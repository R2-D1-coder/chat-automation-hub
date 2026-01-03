"""限频模块 - 滑动窗口"""
import time
from collections import deque
from threading import Lock

from src.core.log import log


class RateLimiter:
    """滑动窗口限频器"""
    
    def __init__(self, max_per_minute: int = 10):
        """
        Args:
            max_per_minute: 每分钟最大请求数
        """
        self.max_per_minute = max_per_minute
        self.window_size = 60.0  # 60 秒窗口
        self.timestamps: deque = deque()
        self._lock = Lock()
    
    def _cleanup_old(self, now: float):
        """清理窗口外的旧时间戳"""
        cutoff = now - self.window_size
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()
    
    def acquire(self) -> float:
        """
        获取一个请求配额，必要时阻塞等待
        
        Returns:
            实际等待的秒数
        """
        with self._lock:
            now = time.time()
            self._cleanup_old(now)
            
            waited = 0.0
            
            # 如果已达上限，等待直到最早的请求过期
            while len(self.timestamps) >= self.max_per_minute:
                oldest = self.timestamps[0]
                wait_time = (oldest + self.window_size) - time.time() + 0.01
                if wait_time > 0:
                    log.info(f"限频等待", wait=f"{wait_time:.2f}s", current=len(self.timestamps), max=self.max_per_minute)
                    time.sleep(wait_time)
                    waited += wait_time
                now = time.time()
                self._cleanup_old(now)
            
            self.timestamps.append(time.time())
            return waited
    
    def current_count(self) -> int:
        """当前窗口内的请求数"""
        with self._lock:
            self._cleanup_old(time.time())
            return len(self.timestamps)


# 全局限频器实例（可在初始化时重新配置）
_rate_limiter: RateLimiter = None


def get_rate_limiter(max_per_minute: int = 10) -> RateLimiter:
    """获取或创建全局限频器"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(max_per_minute)
    return _rate_limiter


def reset_rate_limiter(max_per_minute: int = 10):
    """重置全局限频器"""
    global _rate_limiter
    _rate_limiter = RateLimiter(max_per_minute)
