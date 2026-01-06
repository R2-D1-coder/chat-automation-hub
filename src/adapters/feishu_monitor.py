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
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s][%(name)s][%(levelname)s] %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

# Windows API 常量
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
WINEVENT_OUTOFCONTEXT = 0x0000

user32 = ctypes.windll.user32


def parse_notification_content(texts: List[str], monitor_groups: Optional[List[str]] = None) -> Dict[str, str]:
    """解析通知内容"""
    result = {
        "group": "",
        "sender": "",
        "content": ""
    }

    cleaned = [t.strip() for t in (texts or []) if t and str(t).strip()]
    if not cleaned:
        return result

    # 1) 优先用 monitor_groups 定位群名（Windows Toast 往往会额外带 App 名等字段）
    group = ""
    if monitor_groups:
        for t in cleaned:
            for g in monitor_groups:
                if not g:
                    continue
                if g in t or t in g:
                    group = t
                    break
            if group:
                break

    # 2) 兜底：找一个不像“发送者: 内容”的行当群名
    if not group:
        for t in cleaned:
            if t in ("飞书", "Feishu", "Lark"):
                continue
            if ": " in t or "：" in t:
                continue
            group = t
            break
        if not group:
            group = cleaned[0]

    # 3) 找消息行（支持英文/中文冒号）
    sep = None
    message_text = ""
    start_idx = 0
    try:
        start_idx = cleaned.index(group) + 1
    except ValueError:
        start_idx = 0

    for t in cleaned[start_idx:]:
        if ": " in t:
            sep = ": "
            message_text = t
            break
        if "：" in t:
            sep = "："
            message_text = t
            break

    if message_text and sep:
        parts = message_text.split(sep, 1)
        result["sender"] = parts[0].strip()
        result["content"] = parts[1].strip() if len(parts) > 1 else ""
    else:
        # 兜底：取 group 后第一条非空文本作为内容
        for t in cleaned[start_idx:]:
            if t and t != group:
                result["content"] = t
                break

    result["group"] = group

    return result


def check_if_notification_window(hwnd, monitor_groups: Optional[List[str]] = None) -> Optional[Dict]:
    """检查窗口是否是通知弹窗"""
    if not HAS_UIAUTOMATION:
        return None

    try:
        control = auto.ControlFromHandle(hwnd)
        if not control:
            return None

        class_name = control.ClassName or ""
        name = control.Name or ""

        rect = control.BoundingRectangle
        width = rect.width() if rect else 0
        height = rect.height() if rect else 0

        # 通知弹窗特征：小窗口（飞书应用内弹窗/Windows Toast 都符合）
        is_small_window = 0 < width < 900 and 0 < height < 450
        if not is_small_window:
            return None

        # 收集窗口内的文本
        texts = []
        try:
            def collect_texts(ctrl, depth=0):
                if depth > 5:
                    return
                try:
                    text = (ctrl.Name or "").strip()
                    if text:
                        texts.append(text)
                    for child in ctrl.GetChildren():
                        collect_texts(child, depth + 1)
                except:
                    pass

            collect_texts(control)
        except:
            pass

        if name and name.strip() and name not in texts:
            texts.insert(0, name.strip())

        # 去重（保持顺序）
        if texts:
            seen = set()
            deduped = []
            for t in texts:
                if t in seen:
                    continue
                seen.add(t)
                deduped.append(t)
            texts = deduped

        if not texts:
            return None

        # 限制：尽量只保留飞书相关（避免大量误判）
        hay = " ".join(texts + [name, class_name])
        has_feishu_keyword = ("飞书" in hay) or ("Feishu" in hay) or ("Lark" in hay)
        has_group_match = False
        if monitor_groups:
            for g in monitor_groups:
                if not g:
                    continue
                if g in hay:
                    has_group_match = True
                    break

        if monitor_groups and not has_group_match and not has_feishu_keyword:
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
        self._start_event = threading.Event()
        self._start_ok = False
        self._start_error: Optional[str] = None

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

            # 快速筛选：只处理小窗口（避免对系统大量事件做 UIA 解析）
            try:
                rect = wintypes.RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                if width <= 0 or height <= 0 or width >= 900 or height >= 450:
                    return
            except Exception:
                return

            # hwnd 短时间去重（Toast 可能复用同一窗口句柄）
            now = time.time()
            with self._lock:
                last = self.known_windows.get(hwnd)
                if last and (now - last) < 1.0:
                    return
                self.known_windows[hwnd] = now

            # 延迟等待窗口加载
            time.sleep(0.6)

            # 检查是否是通知
            notif_info = check_if_notification_window(hwnd, self.monitor_groups)
            if not notif_info:
                time.sleep(0.3)
                notif_info = check_if_notification_window(hwnd, self.monitor_groups)
            if not notif_info:
                return

            texts = notif_info.get("texts", [])
            if not texts:
                return

            # 解析内容
            parsed = parse_notification_content(texts, self.monitor_groups)
            group = parsed["group"]
            sender = parsed["sender"]
            content = parsed["content"]

            # 群过滤
            if self.monitor_groups is not None:
                ok = False
                for g in self.monitor_groups:
                    if not g:
                        continue
                    if g == group or (g in group) or (group in g):
                        ok = True
                        break
                if not ok:
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
        uia_init = None
        try:
            # uiautomation 需要在当前线程进行 COM/UIAutomation 初始化，否则会报 “尚未调用 CoInitialize”
            if HAS_UIAUTOMATION:
                uia_init = auto.UIAutomationInitializerInThread()

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
                self._start_ok = False
                self._start_error = "SetWinEventHook 失败"
                logger.error("设置事件钩子失败")
                self._start_event.set()
                return

            self._start_ok = True
            self._start_error = None
            logger.info("事件钩子已设置")
            self._start_event.set()

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
        except Exception as e:
            self._start_ok = False
            self._start_error = str(e)
            logger.error(f"飞书监听线程异常: {e}")
        finally:
            # 确保 start() 不会无限等待
            self._start_event.set()

            if self.hook:
                try:
                    user32.UnhookWinEvent(self.hook)
                except Exception:
                    pass
                self.hook = None

            if uia_init is not None:
                try:
                    uia_init.Uninitialize()
                except Exception:
                    pass

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
        self._start_event.clear()
        self._start_ok = False
        self._start_error = None

        # 在独立线程运行消息循环
        self._thread = threading.Thread(target=self._run_message_loop, daemon=True)
        self._thread.start()

        # 等待线程完成基础启动（事件钩子/COM 初始化）
        self._start_event.wait(timeout=3)
        if not self._start_ok:
            err = self._start_error or "未知错误"
            logger.error(f"飞书通知监听启动失败: {err}")
            self.running = False
            return False

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
