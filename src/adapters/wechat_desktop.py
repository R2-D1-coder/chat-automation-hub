"""微信桌面客户端适配器 - 独立窗口版"""
import ctypes
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
PROJECT_ROOT = Path(__file__).parent.parent.parent

log = Logger("wechat_adapter")


def _safe_sleep(min_sec: float = 0.1, max_sec: float = 0.4):
    """随机延迟，防止快捷键操作过快导致丢失"""
    time.sleep(random.uniform(min_sec, max_sec))


def _click_wechat_input_box() -> bool:
    """
    点击微信输入框区域，将焦点移到输入框
    
    Returns:
        True 如果成功，False 如果失败
    """
    try:
        import win32gui
        import win32api
        import win32con
        
        # 找到微信窗口
        hwnd = _find_wechat_window_by_process()
        if not hwnd:
            log.warn("未找到微信窗口，无法点击输入框")
            return False
        
        # 获取窗口位置和大小
        rect = win32gui.GetWindowRect(hwnd)
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top
        
        # 计算输入框位置（窗口右下角区域）
        # 输入框大约在：水平 60%，垂直 92%
        click_x = left + int(width * 0.6)
        click_y = top + int(height * 0.92)
        
        log.info(f"点击输入框", x=click_x, y=click_y, window_rect=rect)
        
        # 移动鼠标并点击
        win32api.SetCursorPos((click_x, click_y))
        time.sleep(0.1)
        
        # 点击
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, click_x, click_y, 0, 0)
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, click_x, click_y, 0, 0)
        
        log.info("输入框点击完成")
        return True
        
    except Exception as e:
        log.error(f"点击输入框失败", error=str(e))
        return False


def _find_wechat_window_by_process() -> Optional[int]:
    """
    通过进程名查找微信主窗口
    
    Returns:
        窗口句柄 hwnd，或 None
    """
    try:
        import win32gui
        import win32process
        import psutil
        
        # 查找 Weixin 或 WeChat 进程
        wechat_pids = set()
        for proc in psutil.process_iter(['pid', 'name']):
            name = proc.info['name'].lower()
            if 'weixin' in name or 'wechat' in name:
                wechat_pids.add(proc.info['pid'])
        
        if not wechat_pids:
            log.warn("未找到微信进程")
            return None
        
        log.info(f"找到微信进程", pids=list(wechat_pids))
        
        # 查找属于这些进程的窗口
        target_hwnd = None
        
        def enum_callback(hwnd, _):
            nonlocal target_hwnd
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid in wechat_pids:
                    # 检查是否是主窗口（有标题、可见或可以显示）
                    title = win32gui.GetWindowText(hwnd)
                    classname = win32gui.GetClassName(hwnd)
                    
                    # 微信主窗口的类名通常是 WeChatMainWndForPC 或类似
                    if 'WeChatMainWnd' in classname or 'WeChatLogin' in classname:
                        target_hwnd = hwnd
                        log.info(f"找到微信窗口", hwnd=hwnd, title=title, classname=classname)
                        return False
                    
                    # 备选：有标题的窗口
                    if title and target_hwnd is None:
                        target_hwnd = hwnd
            except Exception:
                pass
            return True
        
        win32gui.EnumWindows(enum_callback, None)
        return target_hwnd
        
    except ImportError as e:
        log.warn(f"缺少依赖库", error=str(e))
        return None
    except Exception as e:
        log.error(f"查找微信窗口失败", error=str(e))
        return None


def _activate_window_by_hwnd(hwnd: int) -> bool:
    """
    通过窗口句柄激活窗口
    """
    try:
        import win32gui
        import win32con
        
        # 检查窗口是否可见
        is_visible = win32gui.IsWindowVisible(hwnd)
        is_iconic = win32gui.IsIconic(hwnd)
        
        log.info(f"窗口状态", hwnd=hwnd, visible=is_visible, iconic=is_iconic)
        
        # 如果窗口不可见（在托盘中），尝试运行微信 exe 来激活
        if not is_visible:
            log.info("窗口不可见，尝试通过运行 exe 激活...")
            return _activate_wechat_by_exe()
        
        # 如果最小化，恢复
        if is_iconic:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.3)
        
        # 使用 Alt 键技巧绕过 Windows 前台限制
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)  # Alt down
        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)  # Alt up
        
        # 激活窗口
        win32gui.SetForegroundWindow(hwnd)
        win32gui.BringWindowToTop(hwnd)
        
        title = win32gui.GetWindowText(hwnd)
        log.info(f"窗口已激活", hwnd=hwnd, title=title)
        return True
        
    except Exception as e:
        log.error(f"激活窗口失败", hwnd=hwnd, error=str(e))
        return False


def _activate_wechat_by_exe() -> bool:
    """
    通过运行微信 exe 来激活窗口（微信已登录时会自动激活现有窗口）
    """
    try:
        import subprocess
        import psutil
        
        # 查找微信进程获取 exe 路径
        wechat_exe = None
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            name = proc.info['name'].lower()
            if 'weixin' in name or 'wechat' in name:
                exe = proc.info.get('exe')
                if exe and 'weixin' in exe.lower():
                    wechat_exe = exe
                    break
        
        if not wechat_exe:
            # 尝试常见路径
            common_paths = [
                r"C:\Program Files\Tencent\WeChat\WeChat.exe",
                r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe",
            ]
            for path in common_paths:
                if Path(path).exists():
                    wechat_exe = path
                    break
        
        if wechat_exe:
            log.info(f"运行微信 exe 激活窗口", exe=wechat_exe)
            # 运行 exe（如果已登录会激活现有窗口）
            subprocess.Popen([wechat_exe], shell=False)
            time.sleep(1.5)  # 等待窗口出现
            return True
        else:
            log.warn("未找到微信 exe 路径")
            return False
            
    except Exception as e:
        log.error(f"通过 exe 激活失败", error=str(e))
        return False


def _force_activate_window(title_pattern: str) -> bool:
    """
    强制激活微信窗口（只通过进程名查找，避免误匹配浏览器）
    
    Args:
        title_pattern: 已废弃，保留参数兼容性
        
    Returns:
        True 如果成功激活，False 如果失败
    """
    # 只通过进程名查找微信窗口（避免匹配到浏览器标签页）
    hwnd = _find_wechat_window_by_process()
    if hwnd:
        return _activate_window_by_hwnd(hwnd)
    
    # 如果找不到窗口，尝试运行 exe 激活
    log.warn("未找到微信窗口，尝试运行 exe 激活")
    return _activate_wechat_by_exe()


def _copy_image_to_clipboard(image_path: Path) -> bool:
    """
    将图片复制到 Windows 剪贴板
    
    Args:
        image_path: 图片文件路径
        
    Returns:
        True 如果成功，False 如果失败
    """
    try:
        import win32clipboard
        from PIL import Image
        
        # 打开图片并转换为 BMP 格式（Windows 剪贴板格式）
        img = Image.open(image_path)
        
        # 转换为 RGB（如果是 RGBA 或其他格式）
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # 转换为 BMP 格式的字节流
        output = io.BytesIO()
        img.save(output, format='BMP')
        bmp_data = output.getvalue()[14:]  # 去掉 BMP 文件头
        output.close()
        
        # 复制到剪贴板
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
        窗口信息列表，每个元素包含 name, window, rect
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
    
    for w in windows:
        # 精确匹配纯群名
        if w["pure_name"] == group_name:
            return w
        # 也尝试匹配原始窗口名
        if w["name"] == group_name:
            return w
    
    # 模糊匹配（群名包含在窗口名中）
    for w in windows:
        if group_name in w["pure_name"] or group_name in w["name"]:
            return w
    
    return None


def focus_independent_window(window_info: Dict[str, Any]) -> bool:
    """
    聚焦独立窗口
    
    Args:
        window_info: find_window_by_group_name 返回的窗口信息
        
    Returns:
        True 如果成功，False 如果失败
    """
    try:
        win = window_info["window"]
        name = window_info["name"]
        
        # 激活窗口
        win.SetFocus()
        time.sleep(0.2)
        
        # 点击窗口确保获得焦点
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


def send_keys_to_window(keys: str, delay: float = 0.1):
    """
    发送按键（使用 uiautomation）
    
    Args:
        keys: 按键字符串，如 "{Ctrl}v", "{Enter}"
        delay: 按键后延迟
    """
    auto.SendKeys(keys)
    time.sleep(delay)


class SafetyError(Exception):
    """安全保险丝触发异常"""
    pass


class WhitelistError(Exception):
    """白名单校验失败异常"""
    pass


class WeChatBroadcaster:
    """微信群发广播器"""
    
    def __init__(self, config: Optional[dict] = None):
        """
        初始化广播器
        
        Args:
            config: 配置字典，为 None 时从 config.json 加载
        """
        if config is None:
            config = load_config()
        
        # 保存完整配置（供后续方法使用）
        self.config = config
        
        # 微信配置
        wechat_cfg = config.get("wechat", {})
        self.exe_path = wechat_cfg.get("exe_path", r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe")
        self.window_title_regex = wechat_cfg.get("window_title_regex", "微信")
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
        
        # RPA 库实例（延迟初始化）
        self._desktop = None
        self._windows = None
        
        log.info("WeChatBroadcaster 初始化完成",
                 armed=self.armed,
                 dry_run=self.dry_run,
                 allowed_groups=len(self.allowed_groups))
    
    def _get_desktop(self):
        """获取 Desktop 实例（延迟加载）"""
        if self._desktop is None:
            from RPA.Desktop import Desktop
            self._desktop = Desktop()
        return self._desktop
    
    def _get_windows(self):
        """获取 Windows 实例（延迟加载）"""
        if self._windows is None:
            from RPA.Windows import Windows
            self._windows = Windows()
        return self._windows
    
    def _take_screenshot(self, context: str) -> Optional[Path]:
        """
        错误时截图保存
        
        Args:
            context: 上下文标识（用于文件名）
            
        Returns:
            截图文件路径，失败时返回 None
        """
        if not self.screenshot_on_error:
            log.debug("截图功能已禁用")
            return None
        
        # 清理 context 中的非法文件名字符
        safe_context = "".join(c if c.isalnum() or c in "-_" else "_" for c in context)
        
        try:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")  # 添加微秒避免重名
            filename = f"wechat_error_{safe_context}_{ts}.png"
            filepath = OUTPUT_DIR / filename
            
            # 尝试多次截图（有时第一次可能失败）
            for attempt in range(2):
                try:
                    desktop = self._get_desktop()
                    desktop.take_screenshot(str(filepath))
                    
                    # 验证文件确实存在
                    if filepath.exists() and filepath.stat().st_size > 0:
                        log.info(f"截图已保存", path=str(filepath))
                        return filepath
                    else:
                        log.warn("截图文件为空或不存在，重试中")
                        time.sleep(0.3)
                except Exception as e:
                    if attempt == 0:
                        log.warn(f"截图失败，重试中", error=str(e))
                        time.sleep(0.5)
                    else:
                        raise
            
            return None
            
        except Exception as e:
            log.error(f"截图失败", error=str(e))
            return None
    
    def _ensure_wechat_ready(self, groups: Optional[List[str]] = None) -> bool:
        """
        确保微信独立窗口就绪（独立窗口版）
        
        Args:
            groups: 可选，需要检查的群列表
        
        Returns:
            True 如果成功，False 如果失败
        """
        if self.dry_run:
            log.info("[DRY_RUN] 跳过微信窗口检查")
            return True
        
        # 检查是否有独立窗口打开
        available_windows = find_independent_chat_windows()
        
        if not available_windows:
            log.error("未找到任何微信独立聊天窗口！")
            log.error("请先在微信中双击聊天打开独立窗口")
            self._take_screenshot("no_independent_windows")
            return False
        
        log.info(f"找到 {len(available_windows)} 个独立聊天窗口:")
        for w in available_windows:
            log.info(f"  - {w['pure_name']}")
        
        # 如果指定了群列表，检查是否都有对应的独立窗口
        if groups:
            missing = []
            for group in groups:
                if not find_window_by_group_name(group):
                    missing.append(group)
            
            if missing:
                log.warn(f"以下群没有打开独立窗口: {missing}")
                log.warn("这些群的消息将无法发送")
        
        return True
    
    def _focus_window(self, retry_count: int = 3) -> bool:
        """
        每次操作前确保窗口聚焦
        
        Args:
            retry_count: 重试次数
            
        Returns:
            True 如果成功聚焦，False 如果失败
        """
        if self.dry_run:
            return True
        
        for attempt in range(retry_count):
            try:
                # 方法 1: 使用 Win32 API 强制激活（更可靠）
                if _force_activate_window(self.window_title_regex):
                    _safe_sleep(0.3, 0.5)  # 等待窗口完全激活
                    return True
                
                # 方法 2: 备用 - 使用 RPA.Windows
                windows = self._get_windows()
                windows.control_window(f"regex:{self.window_title_regex}")
                _safe_sleep(0.2, 0.3)
                return True
                
            except Exception as e:
                if attempt < retry_count - 1:
                    log.warn(f"聚焦窗口失败，重试中", attempt=attempt + 1, error=str(e))
                    time.sleep(0.5)
                else:
                    log.error(f"聚焦窗口失败，已耗尽重试", error=str(e))
                    self._take_screenshot("focus_failed")
        
        return False
    
    @retry(max_attempts=3, base_delay=1.0, jitter=0.3, exceptions=(Exception,))
    def _send_to_group(self, group_name: str, text: str, image_path: Optional[Path] = None):
        """
        发送消息到指定群（独立窗口版）
        
        前提条件：目标群的聊天窗口已作为独立窗口打开
        
        Args:
            group_name: 群名称
            text: 消息文本
            image_path: 可选的图片路径，如果提供则先发送图片
            
        Raises:
            RuntimeError: 窗口未找到或聚焦失败时
        """
        if self.dry_run:
            log.info(f"[DRY_RUN] 将发送到群",
                     group=group_name,
                     text_len=len(text),
                     has_image=image_path is not None,
                     text_preview=text[:50] + "..." if len(text) > 50 else text)
            return
        
        log.info("=" * 40)
        log.info(f"[开始发送] 目标群: {group_name}")
        
        # 1. 查找独立窗口
        log.info("[步骤 1/5] 查找独立窗口...")
        window_info = find_window_by_group_name(group_name)
        
        if not window_info:
            log.error(f"[步骤 1/5] 未找到群 '{group_name}' 的独立窗口！")
            # 列出当前可用的独立窗口
            available = find_independent_chat_windows()
            if available:
                log.info(f"当前可用的独立窗口: {[w['pure_name'] for w in available]}")
            raise RuntimeError(f"未找到群 '{group_name}' 的独立窗口，请先打开该群的独立聊天窗口")
        
        log.info(f"[步骤 1/5] 找到窗口: {window_info['name']}")
        
        # 2. 聚焦独立窗口
        log.info("[步骤 2/5] 聚焦独立窗口...")
        if not focus_independent_window(window_info):
            raise RuntimeError(f"无法聚焦群 '{group_name}' 的独立窗口")
        log.info("[步骤 2/5] 窗口聚焦成功")
        
        # 3. 验证窗口名称（闭环验证）
        log.info("[步骤 3/5] 验证窗口...")
        _safe_sleep(0.2, 0.3)
        # 重新获取窗口信息验证
        verify_window = find_window_by_group_name(group_name)
        if not verify_window:
            log.warn("[步骤 3/5] 验证失败，窗口可能已关闭")
            raise RuntimeError(f"验证失败：群 '{group_name}' 的窗口可能已关闭")
        log.info(f"[步骤 3/5] 验证通过: {verify_window['name']}")
        
        # 4. 如果有图片，先发送图片
        if image_path and image_path.exists():
            log.info(f"[步骤 4/5] 发送图片: {image_path}")
            if _copy_image_to_clipboard(image_path):
                log.info("[步骤 4/5] 图片已复制到剪贴板，粘贴中...")
                send_keys_to_window("{Ctrl}v", 0.3)
                log.info("[步骤 4/5] 按 Enter 发送图片...")
                send_keys_to_window("{Enter}", 0.5)
                log.info("[步骤 4/5] 图片已发送")
            else:
                log.warn("[步骤 4/5] 图片复制失败，跳过图片发送")
        else:
            log.info("[步骤 4/5] 无图片，跳过")
        
        # 5. 输入消息文本并发送
        log.info(f"[步骤 5/5] 发送文本消息 ({len(text)} 字符)...")
        pyperclip.copy(text)
        _safe_sleep(0.1, 0.15)
        
        log.info("[步骤 5/5] 粘贴文本...")
        send_keys_to_window("{Ctrl}v", 0.2)
        
        log.info("[步骤 5/5] 按 Enter 发送...")
        send_keys_to_window("{Enter}", 0.3)
        
        log.info(f"[发送完成] 群: {group_name}, 文本: {len(text)} 字符, 图片: {image_path is not None}")
        log.info("=" * 40)
    
    def _try_recover_window_state(self):
        """
        尝试恢复窗口状态（发送失败后调用）
        - 按 Esc 关闭可能的弹窗
        """
        if self.dry_run:
            return
        
        try:
            # 按 Esc 关闭可能的弹窗
            send_keys_to_window("{Esc}", 0.2)
            send_keys_to_window("{Esc}", 0.2)
            
            log.debug("窗口状态恢复完成")
        except Exception as e:
            log.warn(f"恢复窗口状态失败", error=str(e))
    
    def _validate_whitelist(self, groups: List[str]):
        """校验群是否在白名单中"""
        invalid_groups = [g for g in groups if g not in self.allowed_groups]
        if invalid_groups:
            raise WhitelistError(f"以下群不在白名单中: {invalid_groups}")
    
    def broadcast(self, groups: List[str], text: str, image_path: Optional[Path] = None) -> dict:
        """
        广播消息到多个群
        
        Args:
            groups: 目标群列表
            text: 消息文本
            image_path: 可选的图片路径
            
        Returns:
            执行结果统计 {"sent": N, "skipped": N, "failed": N}
        """
        log.info("=" * 50)
        log.info("开始广播任务",
                 groups=len(groups),
                 text_len=len(text),
                 has_image=image_path is not None,
                 armed=self.armed,
                 dry_run=self.dry_run)
        
        # 1. 白名单校验
        self._validate_whitelist(groups)
        log.info("白名单校验通过")
        
        # 2. 安全保险丝检查
        log.info(f"安全模式: armed={self.armed}, dry_run={self.dry_run}")
        if not self.dry_run and not self.armed:
            raise SafetyError(
                "安全保险丝未解除！设置 armed=true 以启用真实发送。"
                "当前配置: dry_run=false, armed=false"
            )
        log.info("安全保险丝检查通过")
        
        # 3. 确保微信独立窗口就绪
        log.info("检查微信独立窗口状态...")
        if not self._ensure_wechat_ready(groups):
            log.error("微信独立窗口未就绪！")
            raise RuntimeError("微信独立窗口未就绪，请先打开目标群的独立聊天窗口")
        log.info("微信独立窗口检查完成")
        
        # 4. 执行广播
        stats = {"sent": 0, "skipped": 0, "failed": 0}
        rate_limiter = get_rate_limiter()
        
        for i, group in enumerate(groups, 1):
            log.info(f"")
            log.info(f">>> 处理群 {i}/{len(groups)}: {group}")
            
            # 4.1 去重检查（基于时间间隔，默认 60 秒）
            min_interval = self.config.get("wechat", {}).get("min_send_interval_sec", 60)
            log.info(f"    检查去重（间隔: {min_interval}s）...")
            if not should_send(group, min_interval_sec=min_interval):
                log.info(f"    → 跳过（在间隔时间内）")
                stats["skipped"] += 1
                continue
            log.info(f"    → 可以发送")
            
            # 4.2 限频等待
            waited = rate_limiter.acquire()
            if waited > 0:
                log.info(f"限频等待完成", waited=f"{waited:.2f}s")
            
            # 4.3 发送（带重试）
            try:
                self._send_to_group(group, text, image_path)
                
                # 4.4 只有发送成功才标记（不传 text，只记录时间）
                mark_sent(group)
                stats["sent"] += 1
                
            except Exception as e:
                # 发送失败，不标记！下次可以重试
                log.error(f"发送失败（已耗尽重试）", group=group, error=str(e))
                if not self.dry_run:
                    self._take_screenshot(f"send_failed_{group}")
                stats["failed"] += 1
                
                # 发送失败后尝试恢复窗口状态
                self._try_recover_window_state()
            
            # 4.5 消息间延迟
            if i < len(groups):
                time.sleep(self.per_message_delay_sec)
        
        log.info("广播任务完成", **stats)
        log.info("=" * 50)
        return stats
