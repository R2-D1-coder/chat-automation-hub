"""消息去重模块"""
import hashlib

from src.core.log import log
from src.core.storage import get_store


def compute_key(group: str, text: str) -> str:
    """
    计算去重 key
    
    key = sha256(group + "\\n" + text) 的前 16 位十六进制
    """
    content = f"{group}\n{text}"
    full_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return full_hash[:16]  # 16 位足够区分


def should_send(group: str, text: str) -> bool:
    """
    检查是否应该发送（未发送过）
    
    Returns:
        True 如果应该发送，False 如果已发送过
    """
    key = compute_key(group, text)
    store = get_store()
    
    if store.has_key(key):
        log.info(f"跳过重复消息", group=group, key=key)
        return False
    return True


def mark_sent(group: str, text: str):
    """标记消息已发送"""
    key = compute_key(group, text)
    store = get_store()
    
    if store.set_key(key):
        log.debug(f"标记已发送", group=group, key=key)
    else:
        log.warn(f"重复标记（已存在）", group=group, key=key)
