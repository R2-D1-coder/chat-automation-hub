"""
飞书通知监听器 - 基于 UI Automation 的通知弹窗检测

使用方案 A：检测通知弹窗 + 按需提取消息
- 检测阶段：每 0.3 秒扫描通知弹窗（无干扰）
- 提取阶段：检测到通知后，提取消息内容并输出到日志

运行方式:
  python -m src.adapters.feishu_notification
"""

import time
import uiautomation as auto
from typing import Set, Dict, Optional, List
from pathlib import Path

from src.core.log import Logger

log = Logger("feishu_notification")


def find_notification_windows() -> List[Dict]:
    """查找所有可能的通知弹窗"""
    notification_windows = []
    
    try:
        root = auto.GetRootControl()
        
        for win in root.GetChildren():
            try:
                class_name = win.ClassName or ""
                name = win.Name or ""
                
                # 检测所有 Chrome_WidgetWin 窗口
                if "Chrome_WidgetWin" in class_name:
                    rect = win.BoundingRectangle
                    width = rect.width() if rect else 0
                    height = rect.height() if rect else 0
                    
                    # 通知弹窗特征：
                    # 1. 类名包含 Chrome_WidgetWin
                    # 2. 窗口较小（宽度 < 600, 高度 < 300）
                    # 3. 窗口名包含群名/消息内容（冒号、括号等），或者窗口很小
                    is_small_window = 0 < width < 600 and 0 < height < 300
                    has_message_format = (": " in name or "（" in name or "(" in name) and len(name) < 150
                    is_very_small = 0 < width < 400 and 0 < height < 200
                    
                    # 放宽条件：小窗口 + (有消息格式 或 非常小)
                    should_check = is_small_window and (has_message_format or is_very_small)
                    
                    # 如果窗口名包含中文，也可能是通知（飞书通知通常有中文）
                    has_chinese = any('\u4e00' <= char <= '\u9fff' for char in name) if name else False
                    if not should_check and is_small_window and has_chinese:
                        should_check = True
                    
                    if should_check:
                        # 检查窗口内是否有文本内容
                        texts = []
                        try:
                            # 递归查找所有文本控件
                            def collect_texts(control, depth=0):
                                if depth > 5:  # 限制深度
                                    return
                                try:
                                    if control.ControlTypeName == "TextControl":
                                        text = control.Name or ""
                                        if text and text.strip():
                                            texts.append(text.strip())
                                    for child in control.GetChildren():
                                        collect_texts(child, depth + 1)
                                except:
                                    pass
                            
                            collect_texts(win)
                        except:
                            pass
                        
                        # 如果窗口名有内容，也加入
                        if name and name.strip() and name not in texts:
                            texts.insert(0, name.strip())
                        
                        notification_windows.append({
                            "window": win,
                            "class_name": class_name,
                            "name": name,
                            "texts": texts,
                            "rect": rect,
                            "size": (width, height)
                        })
            except Exception:
                pass
                
    except Exception as e:
        log.error("扫描窗口时出错", error=str(e))
    
    return notification_windows


def parse_notification_content(texts: List[str]) -> Dict[str, str]:
    """解析通知内容
    
    从文本列表中提取群名和消息内容
    格式可能是：
    - ["消息同步（测试）", "Lisa: 测试"]
    - ["群名", "发送者: 消息内容"]
    """
    result = {
        "group": "",
        "sender": "",
        "content": ""
    }
    
    if not texts:
        return result
    
    # 第一个文本通常是群名
    if len(texts) > 0:
        result["group"] = texts[0]
    
    # 第二个文本通常是 "发送者: 消息内容"
    if len(texts) > 1:
        message_text = texts[1]
        if ": " in message_text:
            parts = message_text.split(": ", 1)
            result["sender"] = parts[0]
            result["content"] = parts[1] if len(parts) > 1 else ""
        else:
            result["content"] = message_text
    
    return result


class FeishuNotificationMonitor:
    """飞书通知监听器"""
    
    def __init__(
        self,
        monitor_groups: Optional[List[str]] = None,
        check_interval: float = 0.3,
        debounce_seconds: float = 0.3
    ):
        """
        Args:
            monitor_groups: 要监控的群列表，None 表示监控所有群
            check_interval: 检测间隔（秒）
            debounce_seconds: 防抖时间（秒），同一群在指定时间内只触发一次
        """
        self.monitor_groups = monitor_groups
        self.check_interval = check_interval
        self.debounce_seconds = debounce_seconds
        
        # 记录已处理的通知（防抖）
        self.seen_notifications: Set[tuple] = set()
        self.last_notification_time: Dict[str, float] = {}
        
        self.check_count = 0
        self.running = False
    
    def start(self):
        """启动监听"""
        self.running = True
        
        if self.monitor_groups:
            log.info("启动飞书通知监听", 
                    groups=", ".join(self.monitor_groups),
                    check_interval=self.check_interval,
                    debounce=self.debounce_seconds)
        else:
            log.info("启动飞书通知监听（监控所有群）",
                    check_interval=self.check_interval,
                    debounce=self.debounce_seconds)
        
        try:
            while self.running:
                self.check_count += 1
                
                # 每 100 次检查（约 30 秒）输出一次状态
                if self.check_count % 100 == 0:
                    log.debug("持续监听中", check_count=self.check_count)
                
                # 查找通知弹窗
                notification_windows = find_notification_windows()
                
                for notif_info in notification_windows:
                    texts = notif_info["texts"]
                    
                    if not texts:
                        continue
                    
                    # 解析通知内容
                    parsed = parse_notification_content(texts)
                    group = parsed["group"]
                    sender = parsed["sender"]
                    content = parsed["content"]
                    
                    # 如果指定了监控群列表，检查是否在列表中
                    if self.monitor_groups is not None and group:
                        if group not in self.monitor_groups:
                            continue
                    
                    # 创建通知的唯一标识
                    notification_key = (group, sender, content)
                    current_time = time.time()
                    
                    # 防抖检查
                    if notification_key not in self.seen_notifications:
                        # 检查时间间隔
                        if group and group in self.last_notification_time:
                            time_diff = current_time - self.last_notification_time[group]
                            if time_diff < self.debounce_seconds:
                                continue
                        
                        # 记录通知
                        self.seen_notifications.add(notification_key)
                        if group:
                            self.last_notification_time[group] = current_time
                        
                        # 输出到日志
                        self._log_notification(group, sender, content, notif_info)
                
                time.sleep(self.check_interval)
                
        except KeyboardInterrupt:
            log.info("收到停止信号，正在停止监听...")
            self.stop()
        except Exception as e:
            log.error("监听过程中出错", error=str(e))
            import traceback
            log.error("错误详情", traceback=traceback.format_exc())
    
    def _log_notification(
        self,
        group: str,
        sender: str,
        content: str,
        notif_info: Dict
    ):
        """记录通知到日志"""
        log.info("=" * 60)
        log.info("检测到飞书通知",
                group=group or "(未知)",
                sender=sender or "(未知)",
                content=content or "(无内容)")
        
        # 记录详细信息
        log.debug("通知详情",
                 window_class=notif_info['class_name'],
                 window_name=notif_info['name'] or "(无名称)",
                 window_size=f"{notif_info['size'][0]}x{notif_info['size'][1]}",
                 all_texts=notif_info['texts'])
        
        log.info("=" * 60)
    
    def stop(self):
        """停止监听"""
        self.running = False
        log.info("飞书通知监听已停止", total_checks=self.check_count)


def main():
    """主函数"""
    import sys
    
    # 配置监控的群列表
    monitor_groups = [
        "消息同步（测试）",
        "所有群<合约地址>监控",
    ]
    
    # 创建监听器
    monitor = FeishuNotificationMonitor(
        monitor_groups=monitor_groups,
        check_interval=0.3,  # 每 0.3 秒检测一次
        debounce_seconds=0.3  # 0.3 秒内同一群只触发一次
    )
    
    try:
        monitor.start()
    except KeyboardInterrupt:
        log.info("程序被用户中断")
    except Exception as e:
        log.error("程序异常退出", error=str(e))
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

