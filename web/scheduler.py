"""APScheduler 定时调度器"""
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from web.models import db, ScheduledTask, ExecutionLog
from src.core.config import load_config
from src.core.log import Logger

log = Logger("scheduler")

# 全局调度器实例
scheduler: Optional[BackgroundScheduler] = None


def execute_task(task_id: int):
    """执行定时任务"""
    task = db.get_task(task_id)
    if not task:
        log.error("任务不存在", task_id=task_id)
        return
    
    if not task.enabled:
        log.info("任务已禁用，跳过", task_id=task_id, name=task.name)
        return
    
    log.info("=" * 50)
    log.info("开始执行定时任务", task_id=task_id, name=task.name)
    
    exec_log = ExecutionLog(
        task_id=task_id,
        task_name=task.name
    )
    
    try:
        # 导入执行器（延迟导入避免循环依赖）
        from src.adapters.wechat_desktop import WeChatBroadcaster
        
        # 加载基础配置
        config = load_config()
        
        # 获取任务配置
        groups = task.get_groups_list()
        text = task.text.replace("{ts}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        image_path = Path(task.image_path) if task.image_path else None
        
        if image_path and not image_path.is_absolute():
            image_path = PROJECT_ROOT / image_path
        
        if image_path and not image_path.exists():
            log.warn("图片文件不存在", path=str(image_path))
            image_path = None
        
        # 执行广播
        broadcaster = WeChatBroadcaster(config)
        stats = broadcaster.broadcast(groups, text, image_path)
        
        # 记录成功日志
        exec_log.status = "success"
        exec_log.message = f"sent={stats['sent']}, skipped={stats['skipped']}, failed={stats['failed']}"
        log.info("任务执行成功", **stats)
        
    except Exception as e:
        # 记录失败日志
        exec_log.status = "failed"
        exec_log.message = str(e)
        log.error("任务执行失败", error=str(e))
    
    finally:
        db.add_log(exec_log)
        log.info("=" * 50)


def parse_cron_expression(expr: str) -> dict:
    """
    解析 Cron 表达式
    
    支持的格式：
    - 标准 5 段：分 时 日 月 周 (如 "0 20 * * *" 表示每天 20:00)
    - 简化格式：
      - "daily 20:00" -> 每天 20:00
      - "weekly 6 12:00" -> 每周六 12:00 (周日=0, 周一=1, ..., 周六=6)
      - "monthly 1 09:00" -> 每月 1 日 09:00
    """
    expr = expr.strip().lower()
    
    # 简化格式解析
    if expr.startswith("daily "):
        time_part = expr[6:]
        hour, minute = time_part.split(":")
        return {"hour": int(hour), "minute": int(minute)}
    
    elif expr.startswith("weekly "):
        parts = expr[7:].split()
        day_of_week = int(parts[0])
        hour, minute = parts[1].split(":")
        return {"day_of_week": day_of_week, "hour": int(hour), "minute": int(minute)}
    
    elif expr.startswith("monthly "):
        parts = expr[8:].split()
        day = int(parts[0])
        hour, minute = parts[1].split(":")
        return {"day": day, "hour": int(hour), "minute": int(minute)}
    
    # 标准 Cron 格式 (5 段)
    else:
        parts = expr.split()
        if len(parts) == 5:
            return {
                "minute": parts[0],
                "hour": parts[1],
                "day": parts[2],
                "month": parts[3],
                "day_of_week": parts[4]
            }
        else:
            raise ValueError(f"无效的 Cron 表达式: {expr}")


def add_job_for_task(task: ScheduledTask):
    """为任务添加调度作业"""
    global scheduler
    if not scheduler:
        return
    
    job_id = f"task_{task.id}"
    
    # 先移除旧的作业（如果存在）
    try:
        scheduler.remove_job(job_id)
    except:
        pass
    
    if not task.enabled:
        log.debug("任务已禁用，不添加调度", task_id=task.id)
        return
    
    try:
        cron_args = parse_cron_expression(task.cron_expression)
        trigger = CronTrigger(**cron_args)
        
        scheduler.add_job(
            execute_task,
            trigger,
            args=[task.id],
            id=job_id,
            name=task.name,
            replace_existing=True
        )
        
        log.info("已添加调度作业", task_id=task.id, name=task.name, cron=task.cron_expression)
        
    except Exception as e:
        log.error("添加调度作业失败", task_id=task.id, error=str(e))


def remove_job_for_task(task_id: int):
    """移除任务的调度作业"""
    global scheduler
    if not scheduler:
        return
    
    job_id = f"task_{task_id}"
    try:
        scheduler.remove_job(job_id)
        log.info("已移除调度作业", task_id=task_id)
    except:
        pass


def reload_all_jobs():
    """重新加载所有任务的调度作业"""
    global scheduler
    if not scheduler:
        return
    
    # 清除所有任务作业
    for job in scheduler.get_jobs():
        if job.id.startswith("task_"):
            scheduler.remove_job(job.id)
    
    # 重新加载启用的任务
    tasks = db.get_enabled_tasks()
    for task in tasks:
        add_job_for_task(task)
    
    log.info(f"已重新加载 {len(tasks)} 个调度作业")


def init_scheduler() -> BackgroundScheduler:
    """初始化调度器"""
    global scheduler
    
    if scheduler is not None:
        return scheduler
    
    scheduler = BackgroundScheduler(
        timezone="Asia/Shanghai",
        job_defaults={
            'coalesce': True,  # 合并错过的任务
            'max_instances': 1  # 同一任务最多同时运行 1 个实例
        }
    )
    
    # 加载所有启用的任务
    reload_all_jobs()
    
    return scheduler


def start_scheduler():
    """启动调度器"""
    global scheduler
    if scheduler is None:
        init_scheduler()
    
    if not scheduler.running:
        scheduler.start()
        log.info("调度器已启动")


def stop_scheduler():
    """停止调度器"""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("调度器已停止")


def get_scheduler_status() -> dict:
    """获取调度器状态"""
    global scheduler
    if scheduler is None:
        return {"running": False, "jobs": 0}
    
    jobs = scheduler.get_jobs()
    return {
        "running": scheduler.running,
        "jobs": len([j for j in jobs if j.id.startswith("task_")]),
        "next_run": min([j.next_run_time for j in jobs if j.next_run_time], default=None)
    }

