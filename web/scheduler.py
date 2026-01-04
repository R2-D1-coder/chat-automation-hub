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


def execute_task(task_id: int, immediate: bool = False):
    """
    执行定时任务
    
    Args:
        task_id: 任务ID
        immediate: 是否立即执行（跳过队列，用于手动测试）
    """
    task = db.get_task(task_id)
    if not task:
        log.error("任务不存在", task_id=task_id)
        return
    
    # 定时触发时检查是否启用，手动立即执行不检查
    if not immediate and not task.enabled:
        log.info("任务已禁用，跳过", task_id=task_id, name=task.name)
        return
    
    log.info("=" * 50)
    mode = "【立即执行】" if immediate else "【定时任务】"
    log.info(f"{mode} 开始执行", task_id=task_id, name=task.name)
    
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
        stats = broadcaster.broadcast(groups, text, image_path, task_name=task.name, immediate=immediate)
        
        # 记录日志
        exec_log.status = "success"
        if immediate:
            exec_log.message = f"sent={stats['sent']}, failed={stats['failed']}"
            log.info("立即执行完成", **stats)
        else:
            exec_log.message = f"scheduled={stats['scheduled']}, skipped={stats['skipped']}"
            log.info("任务调度成功", **stats)
        
    except Exception as e:
        # 记录失败日志
        exec_log.status = "failed"
        exec_log.message = str(e)
        log.error("任务执行失败", error=str(e))
    
    finally:
        db.add_log(exec_log)
        log.info("=" * 50)


def parse_cron_expression(expr: str) -> tuple:
    """
    解析调度表达式
    
    支持的格式：
    - 间隔格式：
      - "every 5m" -> 每 5 分钟
      - "every 1h" -> 每 1 小时
      - "every 30s" -> 每 30 秒
    - 标准 5 段：分 时 日 月 周 (如 "0 20 * * *" 表示每天 20:00)
    - 简化格式：
      - "daily 20:00" -> 每天 20:00
      - "weekly 6 12:00" -> 每周六 12:00 (周日=0, 周一=1, ..., 周六=6)
      - "monthly 1 09:00" -> 每月 1 日 09:00
    
    Returns:
        tuple: (trigger_type, trigger_args)
        - trigger_type: "cron" 或 "interval"
        - trigger_args: 传给触发器的参数字典
    """
    expr = expr.strip().lower()
    
    # 间隔格式解析 (every Nm/Nh/Ns)
    if expr.startswith("every "):
        interval_part = expr[6:].strip()
        
        if interval_part.endswith("m"):
            minutes = int(interval_part[:-1])
            return ("interval", {"minutes": minutes})
        elif interval_part.endswith("h"):
            hours = int(interval_part[:-1])
            return ("interval", {"hours": hours})
        elif interval_part.endswith("s"):
            seconds = int(interval_part[:-1])
            return ("interval", {"seconds": seconds})
        else:
            raise ValueError(f"无效的间隔格式: {expr}，支持 s/m/h 后缀")
    
    # 简化格式解析
    if expr.startswith("daily "):
        time_part = expr[6:]
        hour, minute = time_part.split(":")
        return ("cron", {"hour": int(hour), "minute": int(minute)})
    
    elif expr.startswith("weekly "):
        parts = expr[7:].split()
        day_of_week = int(parts[0])
        hour, minute = parts[1].split(":")
        return ("cron", {"day_of_week": day_of_week, "hour": int(hour), "minute": int(minute)})
    
    elif expr.startswith("monthly "):
        parts = expr[8:].split()
        day = int(parts[0])
        hour, minute = parts[1].split(":")
        return ("cron", {"day": day, "hour": int(hour), "minute": int(minute)})
    
    # 标准 Cron 格式 (5 段)
    else:
        parts = expr.split()
        if len(parts) == 5:
            return ("cron", {
                "minute": parts[0],
                "hour": parts[1],
                "day": parts[2],
                "month": parts[3],
                "day_of_week": parts[4]
            })
        else:
            raise ValueError(f"无效的调度表达式: {expr}")


def add_job_for_task(task: ScheduledTask, run_immediately: bool = False):
    """
    为任务添加调度作业
    
    Args:
        task: 任务对象
        run_immediately: 是否立即执行一次（对于 interval 类型任务）
    """
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
        trigger_type, trigger_args = parse_cron_expression(task.cron_expression)
        
        # 根据类型创建触发器
        if trigger_type == "interval":
            from apscheduler.triggers.interval import IntervalTrigger
            trigger = IntervalTrigger(**trigger_args)
        else:
            trigger = CronTrigger(**trigger_args)
        
        scheduler.add_job(
            execute_task,
            trigger,
            args=[task.id],
            id=job_id,
            name=task.name,
            replace_existing=True
        )
        
        log.info("已添加调度作业", task_id=task.id, name=task.name, cron=task.cron_expression)
        
        # 对于 interval 类型，立即执行第一次
        if run_immediately and trigger_type == "interval":
            import threading
            log.info("立即执行首次任务", task_id=task.id)
            threading.Thread(target=execute_task, args=(task.id,), daemon=True).start()
        
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
    
    # 获取下次运行时间（兼容不同版本的 APScheduler）
    next_run = None
    try:
        next_runs = []
        for j in jobs:
            # 尝试不同的属性名
            nrt = getattr(j, 'next_run_time', None) or getattr(j, 'next_fire_time', None)
            if nrt:
                next_runs.append(nrt)
        if next_runs:
            next_run = min(next_runs)
    except Exception:
        pass
    
    return {
        "running": scheduler.running,
        "jobs": len([j for j in jobs if j.id.startswith("task_")]),
        "next_run": next_run
    }

