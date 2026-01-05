"""
飞书通知监听适配器

基于事件驱动的飞书通知监听（零轮询方案）
使用 Windows WinEventHook API 监听窗口创建事件
检测到消息后转发到 Telegram 群
"""

import time
import ctypes
from ctypes import wintypes
import threading
import logging
import os
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Callable

# 尝试导入 uiautomation
try:
    import uiautomation as auto
    HAS_UIAUTOMATION = True
except ImportError:
    HAS_UIAUTOMATION = False
    auto = None

# 获取 logger
logger = logging.getLogger("feishu_monitor")

# Windows API 常量
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
WINEVENT_OUTOFCONTEXT = 0x0000

user32 = ctypes.windll.user32


def parse_notification_content(texts: List[str]) -> Dict[str, str]:
    """解析通知内容"""
    result = {
        "group": "",
        "sender": "",
        "content": ""
    }

    if not texts:
        return result

    if len(texts) > 0:
        result["group"] = texts[0]

    if len(texts) > 1:
        message_text = texts[1]
        if ": " in message_text:
            parts = message_text.split(": ", 1)
            result["sender"] = parts[0]
            result["content"] = parts[1] if len(parts) > 1 else ""
        else:
            result["content"] = message_text

    return result


def check_if_notification_window(hwnd) -> Optional[Dict]:
    """检查窗口是否是通知弹窗"""
    if not HAS_UIAUTOMATION:
        return None

    try:
        control = auto.ControlFromHandle(hwnd)
        if not control:
            return None

        class_name = control.ClassName or ""
        name = control.Name or ""

        if "Chrome_WidgetWin" not in class_name:
            return None

        rect = control.BoundingRectangle
        width = rect.width() if rect else 0
        height = rect.height() if rect else 0

        # 通知弹窗特征：小窗口
        is_small_window = 0 < width < 600 and 0 < height < 300
        has_message_format = (": " in name or "（" in name or "(" in name) and len(name) < 150
        is_very_small = 0 < width < 400 and 0 < height < 200

        should_check = is_small_window and (has_message_format or is_very_small)

        # 如果窗口名包含中文，也可能是通知
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in name) if name else False
        if not should_check and is_small_window and has_chinese:
            should_check = True

        if not should_check:
            return None

        # 收集窗口内的文本
        texts = []
        try:
            def collect_texts(ctrl, depth=0):
                if depth > 5:
                    return
                try:
                    if ctrl.ControlTypeName == "TextControl":
                        text = ctrl.Name or ""
                        if text and text.strip():
                            texts.append(text.strip())
                    for child in ctrl.GetChildren():
                        collect_texts(child, depth + 1)
                except:
                    pass

            collect_texts(control)
        except:
            pass

        if name and name.strip() and name not in texts:
            texts.insert(0, name.strip())

        if not texts:
            return None

        return {
            "hwnd": hwnd,
            "class_name": class_name,
            "name": name,
            "texts": texts,
            "size": (width, height)
        }
    except Exception:
        return None


class TelegramForwarder:
    """Telegram 转发器"""

    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("enabled", False)
        self.api_id = config.get("api_id", "")
        self.api_hash = config.get("api_hash", "")
        self.session = config.get("session", "")
        self.chat = config.get("chat", "")

        self._client = None
        self._target = None
        self._loop = None  # 保存创建 client 时的 loop
        self._loop_thread = None  # 运行 event loop 的线程
        self._connected = False

    def _run_loop_forever(self, loop: asyncio.AbstractEventLoop):
        """在独立线程中运行 event loop"""
        asyncio.set_event_loop(loop)
        loop.run_forever()

    async def connect(self) -> bool:
        """连接 Telegram"""
        if not self.enabled:
            logger.info("Telegram 转发已禁用")
            return False

        if not self.api_id or not self.api_hash:
            logger.warning("Telegram API 配置不完整")
            return False

        if not self.session:
            logger.warning("Telegram session 未配置")
            return False

        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            from telethon.network.connection.tcpabridged import ConnectionTcpAbridged

            # 创建专用的 event loop 用于 Telegram
            self._loop = asyncio.new_event_loop()

            # 在独立线程中运行 event loop
            self._loop_thread = threading.Thread(
                target=self._run_loop_forever,
                args=(self._loop,),
                daemon=True
            )
            self._loop_thread.start()

            # 在该 loop 中创建和连接 client
            async def _do_connect():
                self._client = TelegramClient(
                    StringSession(self.session),
                    int(self.api_id),
                    self.api_hash,
                    connection=ConnectionTcpAbridged,
                    auto_reconnect=True,
                    connection_retries=10,
                    retry_delay=2,
                )

                await self._client.connect()

                if not await self._client.is_user_authorized():
                    raise Exception("Telegram session 无效或已过期")

                me = await self._client.get_me()
                logger.info(f"Telegram 已登录: {me.first_name} (@{me.username or 'N/A'})")

                # 解析目标
                self._target = await self._resolve_target(self.chat)
                if not self._target:
                    raise Exception(f"未找到 Telegram 目标: {self.chat}")

                return True

            # 使用 run_coroutine_threadsafe 在 loop 线程中执行
            future = asyncio.run_coroutine_threadsafe(_do_connect(), self._loop)
            result = future.result(timeout=60)  # 60秒超时

            self._connected = True
            return result

        except ImportError:
            logger.error("请安装 telethon: pip install telethon")
            return False
        except Exception as e:
            logger.error(f"Telegram 连接失败: {e}")
            return False

    async def _resolve_target(self, target: str):
        """解析 Telegram 目标"""
        if not target or not self._client:
            return None

        target_str = str(target).strip()

        # 数字 ID
        try:
            if target_str.lstrip("-").isdigit():
                return await self._client.get_entity(int(target_str))
        except:
            pass

        # @username
        try:
            if target_str.startswith("@"):
                return await self._client.get_entity(target_str)
        except:
            pass

        # 群标题匹配
        try:
            async for dialog in self._client.iter_dialogs(limit=200):
                if (dialog.name or "").strip() == target_str:
                    return dialog.entity
        except:
            pass

        return None

    async def send_async(self, text: str) -> bool:
        """异步发送消息"""
        if not self._client or not self._target:
            return False

        try:
            if not self._client.is_connected():
                await self._client.connect()

            await self._client.send_message(self._target, text)
            logger.info(f"已转发到 Telegram: {self.chat}")
            return True
        except Exception as e:
            logger.error(f"Telegram 发送失败: {e}")
            return False

    def send(self, text: str) -> bool:
        """同步发送消息（线程安全）"""
        if not self.enabled or not self._client:
            return False

        if self._loop is None or self._loop.is_closed():
            logger.error("Telegram event loop 未运行")
            return False

        try:
            # 使用 run_coroutine_threadsafe 在正确的 loop 中执行
            future = asyncio.run_coroutine_threadsafe(self.send_async(text), self._loop)
            return future.result(timeout=30)  # 30秒超时
        except Exception as e:
            logger.error(f"Telegram 发送异常: {e}")
            return False

    async def disconnect(self):
        """断开连接"""
        if self._client:
            try:
                await self._client.disconnect()
            except:
                pass
            self._client = None

    def disconnect_sync(self):
        """同步断开连接"""
        if self._client and self._loop and not self._loop.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(self.disconnect(), self._loop)
                future.result(timeout=10)
            except:
                pass

        # 停止 event loop
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)

        # 等待线程结束
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=2)

        self._client = None
        self._loop = None
        self._loop_thread = None


class FeishuMonitor:
    """飞书通知监听器"""

    def __init__(self, config: dict):
        """
        初始化监听器

        config 结构:
        {
            "enabled": true,
            "monitor_groups": ["群1", "群2"],  # None 表示监控所有
            "dedupe_seconds": 600,  # 去重窗口（秒）
            "telegram": {
                "enabled": true,
                "api_id": "xxx",
                "api_hash": "xxx",
                "session": "xxx",
                "chat": "目标群"
            }
        }
        """
        self.config = config
        self.enabled = config.get("enabled", False)
        self.monitor_groups = config.get("monitor_groups")
        self.dedupe_seconds = config.get("dedupe_seconds", 600)

        # Telegram 转发器
        tg_config = config.get("telegram", {})
        self.telegram = TelegramForwarder(tg_config)

        # 状态
        self.seen_notifications: Dict[tuple, float] = {}
        self.known_windows: Dict[int, float] = {}
        self._lock = threading.Lock()
        self.hook = None
        self.running = False
        self.notification_count = 0
        self.start_time = None
        self._thread = None
        self._callback = None

        # 回调函数类型
        self.WinEventProcType = ctypes.WINFUNCTYPE(
            None,
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.HWND,
            wintypes.LONG,
            wintypes.LONG,
            wintypes.DWORD,
            wintypes.DWORD
        )

        # 外部回调（可选）
        self.on_notification: Optional[Callable[[str, str, str], None]] = None

    def _format_message(self, group: str, sender: str, content: str) -> str:
        """格式化 Telegram 消息"""
        msg = f"[Feishu]\n"
        msg += f"---\n"
        if group:
            msg += f"Group: {group}\n"
        if sender:
            msg += f"From: {sender}\n"
        if content:
            msg += f"Content:\n{content}\n"
        msg += f"---\n"
        msg += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        return msg

    def _win_event_callback(self, hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        """窗口事件回调"""
        try:
            if idObject != 0:
                return

            if event not in (EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW):
                return

            # 快速检查窗口类名
            try:
                class_name_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_name_buf, 256)
                if "Chrome_WidgetWin" not in class_name_buf.value:
                    return
            except:
                return

            # hwnd 去重
            with self._lock:
                if hwnd in self.known_windows:
                    return
                self.known_windows[hwnd] = time.time()

            # 延迟等待窗口加载
            time.sleep(0.4)

            # 检查是否是通知
            notif_info = check_if_notification_window(hwnd)
            if not notif_info:
                return

            texts = notif_info.get("texts", [])
            if not texts:
                return

            # 解析内容
            parsed = parse_notification_content(texts)
            group = parsed["group"]
            sender = parsed["sender"]
            content = parsed["content"]

            # 群过滤
            if self.monitor_groups is not None:
                if group not in self.monitor_groups:
                    logger.debug(f"忽略非监控群: {group}")
                    return

            # 内容去重
            now = time.time()
            notification_key = (group, sender, content)

            with self._lock:
                last_seen = self.seen_notifications.get(notification_key)
                if last_seen and (now - last_seen) < self.dedupe_seconds:
                    logger.debug(f"忽略重复通知 ({int(now - last_seen)}s): {group}")
                    return

                self.seen_notifications[notification_key] = now

                # 清理旧记录
                if len(self.seen_notifications) > 2000:
                    cutoff = now - self.dedupe_seconds * 1.5
                    self.seen_notifications = {k: v for k, v in self.seen_notifications.items() if v >= cutoff}
                if len(self.known_windows) > 5000:
                    cutoff = now - 300
                    self.known_windows = {k: v for k, v in self.known_windows.items() if v >= cutoff}

            self.notification_count += 1

            logger.info(f"[#{self.notification_count}] {group} | {sender}: {content[:50]}...")

            # 外部回调
            if self.on_notification:
                try:
                    self.on_notification(group, sender, content)
                except Exception as e:
                    logger.error(f"回调执行失败: {e}")

            # Telegram 转发
            if self.telegram.enabled:
                try:
                    msg = self._format_message(group, sender, content)
                    self.telegram.send(msg)
                except Exception as e:
                    logger.error(f"Telegram 转发失败: {e}")

        except Exception as e:
            logger.error(f"事件回调异常: {e}")

    def _run_message_loop(self):
        """运行消息循环（在独立线程中）"""
        self._callback = self.WinEventProcType(self._win_event_callback)

        self.hook = user32.SetWinEventHook(
            EVENT_OBJECT_CREATE,
            EVENT_OBJECT_HIDE,
            0,
            self._callback,
            0,
            0,
            WINEVENT_OUTOFCONTEXT
        )

        if not self.hook:
            logger.error("设置事件钩子失败")
            return

        logger.info("事件钩子已设置")

        msg = wintypes.MSG()

        while self.running:
            bRet = user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 0x0001)
            if bRet:
                if msg.message == 0x0012:  # WM_QUIT
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.01)

        if self.hook:
            user32.UnhookWinEvent(self.hook)
            self.hook = None

    def start(self) -> bool:
        """启动监听"""
        if not self.enabled:
            logger.info("飞书监听已禁用")
            return False

        if not HAS_UIAUTOMATION:
            logger.error("请安装 uiautomation: pip install uiautomation")
            return False

        # 连接 Telegram（connect 内部管理自己的 event loop）
        if self.telegram.enabled:
            # 使用临时 loop 调用 async connect
            loop = asyncio.new_event_loop()
            try:
                tg_ok = loop.run_until_complete(self.telegram.connect())
            finally:
                loop.close()

            if not tg_ok:
                logger.warning("Telegram 连接失败，继续运行但不转发")

        self.running = True
        self.start_time = time.time()
        self.notification_count = 0

        # 在独立线程运行消息循环
        self._thread = threading.Thread(target=self._run_message_loop, daemon=True)
        self._thread.start()

        logger.info("飞书通知监听已启动")
        if self.monitor_groups:
            logger.info(f"监控群: {self.monitor_groups}")
        else:
            logger.info("监控所有群")

        return True

    def stop(self):
        """同步停止监听"""
        self.running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

        # 断开 Telegram（使用新的同步方法）
        self.telegram.disconnect_sync()

        runtime = int(time.time() - (self.start_time or time.time()))
        logger.info(f"飞书监听已停止，运行 {runtime}s，检测 {self.notification_count} 条")

    def get_status(self) -> dict:
        """获取状态"""
        runtime = int(time.time() - (self.start_time or time.time())) if self.running else 0
        return {
            "enabled": self.enabled,
            "running": self.running,
            "runtime_seconds": runtime,
            "notification_count": self.notification_count,
            "monitor_groups": self.monitor_groups,
            "telegram_enabled": self.telegram.enabled,
        }


# 全局实例
_feishu_monitor: Optional[FeishuMonitor] = None


def get_feishu_monitor() -> Optional[FeishuMonitor]:
    """获取全局飞书监听器实例"""
    return _feishu_monitor


def init_feishu_monitor(config: dict) -> FeishuMonitor:
    """初始化全局飞书监听器"""
    global _feishu_monitor
    _feishu_monitor = FeishuMonitor(config)
    return _feishu_monitor


def start_feishu_monitor() -> bool:
    """启动全局飞书监听器"""
    if _feishu_monitor:
        return _feishu_monitor.start()
    return False


def stop_feishu_monitor():
    """停止全局飞书监听器"""
    if _feishu_monitor:
        _feishu_monitor.stop()
