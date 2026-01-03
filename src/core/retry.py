"""重试模块 - 指数退避 + jitter"""
import random
import time
from functools import wraps
from typing import Callable, Tuple, Type

from src.core.log import log


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: float = 0.5,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """
    指数退避重试装饰器
    
    Args:
        max_attempts: 最大尝试次数
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟（秒）
        exponential_base: 指数基数
        jitter: 抖动因子 (0~1)，随机增减延迟的比例
        exceptions: 需要重试的异常类型
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        log.error(f"重试耗尽", func=func.__name__, attempt=attempt, error=str(e))
                        raise
                    
                    # 计算延迟：base * (exponential_base ^ (attempt-1))
                    delay = base_delay * (exponential_base ** (attempt - 1))
                    delay = min(delay, max_delay)
                    
                    # 添加 jitter
                    jitter_range = delay * jitter
                    delay += random.uniform(-jitter_range, jitter_range)
                    delay = max(0.1, delay)  # 至少 0.1 秒
                    
                    log.warn(f"重试中", func=func.__name__, attempt=attempt, delay=f"{delay:.2f}s", error=str(e))
                    time.sleep(delay)
            
            raise last_exception
        return wrapper
    return decorator
