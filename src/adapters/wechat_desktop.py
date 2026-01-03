"""微信桌面客户端适配器"""
import random
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pyperclip

from src.core.config import load_config
from src.core.dedupe import should_send, mark_sent
from src.core.log import Logger
from src.core.ratelimit import get_rate_limiter, reset_rate_limiter
from src.core.retry import retry

# 输出目录
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

log = Logger("wechat_adapter")


def _safe_sleep(min_sec: float = 0.1, max_sec: float = 0.4):
    """随机延迟，防止快捷键操作过快导致丢失"""
    time.sleep(random.uniform(min_sec, max_sec))


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
    
    def _ensure_wechat_ready(self) -> bool:
        """
        确保微信窗口就绪
        
        Returns:
            True 如果成功，False 如果失败
        """
        if self.dry_run:
            log.info("[DRY_RUN] 跳过微信窗口检查")
            return True
        
        windows = self._get_windows()
        desktop = self._get_desktop()
        
        try:
            # 尝试聚焦已有窗口
            windows.control_window(f"regex:{self.window_title_regex}")
            log.info("微信窗口已聚焦")
            time.sleep(0.3)  # 等待窗口响应
            return True
        except Exception as e:
            log.warn(f"未找到微信窗口，尝试启动", error=str(e))
        
        try:
            # 启动微信
            desktop.open_application(self.exe_path)
            log.info("已启动微信，等待窗口出现...")
            
            # 等待窗口出现（最多 30 秒）
            for _ in range(30):
                time.sleep(1)
                try:
                    windows.control_window(f"regex:{self.window_title_regex}")
                    log.info("微信窗口已就绪")
                    time.sleep(0.5)
                    return True
                except Exception:
                    pass
            
            log.error("等待微信窗口超时")
            self._take_screenshot("startup_timeout")
            return False
            
        except Exception as e:
            log.error(f"启动微信失败", error=str(e))
            self._take_screenshot("startup_failed")
            return False
    
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
        
        windows = self._get_windows()
        
        for attempt in range(retry_count):
            try:
                windows.control_window(f"regex:{self.window_title_regex}")
                _safe_sleep(0.2, 0.3)  # 等待窗口响应
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
    def _send_to_group(self, group_name: str, text: str):
        """
        发送消息到指定群
        
        Args:
            group_name: 群名称
            text: 消息文本
            
        Raises:
            RuntimeError: 窗口聚焦失败时
        """
        if self.dry_run:
            log.info(f"[DRY_RUN] 将发送到群",
                     group=group_name,
                     text_len=len(text),
                     text_preview=text[:50] + "..." if len(text) > 50 else text)
            return
        
        desktop = self._get_desktop()
        
        # 1. 确保窗口聚焦（关键步骤，失败则抛出异常触发重试）
        if not self._focus_window():
            raise RuntimeError(f"无法聚焦微信窗口，无法发送到群: {group_name}")
        
        # 2. Ctrl+F 打开搜索
        log.debug("打开搜索框")
        desktop.press_keys("ctrl", "f")
        _safe_sleep(0.3, 0.5)  # 等待搜索框出现
        
        # 3. 清空搜索框并输入群名
        desktop.press_keys("ctrl", "a")
        _safe_sleep(0.1, 0.2)
        
        # 使用剪贴板输入群名（避免中文输入法问题）
        pyperclip.copy(group_name)
        _safe_sleep(0.1, 0.15)
        desktop.press_keys("ctrl", "v")
        _safe_sleep(0.8, 1.0)  # 等待搜索结果出现（需要更长时间）
        
        # 4. 按 Down 键选择第一个搜索结果（联系人/群聊）
        log.debug("选择搜索结果")
        desktop.press_keys("down")
        _safe_sleep(0.2, 0.3)
        
        # 5. 按 Enter 进入聊天窗口
        desktop.press_keys("enter")
        _safe_sleep(0.5, 0.7)  # 等待聊天窗口切换
        
        # 6. 按 Esc 确保关闭搜索面板（如果还在的话）
        desktop.press_keys("escape")
        _safe_sleep(0.2, 0.3)
        
        # 7. 再次确保窗口聚焦（防止切换群时焦点丢失）
        self._focus_window(retry_count=1)
        _safe_sleep(0.2, 0.3)
        
        # 8. 输入消息文本
        log.debug("输入消息文本")
        pyperclip.copy(text)
        _safe_sleep(0.1, 0.15)
        desktop.press_keys("ctrl", "v")
        _safe_sleep(0.3, 0.4)  # 等待文本粘贴完成
        
        # 9. 发送消息（Enter）
        desktop.press_keys("enter")
        _safe_sleep(0.3, 0.4)
        
        log.info(f"消息已发送", group=group_name, text_len=len(text))
    
    def _try_recover_window_state(self):
        """
        尝试恢复窗口状态（发送失败后调用）
        - 按 Esc 关闭可能的弹窗/搜索框
        - 重新聚焦窗口
        """
        if self.dry_run:
            return
        
        try:
            desktop = self._get_desktop()
            
            # 按 Esc 关闭可能的弹窗或搜索框
            desktop.press_keys("escape")
            _safe_sleep(0.2, 0.3)
            desktop.press_keys("escape")
            _safe_sleep(0.2, 0.3)
            
            # 尝试重新聚焦
            self._focus_window(retry_count=2)
            
            log.debug("窗口状态恢复完成")
        except Exception as e:
            log.warn(f"恢复窗口状态失败", error=str(e))
    
    def _validate_whitelist(self, groups: List[str]):
        """校验群是否在白名单中"""
        invalid_groups = [g for g in groups if g not in self.allowed_groups]
        if invalid_groups:
            raise WhitelistError(f"以下群不在白名单中: {invalid_groups}")
    
    def broadcast(self, groups: List[str], text: str) -> dict:
        """
        广播消息到多个群
        
        Args:
            groups: 目标群列表
            text: 消息文本
            
        Returns:
            执行结果统计 {"sent": N, "skipped": N, "failed": N}
        """
        log.info("=" * 50)
        log.info("开始广播任务",
                 groups=len(groups),
                 text_len=len(text),
                 armed=self.armed,
                 dry_run=self.dry_run)
        
        # 1. 白名单校验
        self._validate_whitelist(groups)
        log.info("白名单校验通过")
        
        # 2. 安全保险丝检查
        if not self.dry_run and not self.armed:
            raise SafetyError(
                "安全保险丝未解除！设置 armed=true 以启用真实发送。"
                "当前配置: dry_run=false, armed=false"
            )
        
        # 3. 确保微信就绪
        if not self._ensure_wechat_ready():
            raise RuntimeError("微信窗口未就绪，无法执行广播")
        
        # 4. 执行广播
        stats = {"sent": 0, "skipped": 0, "failed": 0}
        rate_limiter = get_rate_limiter()
        
        for i, group in enumerate(groups, 1):
            log.info(f"处理群 {i}/{len(groups)}", group=group)
            
            # 4.1 去重检查
            if not should_send(group, text):
                stats["skipped"] += 1
                continue
            
            # 4.2 限频等待
            waited = rate_limiter.acquire()
            if waited > 0:
                log.info(f"限频等待完成", waited=f"{waited:.2f}s")
            
            # 4.3 发送（带重试）
            try:
                self._send_to_group(group, text)
                
                # 4.4 标记已发送
                mark_sent(group, text)
                stats["sent"] += 1
                
            except Exception as e:
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
