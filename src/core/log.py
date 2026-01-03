"""日志模块 - 统一前缀和上下文"""
from datetime import datetime


class Logger:
    """简单日志器，统一前缀格式"""
    
    def __init__(self, name: str = "app"):
        self.name = name
    
    def _format(self, level: str, msg: str, **ctx) -> str:
        ts = datetime.now().strftime("%H:%M:%S")
        ctx_str = " ".join(f"{k}={v}" for k, v in ctx.items()) if ctx else ""
        if ctx_str:
            return f"[{ts}][{self.name}][{level}] {msg} | {ctx_str}"
        return f"[{ts}][{self.name}][{level}] {msg}"
    
    def info(self, msg: str, **ctx):
        print(self._format("INFO", msg, **ctx))
    
    def warn(self, msg: str, **ctx):
        print(self._format("WARN", msg, **ctx))
    
    def error(self, msg: str, **ctx):
        print(self._format("ERROR", msg, **ctx))
    
    def debug(self, msg: str, **ctx):
        print(self._format("DEBUG", msg, **ctx))


# 全局默认 logger
log = Logger("wechat")
