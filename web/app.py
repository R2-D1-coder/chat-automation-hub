"""Flask Web 管理应用"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from web.models import db, ScheduledTask, ExecutionLog
from web.scheduler import (
    init_scheduler, start_scheduler, stop_scheduler,
    get_scheduler_status, add_job_for_task, remove_job_for_task,
    execute_task, reload_all_jobs
)
from src.core.config import load_config

# 创建 Flask 应用
app = Flask(__name__)
app.secret_key = os.urandom(24)

# 上传文件夹
UPLOAD_FOLDER = PROJECT_ROOT / "assets" / "uploads"
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


def get_allowed_groups():
    """获取白名单群组列表"""
    try:
        config = load_config()
        return config.get("allowed_groups", [])
    except:
        return []


# ========== 页面路由 ==========

@app.route("/")
def index():
    """首页 - 任务列表"""
    tasks = db.get_all_tasks()
    logs = db.get_logs(limit=10)
    status = get_scheduler_status()
    allowed_groups = get_allowed_groups()
    immediate_run_enabled = session.get("immediate_run_enabled", False)
    
    return render_template("index.html", 
                           tasks=tasks, 
                           logs=logs, 
                           status=status,
                           allowed_groups=allowed_groups,
                           immediate_run_enabled=immediate_run_enabled)


@app.route("/task/new", methods=["GET", "POST"])
def new_task():
    """新建任务"""
    allowed_groups = get_allowed_groups()
    status = get_scheduler_status()
    
    if request.method == "POST":
        # 处理随机延时（空字符串或 None 表示使用默认值）
        random_delay_str = request.form.get("random_delay_minutes", "").strip()
        random_delay_minutes = int(random_delay_str) if random_delay_str else None
        
        task = ScheduledTask(
            name=request.form.get("name", "").strip(),
            text=request.form.get("text", ""),
            image_path=request.form.get("image_path", ""),
            cron_expression=request.form.get("cron_expression", "").strip(),
            enabled=request.form.get("enabled") == "on",
            random_delay_minutes=random_delay_minutes
        )
        
        # 处理群组选择
        selected_groups = request.form.getlist("groups")
        task.set_groups_list(selected_groups)
        
        # 处理图片上传
        if "image_file" in request.files:
            file = request.files["image_file"]
            if file and file.filename:
                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
                filepath = UPLOAD_FOLDER / filename
                file.save(str(filepath))
                task.image_path = f"assets/uploads/{filename}"
        
        if not task.name:
            flash("任务名称不能为空", "error")
            return render_template("task_form.html", task=task, allowed_groups=allowed_groups, is_new=True, status=status)
        
        if not task.cron_expression:
            flash("调度规则不能为空", "error")
            return render_template("task_form.html", task=task, allowed_groups=allowed_groups, is_new=True, status=status)
        
        task_id = db.create_task(task)
        task.id = task_id
        add_job_for_task(task, run_immediately=True)  # 创建后立即执行一次
        
        flash(f"任务 '{task.name}' 创建成功", "success")
        return redirect(url_for("index"))
    
    return render_template("task_form.html", task=ScheduledTask(), allowed_groups=allowed_groups, is_new=True, status=status)


@app.route("/task/<int:task_id>/edit", methods=["GET", "POST"])
def edit_task(task_id: int):
    """编辑任务"""
    task = db.get_task(task_id)
    if not task:
        flash("任务不存在", "error")
        return redirect(url_for("index"))
    
    allowed_groups = get_allowed_groups()
    status = get_scheduler_status()
    
    if request.method == "POST":
        task.name = request.form.get("name", "").strip()
        task.text = request.form.get("text", "")
        task.cron_expression = request.form.get("cron_expression", "").strip()
        task.enabled = request.form.get("enabled") == "on"
        
        # 处理随机延时（空字符串或 None 表示使用默认值）
        random_delay_str = request.form.get("random_delay_minutes", "").strip()
        task.random_delay_minutes = int(random_delay_str) if random_delay_str else None
        
        # 处理群组选择
        selected_groups = request.form.getlist("groups")
        task.set_groups_list(selected_groups)
        
        # 处理图片上传
        if "image_file" in request.files:
            file = request.files["image_file"]
            if file and file.filename:
                filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
                filepath = UPLOAD_FOLDER / filename
                file.save(str(filepath))
                task.image_path = f"assets/uploads/{filename}"
        
        # 如果选择清除图片
        if request.form.get("clear_image") == "on":
            task.image_path = ""
        
        if not task.name:
            flash("任务名称不能为空", "error")
            return render_template("task_form.html", task=task, allowed_groups=allowed_groups, is_new=False, status=status)
        
        db.update_task(task)
        add_job_for_task(task, run_immediately=True)  # 保存后立即执行一次
        
        flash(f"任务 '{task.name}' 更新成功", "success")
        return redirect(url_for("index"))
    
    return render_template("task_form.html", task=task, allowed_groups=allowed_groups, is_new=False, status=status)


@app.route("/task/<int:task_id>/delete", methods=["POST"])
def delete_task(task_id: int):
    """删除任务"""
    task = db.get_task(task_id)
    if task:
        remove_job_for_task(task_id)
        db.delete_task(task_id)
        flash(f"任务 '{task.name}' 已删除", "success")
    return redirect(url_for("index"))


@app.route("/task/<int:task_id>/toggle", methods=["POST"])
def toggle_task(task_id: int):
    """启用/禁用任务"""
    task = db.get_task(task_id)
    if task:
        new_status = not task.enabled
        db.toggle_task(task_id, new_status)
        task.enabled = new_status
        add_job_for_task(task)
        
        # 禁用任务时，清空该任务在队列中的待发送动作
        if not new_status:
            from src.core.send_queue import get_send_queue
            queue = get_send_queue()
            queue.clear_task(task.name)
        
        status_text = "启用" if new_status else "禁用"
        flash(f"任务 '{task.name}' 已{status_text}", "success")
    return redirect(url_for("index"))


@app.route("/api/verify-password", methods=["POST"])
def api_verify_password():
    """验证立即执行密码"""
    data = request.get_json()
    password = data.get("password", "")
    
    # 默认密码：525611
    if password == "525611":
        session["immediate_run_enabled"] = True
        return jsonify({"success": True, "message": "密码验证成功，立即执行功能已启用"})
    else:
        return jsonify({"success": False, "message": "密码错误"}), 401


@app.route("/task/<int:task_id>/run", methods=["POST"])
def run_task(task_id: int):
    """立即执行任务（跳过队列，直接发送）"""
    # 检查密码验证状态
    if not session.get("immediate_run_enabled", False):
        flash("请先输入密码启用立即执行功能", "error")
        return redirect(url_for("index"))
    
    task = db.get_task(task_id)
    if task:
        # 异步执行（避免阻塞），immediate=True 跳过队列直接发送
        import threading
        thread = threading.Thread(target=execute_task, args=(task_id, True))
        thread.start()
        flash(f"任务 '{task.name}' 正在立即执行（跳过队列）", "info")
    return redirect(url_for("index"))


@app.route("/logs")
def logs():
    """执行日志页面"""
    page_logs = db.get_logs(limit=100)
    status = get_scheduler_status()
    return render_template("logs.html", logs=page_logs, status=status)


# ========== API 路由 ==========

@app.route("/api/status")
def api_status():
    """获取调度器状态"""
    status = get_scheduler_status()
    status["next_run"] = status["next_run"].isoformat() if status["next_run"] else None
    return jsonify(status)


@app.route("/api/scheduler/start", methods=["POST"])
def api_start_scheduler():
    """启动调度器"""
    start_scheduler()
    return jsonify({"success": True, "message": "调度器已启动"})


@app.route("/api/scheduler/stop", methods=["POST"])
def api_stop_scheduler():
    """停止调度器并清空发送队列"""
    stop_scheduler()
    
    # 同时清空发送队列
    from src.core.send_queue import get_send_queue
    queue = get_send_queue()
    queue.clear_all()
    
    return jsonify({"success": True, "message": "调度器已停止，发送队列已清空"})


@app.route("/api/scheduler/reload", methods=["POST"])
def api_reload_scheduler():
    """重新加载所有任务"""
    reload_all_jobs()
    return jsonify({"success": True, "message": "已重新加载所有任务"})


# ========== 发送队列 API ==========

@app.route("/queue")
def queue_page():
    """发送队列页面"""
    status = get_scheduler_status()
    return render_template("queue.html", status=status)


@app.route("/api/queue")
def api_queue():
    """获取发送队列"""
    from src.core.send_queue import get_send_queue
    
    include_completed = request.args.get("include_completed", "false").lower() == "true"
    queue = get_send_queue()
    actions = queue.get_queue(include_completed=include_completed)
    pending_count = queue.get_pending_count()
    
    return jsonify({
        "actions": actions,
        "pending_count": pending_count
    })


@app.route("/api/queue/clear", methods=["POST"])
def api_clear_queue():
    """清空待执行队列"""
    from src.core.send_queue import get_send_queue
    
    queue = get_send_queue()
    queue.clear_all()
    return jsonify({"success": True, "message": "队列已清空"})


@app.route("/api/queue/clear-completed", methods=["POST"])
def api_clear_completed():
    """清理已完成的动作"""
    from src.core.send_queue import get_send_queue
    
    queue = get_send_queue()
    queue.clear_completed()
    return jsonify({"success": True, "message": "已清理完成的动作"})


# ========== 模板过滤器 ==========

@app.template_filter("format_datetime")
def format_datetime(value):
    """格式化日期时间"""
    if not value:
        return ""
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value)
        else:
            dt = value
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return value


@app.template_filter("format_cron")
def format_cron(expr):
    """格式化调度表达式为可读文本"""
    if not expr:
        return ""
    
    expr = expr.strip().lower()
    
    # 间隔格式
    if expr.startswith("every "):
        interval_part = expr[6:].strip()
        if interval_part.endswith("m"):
            return f"每 {interval_part[:-1]} 分钟"
        elif interval_part.endswith("h"):
            return f"每 {interval_part[:-1]} 小时"
        elif interval_part.endswith("s"):
            return f"每 {interval_part[:-1]} 秒"
        return f"每 {interval_part}"
    
    if expr.startswith("daily "):
        return f"每天 {expr[6:]}"
    elif expr.startswith("weekly "):
        parts = expr[7:].split()
        day_names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
        day = int(parts[0])
        return f"每{day_names[day]} {parts[1]}"
    elif expr.startswith("monthly "):
        parts = expr[8:].split()
        return f"每月 {parts[0]} 日 {parts[1]}"
    else:
        return f"Cron: {expr}"


@app.template_filter("to_json")
def to_json_filter(value):
    """转换为 JSON"""
    try:
        return json.loads(value) if isinstance(value, str) else value
    except:
        return []


# ========== 启动入口 ==========

def create_app():
    """创建并配置应用"""
    # 从 JSON 文件同步任务到数据库（启动时）
    try:
        db.sync_from_json()
        print("[初始化] 已从 tasks.json 同步任务配置")
    except Exception as e:
        print(f"[警告] 从 JSON 文件同步任务失败: {e}")
    
    # 初始化调度器
    init_scheduler()
    start_scheduler()
    return app


if __name__ == "__main__":
    app = create_app()
    # 允许远程访问，端口 5000
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

