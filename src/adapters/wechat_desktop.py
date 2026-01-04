"""微信桌面客户端适配器 - 独立窗口版

使用前提：目标群的聊天窗口需要提前作为独立窗口打开（在微信中双击聊天）
"""
import io
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

import pyperclip
import uiautomation as auto

from src.core.config import load_config
from src.core.dedupe import should_send, mark_sent
from src.core.log import Logger
from src.core.ratelimit import get_rate_limiter, reset_rate_limiter
from src.core.retry import retry

# 输出目录
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

log = Logger("wechat_adapter")


def _safe_sleep(min_sec: float = 0.1, max_sec: float = 0.4):
    """随机延迟"""
    time.sleep(random.uniform(min_sec, max_sec))


def _copy_image_to_clipboard(image_path: Path) -> bool:
    """将图片复制到 Windows 剪贴板"""
    try:
        import win32clipboard
        from PIL import Image
        
        img = Image.open(image_path)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        output = io.BytesIO()
        img.save(output, format='BMP')
        bmp_data = output.getvalue()[14:]  # 去掉 BMP 文件头
        output.close()
        
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
        win32clipboard.CloseClipboard()
        
        log.debug("图片已复制到剪贴板", path=str(image_path))
        return True
        
    except Exception as e:
        log.error("复制图片到剪贴板失败", error=str(e))
        return False


# ============================================================
# 独立窗口操作函数
# ============================================================

def find_independent_chat_windows() -> List[Dict[str, Any]]:
    """
    查找所有微信独立聊天窗口
    
    Returns:
        窗口信息列表，每个元素包含 name, pure_name, window, rect
    """
    windows = []
    try:
        root = auto.GetRootControl()
        
        for win in root.GetChildren():
            try:
                class_name = win.ClassName or ""
                name = win.Name or ""
                
                # 微信聊天窗口特征：Qt51514QWindowIcon 类名，且名字不是"微信"
                if "Qt51514QWindowIcon" in class_name and name and name != "微信":
                    # 提取纯群名（去掉可能的消息数，如 "家人们(5)" -> "家人们"）
                    pure_name = re.sub(r'\(\d+\)$', '', name).strip()
                    windows.append({
                        "name": name,           # 原始窗口名（可能带消息数）
                        "pure_name": pure_name, # 纯群名
                        "window": win,
                        "rect": win.BoundingRectangle
                    })
            except Exception:
                pass
    except Exception as e:
        log.error(f"查找独立窗口失败", error=str(e))
    
    return windows


def find_window_by_group_name(group_name: str) -> Optional[Dict[str, Any]]:
    """
    按群名查找独立窗口
    
    Args:
        group_name: 群名称
        
    Returns:
        窗口信息字典，未找到返回 None
    """
    windows = find_independent_chat_windows()
    
    # 精确匹配
    for w in windows:
        if w["pure_name"] == group_name or w["name"] == group_name:
            return w
    
    # 模糊匹配
    for w in windows:
        if group_name in w["pure_name"] or group_name in w["name"]:
            return w
    
    return None


def focus_independent_window(window_info: Dict[str, Any]) -> bool:
    """聚焦独立窗口并点击输入框区域"""
    try:
        win = window_info["window"]
        name = window_info["name"]
        
        win.SetFocus()
        time.sleep(0.2)
        
        # 获取窗口位置
        rect = win.BoundingRectangle
        if rect:
            # 点击窗口底部 1/5 处（输入框区域）
            # 输入框大约在窗口高度的 85% 位置
            center_x = (rect.left + rect.right) // 2
            input_y = rect.top + int((rect.bottom - rect.top) * 0.85)
            
            try:
                auto.Click(center_x, input_y)
                log.debug(f"点击输入框区域: ({center_x}, {input_y})")
            except Exception:
                # 备用方案：直接点击窗口
                try:
                    win.Click()
                except Exception:
                    pass
        else:
            # 无法获取位置，使用默认点击
            try:
                win.Click()
            except Exception:
                pass
        
        time.sleep(0.2)
        log.info(f"独立窗口已聚焦", name=name)
        return True
        
    except Exception as e:
        log.error(f"聚焦独立窗口失败", error=str(e))
        return False


def send_keys(keys: str, delay: float = 0.1):
    """发送按键"""
    auto.SendKeys(keys)
    time.sleep(delay)


# ============================================================
# 异常类
# ============================================================

class SafetyError(Exception):
    """安全保险丝触发异常"""
    pass


class WhitelistError(Exception):
    """白名单校验失败异常"""
    pass


# ============================================================
# 主类
# ============================================================

class WeChatBroadcaster:
    """微信群发广播器（独立窗口版）"""
    
    def __init__(self, config: Optional[dict] = None):
        if config is None:
            config = load_config()
        
        self.config = config
        
        # 微信配置
        wechat_cfg = config.get("wechat", {})
        self.per_message_delay_sec = wechat_cfg.get("per_message_delay_sec", 2.0)
        self.max_per_minute = wechat_cfg.get("max_per_minute", 10)
        self.screenshot_on_error = wechat_cfg.get("screenshot_on_error", True)
        
        # 安全配置
        safety_cfg = config.get("safety", {})
        self.armed = safety_cfg.get("armed", False)
        self.dry_run = safety_cfg.get("dry_run", True)
        
        # 白名单
        self.allowed_groups = set(config.get("allowed_groups", []))
        
        # 初始化限频器
        reset_rate_limiter(self.max_per_minute)
        
        log.info("WeChatBroadcaster 初始化完成",
                 armed=self.armed,
                 dry_run=self.dry_run,
                 allowed_groups=len(self.allowed_groups))
    
    def _take_screenshot(self, context: str) -> Optional[Path]:
        """错误时截图保存"""
        if not self.screenshot_on_error:
            return None
        
        safe_context = "".join(c if c.isalnum() or c in "-_" else "_" for c in context)
        
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"wechat_error_{safe_context}_{ts}.png"
            filepath = OUTPUT_DIR / filename
            
            # 使用 PIL 截图
            from PIL import ImageGrab
            screenshot = ImageGrab.grab()
            screenshot.save(str(filepath))
            
            if filepath.exists():
                log.info(f"截图已保存", path=str(filepath))
                return filepath
            
            return None
            
        except Exception as e:
            log.error(f"截图失败", error=str(e))
            return None
    
    def _ensure_windows_ready(self, groups: List[str]) -> bool:
        """确保独立窗口就绪"""
        if self.dry_run:
            log.info("[DRY_RUN] 跳过窗口检查")
            return True
        
        available = find_independent_chat_windows()
        
        if not available:
            log.error("未找到任何微信独立聊天窗口！")
            log.error("请先在微信中双击聊天打开独立窗口")
            self._take_screenshot("no_independent_windows")
            return False
        
        log.info(f"找到 {len(available)} 个独立聊天窗口:")
        for w in available:
            log.info(f"  - {w['pure_name']}")
        
        # 检查目标群是否都有窗口
        missing = [g for g in groups if not find_window_by_group_name(g)]
        if missing:
            log.warn(f"以下群没有打开独立窗口: {missing}")
        
        return True
    
    @retry(max_attempts=3, base_delay=1.0, jitter=0.3, exceptions=(Exception,))
    def _send_to_group(self, group_name: str, text: str, image_path: Optional[Path] = None):
        """发送消息到指定群"""
        if self.dry_run:
            log.info(f"[DRY_RUN] 将发送到群",
                     group=group_name,
                     text_len=len(text),
                     has_image=image_path is not None)
            return
        
        log.info("=" * 40)
        log.info(f"[发送] 目标: {group_name}")
        
        # 1. 查找窗口
        window_info = find_window_by_group_name(group_name)
        if not window_info:
            available = find_independent_chat_windows()
            log.error(f"未找到 '{group_name}' 的独立窗口")
            if available:
                log.info(f"可用窗口: {[w['pure_name'] for w in available]}")
            raise RuntimeError(f"未找到群 '{group_name}' 的独立窗口")
        
        log.info(f"找到窗口: {window_info['name']}")
        
        # 2. 聚焦窗口
        if not focus_independent_window(window_info):
            raise RuntimeError(f"无法聚焦 '{group_name}' 的窗口")
        
        # 3. 发送图片
        if image_path and image_path.exists():
            log.info(f"发送图片: {image_path}")
            if _copy_image_to_clipboard(image_path):
                send_keys("{Ctrl}v", 0.3)
                send_keys("{Enter}", 0.5)
                log.info("图片已发送")
            else:
                log.warn("图片复制失败，跳过")
        
        # 4. 发送文本
        log.info(f"发送文本 ({len(text)} 字符)")
        pyperclip.copy(text)
        _safe_sleep(0.1, 0.15)
        send_keys("{Ctrl}v", 0.2)
        send_keys("{Enter}", 0.3)
        
        log.info(f"[完成] {group_name}")
        log.info("=" * 40)
    
    def _validate_whitelist(self, groups: List[str]):
        """校验白名单"""
        invalid = [g for g in groups if g not in self.allowed_groups]
        if invalid:
            raise WhitelistError(f"以下群不在白名单中: {invalid}")
    
    def broadcast(self, groups: List[str], text: str, image_path: Optional[Path] = None, 
                  task_name: str = "手动任务", immediate: bool = False, 
                  random_delay_minutes: Optional[int] = None) -> dict:
        """
        广播消息到多个群
        
        Args:
            groups: 目标群列表（需要提前打开独立窗口）
            text: 消息文本
            image_path: 可选的图片路径
            task_name: 任务名称
            immediate: 是否立即发送（跳过队列，用于测试）
            random_delay_minutes: 随机延时（分钟），None 表示使用配置文件的默认值
            
        Returns:
            执行结果统计
        """
        from src.core.send_queue import get_send_queue
        
        log.info("=" * 50)
        log.info("开始广播任务",
                 groups=len(groups),
                 text_len=len(text),
                 has_image=image_path is not None,
                 armed=self.armed,
                 dry_run=self.dry_run,
                 immediate=immediate)
        
        # 1. 白名单校验
        self._validate_whitelist(groups)
        log.info("白名单校验通过")
        
        # 2. 安全保险丝
        if not self.dry_run and not self.armed:
            raise SafetyError("安全保险丝未解除！设置 armed=true 启用发送")
        
        # 3. 检查独立窗口
        if not self._ensure_windows_ready(groups):
            raise RuntimeError("独立窗口未就绪，请先打开目标群的独立聊天窗口")
        
        # 4. 立即执行模式（用于测试，不进队列，不检查间隔）
        if immediate:
            log.info("【立即执行模式】跳过队列，直接发送")
            stats = {"sent": 0, "failed": 0, "skipped": 0, "scheduled": 0}
            
            for i, group in enumerate(groups, 1):
                log.info(f">>> 立即发送 {i}/{len(groups)}: {group}")
                try:
                    self._send_to_group(group, text, image_path)
                    mark_sent(group)
                    stats["sent"] += 1
                except Exception as e:
                    log.error(f"发送失败", group=group, error=str(e))
                    stats["failed"] += 1
                
                # 消息间短暂延迟
                if i < len(groups):
                    time.sleep(self.per_message_delay_sec)
            
            log.info("立即执行完成", **stats)
            log.info("=" * 50)
            return stats
        
        # 5. 队列模式：过滤需要发送的群（去重检查）
        groups_to_send = []
        min_interval = self.config.get("wechat", {}).get("min_send_interval_sec", 60)
        
        for group in groups:
            if not should_send(group, min_interval_sec=min_interval):
                log.info(f"    跳过（间隔内）: {group}")
                continue
            groups_to_send.append(group)
        
        if not groups_to_send:
            log.info("没有需要发送的群")
            return {"scheduled": 0, "skipped": len(groups), "sent": 0, "failed": 0}
        
        # 6. 获取随机延时配置（优先使用任务级配置，否则使用全局配置）
        if random_delay_minutes is None:
            random_delay_minutes = self.config.get("wechat", {}).get("random_delay_minutes", 30)
        
        # 7. 加入全局发送队列
        queue = get_send_queue()
        
        # 设置发送函数（如果还没设置）
        queue.set_send_function(self._do_send)
        
        # 启动执行器（如果还没启动）
        queue.start_executor()
        
        # 加入队列
        image_str = str(image_path) if image_path else None
        actions = queue.schedule_actions(
            task_name=task_name,
            groups=groups_to_send,
            text=text,
            image_path=image_str,
            window_minutes=random_delay_minutes
        )
        
        log.info(f"已加入队列 {len(actions)} 个发送任务")
        for action in actions:
            log.info(f"    {action.scheduled_time.strftime('%H:%M:%S')} → {action.group_name}")
        
        stats = {
            "scheduled": len(actions),
            "skipped": len(groups) - len(groups_to_send),
            "sent": 0,  # 实际发送由队列异步完成
            "failed": 0
        }
        
        log.info("广播任务已调度", **stats)
        log.info("=" * 50)
        return stats
    
    def _do_send(self, group_name: str, text: str, image_path: Optional[Path]) -> bool:
        """
        实际执行发送（供队列调用）
        
        Returns:
            是否成功
        """
        try:
            self._send_to_group(group_name, text, image_path)
            mark_sent(group_name)
            return True
        except Exception as e:
            log.error(f"发送失败", group=group_name, error=str(e))
            if not self.dry_run:
                self._take_screenshot(f"send_failed_{group_name}")
            return False
