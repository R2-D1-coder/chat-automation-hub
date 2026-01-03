"""SQLite 存储模块"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core.log import log

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"


class SQLiteStore:
    """SQLite 持久化存储"""
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Args:
            db_path: 数据库文件路径，默认 output/state.db
        """
        if db_path is None:
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            db_path = OUTPUT_DIR / "state.db"
        
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（懒加载）"""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        return self._conn
    
    def close(self):
        """关闭数据库连接"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
    
    def _init_db(self):
        """初始化数据库表"""
        conn = self._get_conn()
        # 旧表（基于内容去重，已废弃）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_log (
                key TEXT PRIMARY KEY,
                ts TEXT NOT NULL
            )
        """)
        # 新表：基于群名+时间间隔去重
        conn.execute("""
            CREATE TABLE IF NOT EXISTS group_last_sent (
                group_name TEXT PRIMARY KEY,
                last_sent_time TEXT NOT NULL
            )
        """)
        conn.commit()
        log.debug(f"数据库初始化完成", path=str(self.db_path))
    
    def has_key(self, key: str) -> bool:
        """检查 key 是否已存在"""
        conn = self._get_conn()
        cursor = conn.execute("SELECT 1 FROM sent_log WHERE key = ?", (key,))
        return cursor.fetchone() is not None
    
    def set_key(self, key: str) -> bool:
        """
        记录一个 key（带时间戳）
        
        Returns:
            True 如果成功插入，False 如果已存在
        """
        ts = datetime.now().isoformat()
        try:
            conn = self._get_conn()
            conn.execute("INSERT INTO sent_log (key, ts) VALUES (?, ?)", (key, ts))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # key 已存在
    
    def get_ts(self, key: str) -> Optional[str]:
        """获取 key 的时间戳"""
        conn = self._get_conn()
        cursor = conn.execute("SELECT ts FROM sent_log WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None
    
    def count(self) -> int:
        """获取记录总数"""
        conn = self._get_conn()
        cursor = conn.execute("SELECT COUNT(*) FROM sent_log")
        return cursor.fetchone()[0]
    
    def clear(self):
        """清空所有记录（慎用）"""
        conn = self._get_conn()
        conn.execute("DELETE FROM sent_log")
        conn.commit()
    
    # ========== 基于时间间隔的去重 ==========
    
    def get_last_sent_time(self, group_name: str) -> Optional[str]:
        """
        获取群的最后发送时间
        
        Args:
            group_name: 群名
            
        Returns:
            ISO 格式时间字符串，或 None（从未发送）
        """
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT last_sent_time FROM group_last_sent WHERE group_name = ?",
            (group_name,)
        )
        row = cursor.fetchone()
        return row[0] if row else None
    
    def set_last_sent_time(self, group_name: str):
        """
        记录群的最后发送时间（当前时间）
        
        Args:
            group_name: 群名
        """
        ts = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO group_last_sent (group_name, last_sent_time)
            VALUES (?, ?)
        """, (group_name, ts))
        conn.commit()
    
    def get_all_group_times(self) -> dict:
        """获取所有群的最后发送时间"""
        conn = self._get_conn()
        cursor = conn.execute("SELECT group_name, last_sent_time FROM group_last_sent")
        return {row[0]: row[1] for row in cursor.fetchall()}
    
    def clear_group_times(self):
        """清空群发送时间记录"""
        conn = self._get_conn()
        conn.execute("DELETE FROM group_last_sent")
        conn.commit()


# 全局存储实例
_store: SQLiteStore = None


def get_store() -> SQLiteStore:
    """获取全局存储实例"""
    global _store
    if _store is None:
        _store = SQLiteStore()
    return _store
