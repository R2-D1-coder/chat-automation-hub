"""日志模块 - 统一前缀和上下文，同时输出到控制台和文件"""
from datetime import datetime
from pathlib import Path

# 日志文件路径
LOG_DIR = Path(__file__).parent.parent.parent / "output"
LOG_FILE = LOG_DIR / "wechat.log"


class Logger:
    """简单日志器，统一前缀格式，同时输出到控制台和文件"""
    
    def __init__(self, name: str = "app"):
        self.name = name
        # 确保日志目录存在
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    def _format(self, level: str, msg: str, **ctx) -> str:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ctx_str = " ".join(f"{k}={v}" for k, v in ctx.items()) if ctx else ""
        if ctx_str:
            return f"[{ts}][{self.name}][{level}] {msg} | {ctx_str}"
        return f"[{ts}][{self.name}][{level}] {msg}"
    
    def _log(self, level: str, msg: str, **ctx):
        formatted = self._format(level, msg, **ctx)
        # 输出到控制台
        print(formatted)
        # 同时写入文件
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception:
            pass  # 写文件失败不影响主流程
    
    def info(self, msg: str, **ctx):
        self._log("INFO", msg, **ctx)
    
    def warn(self, msg: str, **ctx):
        self._log("WARN", msg, **ctx)
    
    def error(self, msg: str, **ctx):
        self._log("ERROR", msg, **ctx)
    
    def debug(self, msg: str, **ctx):
        self._log("DEBUG", msg, **ctx)


# 全局默认 logger
log = Logger("wechat")
