"""全局发送队列管理

所有任务的发送动作统一排队，避免冲突
"""
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Callable, Dict, Any
from pathlib import Path

from src.core.log import Logger
from src.core.config import load_config

log = Logger("send_queue")

# 默认最小间隔（秒），可通过 config.json 覆盖
DEFAULT_MIN_INTERVAL_SEC = 120  # 2分钟


def get_min_interval_sec() -> int:
    """获取最小间隔配置"""
    try:
        config = load_config()
        return config.get("wechat", {}).get("min_delay_between_groups_sec", DEFAULT_MIN_INTERVAL_SEC)
    except:
        return DEFAULT_MIN_INTERVAL_SEC


@dataclass
class SendAction:
    """发送动作"""
    id: str                          # 唯一ID
    scheduled_time: datetime         # 计划执行时间
    task_name: str                   # 任务名称
    group_name: str                  # 群名
    text: str                        # 消息文本
    image_path: Optional[str] = None # 图片路径
    status: str = "pending"          # pending / running / success / failed
    message: str = ""                # 执行结果消息
    created_at: datetime = field(default_factory=datetime.now)
    executed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "scheduled_time": self.scheduled_time.strftime("%Y-%m-%d %H:%M:%S"),
            "task_name": self.task_name,
            "group_name": self.group_name,
            "text": self.text[:50] + "..." if len(self.text) > 50 else self.text,
            "image_path": self.image_path,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "executed_at": self.executed_at.strftime("%Y-%m-%d %H:%M:%S") if self.executed_at else None,
        }


class SendQueue:
    """全局发送队列"""
    
    def __init__(self):
        self._queue: List[SendAction] = []
        self._lock = threading.Lock()
        self._executor_thread: Optional[threading.Thread] = None
        self._running = False
        self._send_func: Optional[Callable] = None
        self._action_counter = 0
    
    def set_send_function(self, func: Callable[[str, str, Optional[Path]], bool]):
        """设置实际发送函数"""
        self._send_func = func
    
    def schedule_actions(
        self,
        task_name: str,
        groups: List[str],
        text: str,
        image_path: Optional[str],
        window_minutes: int = 0
    ) -> List[SendAction]:
        """
        将一组群的发送动作加入队列
        
        Args:
            task_name: 任务名称
            groups: 群列表
            text: 消息文本
            image_path: 图片路径
            window_minutes: 时间窗口（分钟），0表示立即发送
        
        Returns:
            已添加的动作列表
        """
        import random
        
        now = datetime.now()
        actions = []
        
        with self._lock:
            for group in groups:
                # 计算初始时间
                if window_minutes > 0:
                    offset_sec = random.randint(0, window_minutes * 60)
                    initial_time = now + timedelta(seconds=offset_sec)
                else:
                    initial_time = now
                
                # 调整时间避免冲突
                scheduled_time = self._find_available_slot(initial_time)
                
                # 创建动作
                self._action_counter += 1
                action = SendAction(
                    id=f"{task_name}_{self._action_counter}_{int(time.time())}",
                    scheduled_time=scheduled_time,
                    task_name=task_name,
                    group_name=group,
                    text=text,
                    image_path=image_path,
                )
                
                self._queue.append(action)
                actions.append(action)
                
                log.info(f"排队: {group} @ {scheduled_time.strftime('%H:%M:%S')}")
            
            # 按时间排序
            self._queue.sort(key=lambda x: x.scheduled_time)
        
        return actions
    
    def _find_available_slot(self, preferred_time: datetime) -> datetime:
        """找到一个不冲突的时间槽"""
        candidate = preferred_time
        min_interval = get_min_interval_sec()
        
        # 获取所有待执行的时间点
        existing_times = [
            a.scheduled_time for a in self._queue 
            if a.status == "pending"
        ]
        
        if not existing_times:
            return candidate
        
        # 检查是否冲突，如果冲突则调整
        max_attempts = 100  # 防止无限循环
        for _ in range(max_attempts):
            conflict = False
            for existing in existing_times:
                diff = abs((candidate - existing).total_seconds())
                if diff < min_interval:
                    # 冲突，往后挪
                    candidate = existing + timedelta(seconds=min_interval)
                    conflict = True
                    break
            
            if not conflict:
                break
        
        return candidate
    
    def get_queue(self, include_completed: bool = False) -> List[Dict[str, Any]]:
        """获取队列状态"""
        with self._lock:
            if include_completed:
                actions = self._queue
            else:
                actions = [a for a in self._queue if a.status in ("pending", "running")]
            
            return [a.to_dict() for a in actions]
    
    def get_pending_count(self) -> int:
        """获取待执行数量"""
        with self._lock:
            return len([a for a in self._queue if a.status == "pending"])
    
    def clear_completed(self):
        """清理已完成的动作"""
        with self._lock:
            self._queue = [a for a in self._queue if a.status in ("pending", "running")]
    
    def clear_all(self):
        """清空所有待执行动作"""
        with self._lock:
            # 只保留正在执行的
            self._queue = [a for a in self._queue if a.status == "running"]
            log.info("队列已清空")
    
    def clear_task(self, task_name: str):
        """清空指定任务的待执行动作"""
        with self._lock:
            before = len([a for a in self._queue if a.status == "pending"])
            self._queue = [
                a for a in self._queue 
                if a.status != "pending" or a.task_name != task_name
            ]
            after = len([a for a in self._queue if a.status == "pending"])
            removed = before - after
            if removed > 0:
                log.info(f"已清除任务 '{task_name}' 的 {removed} 个待发送动作")
    
    def start_executor(self):
        """启动执行器线程"""
        if self._executor_thread and self._executor_thread.is_alive():
            return
        
        self._running = True
        self._executor_thread = threading.Thread(target=self._executor_loop, daemon=True)
        self._executor_thread.start()
        log.info("发送队列执行器已启动")
    
    def stop_executor(self):
        """停止执行器"""
        self._running = False
        if self._executor_thread:
            self._executor_thread.join(timeout=5)
        log.info("发送队列执行器已停止")
    
    def _executor_loop(self):
        """执行器主循环"""
        while self._running:
            try:
                action = self._get_next_action()
                if action:
                    self._execute_action(action)
                else:
                    time.sleep(1)  # 无任务时休眠
            except Exception as e:
                log.error(f"执行器错误: {e}")
                time.sleep(5)
    
    def _get_next_action(self) -> Optional[SendAction]:
        """获取下一个到期的动作"""
        now = datetime.now()
        
        with self._lock:
            for action in self._queue:
                if action.status == "pending" and action.scheduled_time <= now:
                    action.status = "running"
                    return action
        
        return None
    
    def _execute_action(self, action: SendAction):
        """执行发送动作"""
        log.info(f"执行发送: {action.group_name} (任务: {action.task_name})")
        
        try:
            if self._send_func:
                image_path = Path(action.image_path) if action.image_path else None
                success = self._send_func(action.group_name, action.text, image_path)
                
                with self._lock:
                    action.executed_at = datetime.now()
                    if success:
                        action.status = "success"
                        action.message = "发送成功"
                    else:
                        action.status = "failed"
                        action.message = "发送失败"
            else:
                with self._lock:
                    action.status = "failed"
                    action.message = "发送函数未设置"
                    
        except Exception as e:
            with self._lock:
                action.executed_at = datetime.now()
                action.status = "failed"
                action.message = str(e)
            log.error(f"发送失败: {action.group_name}, 错误: {e}")


# 全局单例
_queue_instance: Optional[SendQueue] = None
_queue_lock = threading.Lock()


def get_send_queue() -> SendQueue:
    """获取全局发送队列"""
    global _queue_instance
    
    with _queue_lock:
        if _queue_instance is None:
            _queue_instance = SendQueue()
        return _queue_instance

