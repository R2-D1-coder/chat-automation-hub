"""
WeChat Broadcast Automation Tasks
运行方式: python -m robocorp.tasks run tasks.py -t wechat_broadcast
"""
import time
from datetime import datetime
from pathlib import Path

from robocorp.tasks import task

from src.adapters.wechat_desktop import WeChatBroadcaster, SafetyError, WhitelistError
from src.core.config import load_config
from src.core.dedupe import should_send, mark_sent, compute_key
from src.core.log import log
from src.core.ratelimit import RateLimiter
from src.core.retry import retry
from src.core.storage import SQLiteStore


@task
def wechat_broadcast():
    """主任务：微信群发广播"""
    config = load_config()
    
    # 读取广播配置
    broadcast_cfg = config.get("broadcast", {})
    groups = broadcast_cfg.get("groups", [])
    text_template = broadcast_cfg.get("text", "")
    image_rel_path = broadcast_cfg.get("image", None)
    
    # 处理图片路径
    image_path = None
    if image_rel_path:
        image_path = Path(image_rel_path)
        if not image_path.is_absolute():
            image_path = Path(__file__).parent / image_rel_path
        if not image_path.exists():
            print(f"[警告] 图片文件不存在: {image_path}")
            image_path = None
    
    # 渲染文本（替换 {ts} 为当前时间）
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rendered_text = text_template.replace("{ts}", ts)
    
    # 读取安全配置
    safety = config.get("safety", {})
    armed = safety.get("armed", False)
    dry_run = safety.get("dry_run", True)
    
    # 打印配置信息
    print("=" * 60)
    print("[wechat_broadcast] 配置加载完成")
    print("=" * 60)
    print(f"[安全] armed={armed}, dry_run={dry_run}")
    print(f"[目标群组] {groups}")
    print(f"[图片] {image_path if image_path else '无'}")
    print(f"[消息内容] ({len(rendered_text)} 字符)")
    print("-" * 40)
    print(rendered_text)
    print("-" * 40)
    
    # 执行广播
    try:
        broadcaster = WeChatBroadcaster(config)
        stats = broadcaster.broadcast(groups, rendered_text, image_path)
        
        print("\n[结果统计]")
        print(f"  发送成功: {stats['sent']}")
        print(f"  跳过(去重): {stats['skipped']}")
        print(f"  发送失败: {stats['failed']}")
        
    except SafetyError as e:
        print(f"\n[安全保险丝] {e}")
        raise
    except WhitelistError as e:
        print(f"\n[白名单错误] {e}")
        raise
    except Exception as e:
        print(f"\n[执行错误] {e}")
        raise


@task
def self_test_core():
    """自测任务：验证 core 模块功能"""
    print("=" * 60)
    print("[self_test_core] 开始 Core 模块自测")
    print("=" * 60)
    
    # ========== 测试 1: RateLimiter ==========
    print("\n[测试 1] RateLimiter 滑动窗口限频")
    limiter = RateLimiter(max_per_minute=5)
    
    for i in range(7):
        start = time.time()
        waited = limiter.acquire()
        elapsed = time.time() - start
        print(f"  请求 {i+1}: 等待 {waited:.2f}s, 当前窗口计数={limiter.current_count()}")
        if i < 5:
            assert waited < 0.1, f"前 5 次不应等待，但等待了 {waited:.2f}s"
    
    print("  ✓ RateLimiter 测试通过")
    
    # ========== 测试 2: SQLiteStore ==========
    print("\n[测试 2] SQLiteStore 存储")
    test_db = Path("output/test_state.db")
    if test_db.exists():
        test_db.unlink()
    
    store = SQLiteStore(test_db)
    
    # 测试 set/has
    assert not store.has_key("test_key_1"), "新 key 不应存在"
    assert store.set_key("test_key_1"), "首次插入应返回 True"
    assert store.has_key("test_key_1"), "插入后应存在"
    assert not store.set_key("test_key_1"), "重复插入应返回 False"
    
    # 测试 count
    store.set_key("test_key_2")
    assert store.count() == 2, f"应有 2 条记录，实际 {store.count()}"
    
    print(f"  记录数: {store.count()}")
    print("  ✓ SQLiteStore 测试通过")
    
    # 清理测试数据库（先关闭连接）
    store.close()
    test_db.unlink()
    
    # ========== 测试 3: Dedupe 去重 ==========
    print("\n[测试 3] Dedupe 去重逻辑")
    
    # 使用临时数据库
    test_db2 = Path("output/test_dedupe.db")
    if test_db2.exists():
        test_db2.unlink()
    
    # 重新初始化全局 store
    import src.core.storage as storage_mod
    storage_mod._store = SQLiteStore(test_db2)
    
    group = "测试群"
    text = "Hello World"
    
    key = compute_key(group, text)
    print(f"  计算的 key: {key}")
    
    assert should_send(group, text), "首次应该发送"
    mark_sent(group, text)
    assert not should_send(group, text), "标记后不应再发送"
    
    # 不同群/不同文本应该可以发送
    assert should_send("其他群", text), "不同群应该可以发送"
    assert should_send(group, "其他文本"), "不同文本应该可以发送"
    
    print("  ✓ Dedupe 测试通过")
    
    # 清理（先关闭连接）
    storage_mod._store.close()
    storage_mod._store = None
    test_db2.unlink()
    
    # ========== 测试 4: Retry 重试 ==========
    print("\n[测试 4] Retry 指数退避")
    
    call_count = 0
    
    @retry(max_attempts=3, base_delay=0.1, jitter=0.1, exceptions=(ValueError,))
    def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError(f"模拟失败 {call_count}")
        return "success"
    
    result = flaky_function()
    assert result == "success", "最终应该成功"
    assert call_count == 3, f"应该调用 3 次，实际 {call_count}"
    
    print(f"  调用次数: {call_count}")
    print("  ✓ Retry 测试通过")
    
    # ========== 总结 ==========
    print("\n" + "=" * 60)
    print("[self_test_core] ✓ 所有 Core 模块测试通过！")
    print("=" * 60)
