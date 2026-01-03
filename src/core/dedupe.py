"""消息去重模块 - 基于时间间隔"""
from datetime import datetime, timedelta
from typing import Optional

from src.core.log import log
from src.core.storage import get_store

# 默认最小发送间隔（秒）
DEFAULT_MIN_INTERVAL_SEC = 60  # 1 分钟


def should_send(group: str, min_interval_sec: int = DEFAULT_MIN_INTERVAL_SEC) -> bool:
    """
    检查是否应该发送（基于时间间隔）
    
    Args:
        group: 群名
        min_interval_sec: 最小发送间隔（秒），默认 60 秒
        
    Returns:
        True 如果应该发送，False 如果在间隔时间内
    """
    store = get_store()
    last_sent = store.get_last_sent_time(group)
    
    if last_sent is None:
        # 从未发送过
        return True
    
    try:
        last_dt = datetime.fromisoformat(last_sent)
        elapsed = (datetime.now() - last_dt).total_seconds()
        
        if elapsed < min_interval_sec:
            log.info(f"跳过（间隔 {elapsed:.0f}s < {min_interval_sec}s）", 
                     group=group, last_sent=last_sent)
            return False
        
        return True
        
    except Exception as e:
        log.warn(f"解析时间失败，允许发送", error=str(e))
        return True


def mark_sent(group: str):
    """标记群已发送（记录当前时间）"""
    store = get_store()
    store.set_last_sent_time(group)
    log.debug(f"标记已发送", group=group, time=datetime.now().isoformat())


# ========== 兼容旧接口（废弃） ==========

def compute_key(group: str, text: str) -> str:
    """废弃：基于内容的去重 key"""
    import hashlib
    content = f"{group}\n{text}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
