"""
测试独立窗口方案
查找所有微信独立聊天窗口，并在每个窗口发送窗口名

用法：
  python test_independent_windows.py --list          # 只列出窗口
  python test_independent_windows.py --test 家人们   # 测试单个窗口
  python test_independent_windows.py --send          # 真正发送（谨慎！）
"""

import sys
import time
import uiautomation as auto
import pyperclip


def find_wechat_chat_windows():
    """查找所有微信独立聊天窗口"""
    windows = []
    root = auto.GetRootControl()
    
    for win in root.GetChildren():
        try:
            class_name = win.ClassName or ""
            name = win.Name or ""
            
            # 微信聊天窗口特征：Qt51514QWindowIcon 类名，且名字不是"微信"
            if "Qt51514QWindowIcon" in class_name and name and name != "微信":
                windows.append({
                    "name": name,
                    "window": win,
                    "rect": win.BoundingRectangle
                })
        except:
            pass
    
    return windows


def list_windows():
    """列出所有微信独立聊天窗口"""
    print("=" * 60)
    print("  查找微信独立聊天窗口")
    print("=" * 60)
    print()
    
    windows = find_wechat_chat_windows()
    
    if not windows:
        print("未找到任何独立聊天窗口")
        print()
        print("提示：在微信中双击聊天打开独立窗口")
        return []
    
    print(f"找到 {len(windows)} 个独立聊天窗口：")
    print()
    
    for i, w in enumerate(windows, 1):
        rect = w["rect"]
        print(f"  {i}. {w['name']}")
        if rect:
            print(f"     位置: ({rect.left}, {rect.top}) 大小: {rect.width()}x{rect.height()}")
        print()
    
    return windows


def focus_and_send(window, message, dry_run=True):
    """聚焦窗口并发送消息"""
    name = window["name"]
    win = window["window"]
    
    print(f"[{name}] 正在处理...")
    
    try:
        # 1. 激活窗口
        win.SetFocus()
        time.sleep(0.3)
        
        # 2. 点击窗口使其获得焦点
        win.Click()
        time.sleep(0.3)
        
        if dry_run:
            print(f"[{name}] [DRY RUN] 将发送: {message}")
            return True
        
        # 3. 复制消息到剪贴板
        pyperclip.copy(message)
        time.sleep(0.1)
        
        # 4. Ctrl+V 粘贴
        auto.SendKeys("{Ctrl}v")
        time.sleep(0.2)
        
        # 5. Enter 发送
        auto.SendKeys("{Enter}")
        time.sleep(0.3)
        
        print(f"[{name}] ✓ 已发送: {message}")
        return True
        
    except Exception as e:
        print(f"[{name}] ✗ 发送失败: {e}")
        return False


def test_single_window(target_name):
    """测试单个窗口（只聚焦不发送）"""
    print(f"查找窗口: {target_name}")
    print()
    
    windows = find_wechat_chat_windows()
    
    target = None
    for w in windows:
        if target_name in w["name"]:
            target = w
            break
    
    if not target:
        print(f"✗ 未找到包含 '{target_name}' 的窗口")
        print()
        print("可用窗口:")
        for w in windows:
            print(f"  - {w['name']}")
        return False
    
    print(f"✓ 找到窗口: {target['name']}")
    print()
    
    # 聚焦窗口
    try:
        win = target["window"]
        win.SetFocus()
        time.sleep(0.3)
        win.Click()
        print(f"✓ 已聚焦窗口: {target['name']}")
        return True
    except Exception as e:
        print(f"✗ 聚焦失败: {e}")
        return False


def send_to_all_windows(dry_run=True):
    """向所有独立窗口发送各自的窗口名"""
    windows = find_wechat_chat_windows()
    
    if not windows:
        print("未找到任何独立聊天窗口")
        return
    
    print("=" * 60)
    if dry_run:
        print("  [DRY RUN] 模拟发送到所有独立窗口")
    else:
        print("  [真实发送] 发送到所有独立窗口")
    print("=" * 60)
    print()
    
    success = 0
    failed = 0
    
    for w in windows:
        # 发送内容就是窗口名（群名）
        message = f"测试消息 - 窗口名: {w['name']}"
        
        if focus_and_send(w, message, dry_run=dry_run):
            success += 1
        else:
            failed += 1
        
        time.sleep(0.5)  # 窗口切换间隔
    
    print()
    print("-" * 60)
    print(f"完成: 成功 {success}, 失败 {failed}")


def main():
    args = sys.argv[1:]
    
    if not args or "--list" in args or "-l" in args:
        list_windows()
    
    elif "--test" in args or "-t" in args:
        # 获取目标窗口名
        try:
            idx = args.index("--test") if "--test" in args else args.index("-t")
            target = args[idx + 1] if idx + 1 < len(args) else None
        except:
            target = None
        
        if target:
            test_single_window(target)
        else:
            print("用法: python test_independent_windows.py --test <窗口名>")
            print("示例: python test_independent_windows.py --test 家人们")
    
    elif "--send" in args:
        print("⚠️  警告: 即将真实发送消息到所有独立窗口！")
        print()
        confirm = input("确认发送? (输入 yes 继续): ")
        if confirm.lower() == "yes":
            send_to_all_windows(dry_run=False)
        else:
            print("已取消")
    
    elif "--dry" in args or "-d" in args:
        send_to_all_windows(dry_run=True)
    
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

