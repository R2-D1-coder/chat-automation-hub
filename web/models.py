"""数据模型 - 任务配置和执行日志"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, asdict

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 任务配置文件路径（可以通过 Git 同步）
TASKS_JSON_PATH = PROJECT_ROOT / "tasks.json"

# 数据库路径（用于执行日志，不通过 Git 同步）
DB_PATH = PROJECT_ROOT / "output" / "scheduler.db"


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
    random_delay_minutes: Optional[int] = None  # 随机延时（分钟），None 表示使用配置文件的默认值
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
                    random_delay_minutes INTEGER DEFAULT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # 添加新列（如果不存在）
            try:
                conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN random_delay_minutes INTEGER DEFAULT NULL")
                conn.commit()
            except sqlite3.OperationalError:
                # 列已存在，忽略错误
                pass
            
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
    
    # ========== JSON 文件同步 ==========
    
    def _save_tasks_to_json(self):
        """保存所有任务到 JSON 文件"""
        try:
            tasks = self.get_all_tasks()
            # 转换为字典列表，移除 id（JSON 中不需要，数据库会自动生成）
            tasks_data = []
            for task in tasks:
                task_dict = {
                    "name": task.name,
                    "groups": task.get_groups_list(),  # 转换为列表
                    "text": task.text,
                    "image_path": task.image_path,
                    "cron_expression": task.cron_expression,
                    "enabled": task.enabled,
                    "random_delay_minutes": task.random_delay_minutes,
                }
                tasks_data.append(task_dict)
            
            # 保存到 JSON 文件
            with open(TASKS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump({"tasks": tasks_data}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # JSON 保存失败不应该影响数据库操作
            print(f"[警告] 保存任务到 JSON 文件失败: {e}")
    
    def _load_tasks_from_json(self) -> List[dict]:
        """从 JSON 文件加载任务配置"""
        if not TASKS_JSON_PATH.exists():
            return []
        
        try:
            with open(TASKS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("tasks", [])
        except Exception as e:
            print(f"[警告] 从 JSON 文件加载任务失败: {e}")
            return []
    
    def sync_from_json(self):
        """从 JSON 文件同步任务到数据库（启动时调用）"""
        json_tasks = self._load_tasks_from_json()
        if not json_tasks:
            return
        
        db_tasks = self.get_all_tasks()
        # 创建任务名称到任务的映射
        db_tasks_by_name = {task.name: task for task in db_tasks}
        
        # 同步 JSON 中的任务到数据库
        for json_task in json_tasks:
            task_name = json_task.get("name", "")
            if not task_name:
                continue
            
            # 创建任务对象
            task = ScheduledTask(
                name=task_name,
                text=json_task.get("text", ""),
                image_path=json_task.get("image_path", ""),
                cron_expression=json_task.get("cron_expression", ""),
                enabled=json_task.get("enabled", True),
                random_delay_minutes=json_task.get("random_delay_minutes"),
            )
            task.set_groups_list(json_task.get("groups", []))
            
            # 如果数据库中存在同名任务，更新它；否则创建新任务
            if task_name in db_tasks_by_name:
                # 更新现有任务
                existing_task = db_tasks_by_name[task_name]
                task.id = existing_task.id
                task.created_at = existing_task.created_at
                # 只更新数据库，不更新 JSON（避免循环）
                task.updated_at = datetime.now().isoformat()
                with self._get_conn() as conn:
                    conn.execute("""
                        UPDATE scheduled_tasks 
                        SET groups=?, text=?, image_path=?, cron_expression=?, enabled=?, random_delay_minutes=?, updated_at=?
                        WHERE id=?
                    """, (task.groups, task.text, task.image_path,
                          task.cron_expression, int(task.enabled), task.random_delay_minutes, task.updated_at, task.id))
                    conn.commit()
            else:
                # 创建新任务
                now = datetime.now().isoformat()
                task.created_at = now
                task.updated_at = now
                with self._get_conn() as conn:
                    cursor = conn.execute("""
                        INSERT INTO scheduled_tasks 
                        (name, groups, text, image_path, cron_expression, enabled, random_delay_minutes, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (task.name, task.groups, task.text, task.image_path, 
                          task.cron_expression, int(task.enabled), task.random_delay_minutes, task.created_at, task.updated_at))
                    conn.commit()
        
        # 删除 JSON 中不存在但数据库存在的任务（可选，这里不自动删除，保留手动创建的任务）
    
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
                (name, groups, text, image_path, cron_expression, enabled, random_delay_minutes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (task.name, task.groups, task.text, task.image_path, 
                  task.cron_expression, int(task.enabled), task.random_delay_minutes, task.created_at, task.updated_at))
            conn.commit()
            task.id = cursor.lastrowid
        
        # 同步更新 JSON 文件
        self._save_tasks_to_json()
        return task.id
    
    def update_task(self, task: ScheduledTask):
        """更新任务"""
        task.updated_at = datetime.now().isoformat()
        
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE scheduled_tasks 
                SET name=?, groups=?, text=?, image_path=?, cron_expression=?, enabled=?, random_delay_minutes=?, updated_at=?
                WHERE id=?
            """, (task.name, task.groups, task.text, task.image_path,
                  task.cron_expression, int(task.enabled), task.random_delay_minutes, task.updated_at, task.id))
            conn.commit()
        
        # 同步更新 JSON 文件
        self._save_tasks_to_json()
    
    def delete_task(self, task_id: int):
        """删除任务"""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
            conn.commit()
        
        # 同步更新 JSON 文件
        self._save_tasks_to_json()
    
    def toggle_task(self, task_id: int, enabled: bool):
        """启用/禁用任务"""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE scheduled_tasks SET enabled=?, updated_at=? WHERE id=?",
                (int(enabled), datetime.now().isoformat(), task_id)
            )
            conn.commit()
        
        # 同步更新 JSON 文件
        self._save_tasks_to_json()
    
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

