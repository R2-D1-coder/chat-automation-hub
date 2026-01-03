"""数据模型 - 任务配置和执行日志"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, asdict

# 数据库路径
DB_PATH = Path(__file__).parent.parent / "output" / "scheduler.db"


@dataclass
class ScheduledTask:
    """定时任务配置"""
    id: Optional[int] = None
    name: str = ""
    groups: str = "[]"  # JSON 数组
    text: str = ""
    image_path: str = ""
    cron_expression: str = ""  # Cron 表达式
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""
    
    def get_groups_list(self) -> List[str]:
        """获取群组列表"""
        try:
            return json.loads(self.groups)
        except:
            return []
    
    def set_groups_list(self, groups: List[str]):
        """设置群组列表"""
        self.groups = json.dumps(groups, ensure_ascii=False)


@dataclass
class ExecutionLog:
    """执行日志"""
    id: Optional[int] = None
    task_id: int = 0
    task_name: str = ""
    status: str = ""  # success, failed, skipped
    message: str = ""
    executed_at: str = ""


class Database:
    """数据库操作类"""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        """初始化数据库表"""
        with self._get_conn() as conn:
            # 任务表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    groups TEXT NOT NULL DEFAULT '[]',
                    text TEXT NOT NULL DEFAULT '',
                    image_path TEXT DEFAULT '',
                    cron_expression TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # 执行日志表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    task_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT DEFAULT '',
                    executed_at TEXT NOT NULL
                )
            """)
            conn.commit()
    
    # ========== 任务操作 ==========
    
    def get_all_tasks(self) -> List[ScheduledTask]:
        """获取所有任务"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks ORDER BY id DESC"
            ).fetchall()
            return [ScheduledTask(**dict(row)) for row in rows]
    
    def get_task(self, task_id: int) -> Optional[ScheduledTask]:
        """获取单个任务"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
            ).fetchone()
            return ScheduledTask(**dict(row)) if row else None
    
    def get_enabled_tasks(self) -> List[ScheduledTask]:
        """获取所有启用的任务"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE enabled = 1"
            ).fetchall()
            return [ScheduledTask(**dict(row)) for row in rows]
    
    def create_task(self, task: ScheduledTask) -> int:
        """创建任务"""
        now = datetime.now().isoformat()
        task.created_at = now
        task.updated_at = now
        
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT INTO scheduled_tasks 
                (name, groups, text, image_path, cron_expression, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (task.name, task.groups, task.text, task.image_path, 
                  task.cron_expression, int(task.enabled), task.created_at, task.updated_at))
            conn.commit()
            return cursor.lastrowid
    
    def update_task(self, task: ScheduledTask):
        """更新任务"""
        task.updated_at = datetime.now().isoformat()
        
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE scheduled_tasks 
                SET name=?, groups=?, text=?, image_path=?, cron_expression=?, enabled=?, updated_at=?
                WHERE id=?
            """, (task.name, task.groups, task.text, task.image_path,
                  task.cron_expression, int(task.enabled), task.updated_at, task.id))
            conn.commit()
    
    def delete_task(self, task_id: int):
        """删除任务"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
            conn.commit()
    
    def toggle_task(self, task_id: int, enabled: bool):
        """启用/禁用任务"""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET enabled=?, updated_at=? WHERE id=?",
                (int(enabled), datetime.now().isoformat(), task_id)
            )
            conn.commit()
    
    # ========== 日志操作 ==========
    
    def add_log(self, log: ExecutionLog):
        """添加执行日志"""
        log.executed_at = datetime.now().isoformat()
        
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO execution_logs (task_id, task_name, status, message, executed_at)
                VALUES (?, ?, ?, ?, ?)
            """, (log.task_id, log.task_name, log.status, log.message, log.executed_at))
            conn.commit()
    
    def get_logs(self, limit: int = 50) -> List[ExecutionLog]:
        """获取最近的执行日志"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM execution_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [ExecutionLog(**dict(row)) for row in rows]
    
    def get_task_logs(self, task_id: int, limit: int = 20) -> List[ExecutionLog]:
        """获取指定任务的执行日志"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM execution_logs WHERE task_id = ? ORDER BY id DESC LIMIT ?",
                (task_id, limit)
            ).fetchall()
            return [ExecutionLog(**dict(row)) for row in rows]


# 全局数据库实例
db = Database()

