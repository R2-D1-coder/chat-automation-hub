"""
Windows UI Inspector 工具
用于检查 Windows UI 元素并获取 locator

运行方式:
  python inspect_ui.py              # 交互模式
  python inspect_ui.py --wechat     # 直接检查微信
  python inspect_ui.py --list       # 列出所有窗口
  python inspect_ui.py --mouse      # 鼠标追踪模式

输出的信息可用于构造 Robocorp/uiautomation 的 locator
"""

import sys
import time
import uiautomation as auto


def print_element_info(element, indent=0):
    """打印元素详细信息"""
    prefix = "  " * indent
    try:
        # 预先获取所有属性，避免多次访问 COM 对象
        ctrl_type = ""
        class_name = ""
        name = ""
        auto_id = ""
        rect = None
        
        try:
            ctrl_type = element.ControlTypeName or ""
        except:
            pass
        try:
            class_name = element.ClassName or ""
        except:
            pass
        try:
            name = element.Name or ""
        except:
            pass
        try:
            auto_id = element.AutomationId or ""
        except:
            pass
        try:
            rect = element.BoundingRectangle
        except:
            pass
        
        print(f"{prefix}┌─────────────────────────────────────────────────")
        print(f"{prefix}│ ControlType: {ctrl_type}")
        print(f"{prefix}│ ClassName:   {class_name}")
        print(f"{prefix}│ Name:        {name}")
        print(f"{prefix}│ AutomationId:{auto_id}")
        
        if rect:
            try:
                print(f"{prefix}│ Rect:        ({rect.left}, {rect.top}, {rect.right}, {rect.bottom})")
                print(f"{prefix}│ Size:        {rect.width()} x {rect.height()}")
            except:
                pass
        
        # 生成可用的 locator 建议
        print(f"{prefix}├─────────────────────────────────────────────────")
        print(f"{prefix}│ Locator 建议:")
        
        if name:
            print(f"{prefix}│   name:\"{name}\"")
        if class_name:
            print(f"{prefix}│   class:{class_name}")
        if auto_id:
            print(f"{prefix}│   id:{auto_id}")
        if ctrl_type:
            print(f"{prefix}│   control:{ctrl_type}")
        
        # 组合 locator
        parts = []
        if ctrl_type:
            parts.append(f"control:{ctrl_type}")
        if name:
            parts.append(f'name:"{name}"')
        if parts:
            print(f"{prefix}│   组合: {' and '.join(parts)}")
        
        print(f"{prefix}└─────────────────────────────────────────────────")
    except Exception as e:
        # 忽略 COM 事件错误
        if getattr(e, 'args', [None])[0] != -2147220991:
            print(f"{prefix}[错误] 无法获取元素信息: {e}")


def print_tree(element, max_depth=3, current_depth=0):
    """打印元素树"""
    if current_depth > max_depth:
        return
    
    prefix = "  " * current_depth
    try:
        name = ""
        ctrl_type = ""
        class_name = ""
        
        try:
            name = element.Name or ""
            if len(name) > 30:
                name = name[:30] + "..."
        except:
            pass
        try:
            ctrl_type = element.ControlTypeName or ""
        except:
            pass
        try:
            class_name = element.ClassName or ""
        except:
            pass
        
        print(f"{prefix}├─ [{ctrl_type}] {class_name} \"{name}\"")
        
        try:
            children = element.GetChildren()
            for child in children:
                print_tree(child, max_depth, current_depth + 1)
        except:
            pass
    except:
        pass


def list_windows():
    """列出所有顶层窗口"""
    print("=" * 60)
    print("  所有可见窗口")
    print("=" * 60)
    print()
    
    root = auto.GetRootControl()
    for win in root.GetChildren():
        try:
            if win.ClassName and win.Name:
                print(f"  • [{win.ClassName}] {win.Name}")
        except:
            pass
    print()


def find_wechat():
    """查找微信窗口"""
    root = auto.GetRootControl()
    
    # 尝试多种方式查找微信
    wechat = None
    
    # 方法1: 按类名
    try:
        wechat = auto.WindowControl(ClassName="WeChatMainWndForPC")
        if wechat.Exists(0.5):
            return wechat
    except:
        pass
    
    # 方法2: 按名称
    try:
        wechat = auto.WindowControl(Name="微信")
        if wechat.Exists(0.5):
            return wechat
    except:
        pass
    
    return None


def inspect_wechat():
    """检查微信窗口"""
    print("=" * 60)
    print("  正在查找微信窗口...")
    print("=" * 60)
    print()
    
    wechat = find_wechat()
    
    if wechat:
        print("✓ 找到微信窗口")
        print()
        print_element_info(wechat)
        print()
        print("控件树 (深度=3):")
        print("-" * 60)
        print_tree(wechat, max_depth=3)
    else:
        print("✗ 未找到微信窗口")
        print()
        print("可用窗口:")
        list_windows()


def mouse_track_mode():
    """鼠标追踪模式 - 实时显示鼠标下的元素信息"""
    print("=" * 60)
    print("  鼠标追踪模式")
    print("=" * 60)
    print()
    print("将鼠标移到目标控件上，按 Ctrl+C 退出")
    print("每 1.5 秒更新一次...")
    print("-" * 60)
    print()
    
    last_name = None
    last_class = None
    error_count = 0
    
    try:
        while True:
            try:
                element = auto.ControlFromCursor()
                
                if element:
                    curr_name = element.Name
                    curr_class = element.ClassName
                    
                    # 只在元素变化时打印
                    if curr_name != last_name or curr_class != last_class:
                        print(f"\n[{time.strftime('%H:%M:%S')}] 鼠标位置元素:")
                        print_element_info(element)
                        last_name = curr_name
                        last_class = curr_class
                        error_count = 0
                
            except Exception as e:
                error_code = getattr(e, 'args', [None])[0]
                # 忽略 COM 事件订阅错误 (0x80040201 = -2147220991)
                if error_code == -2147220991:
                    error_count += 1
                    if error_count == 1:
                        print("[提示] 部分控件无法访问，继续扫描...")
                else:
                    print(f"[错误] {e}")
            
            time.sleep(1.5)
            
    except KeyboardInterrupt:
        print("\n\n已退出鼠标追踪模式")


def interactive_mode():
    """交互模式"""
    print("=" * 60)
    print("  Windows UI Inspector")
    print("=" * 60)
    print()
    print("命令:")
    print("  m          - 鼠标追踪模式（悬停识别控件）")
    print("  w          - 检查微信窗口")
    print("  l          - 列出所有窗口")
    print("  f <名称>   - 按名称查找窗口")
    print("  t <名称>   - 打印窗口控件树")
    print("  q          - 退出")
    print()
    print("-" * 60)
    
    while True:
        try:
            cmd = input("\n> ").strip()
            
            if not cmd:
                continue
            
            if cmd == "q":
                print("再见！")
                break
            
            elif cmd == "m":
                mouse_track_mode()
            
            elif cmd == "w":
                inspect_wechat()
            
            elif cmd == "l":
                list_windows()
            
            elif cmd.startswith("f "):
                name = cmd[2:].strip()
                if name:
                    print(f"\n查找包含 \"{name}\" 的窗口...")
                    root = auto.GetRootControl()
                    found = False
                    for win in root.GetChildren():
                        try:
                            if name.lower() in win.Name.lower():
                                print()
                                print_element_info(win)
                                found = True
                        except:
                            pass
                    if not found:
                        print(f"未找到包含 \"{name}\" 的窗口")
            
            elif cmd.startswith("t "):
                name = cmd[2:].strip()
                if name:
                    print(f"\n查找 \"{name}\" 并打印控件树...")
                    try:
                        win = auto.WindowControl(SubName=name)
                        if win.Exists(1):
                            print()
                            print_element_info(win)
                            print()
                            print("控件树:")
                            print_tree(win, max_depth=4)
                        else:
                            print(f"未找到 \"{name}\"")
                    except Exception as e:
                        print(f"错误: {e}")
            
            else:
                print("未知命令。输入 q 退出，或查看上方命令列表。")
                
        except KeyboardInterrupt:
            print("\n\n按 q 退出，或继续输入命令。")
        except EOFError:
            break


def main():
    args = sys.argv[1:]
    
    if "--wechat" in args or "-w" in args:
        inspect_wechat()
    elif "--list" in args or "-l" in args:
        list_windows()
    elif "--mouse" in args or "-m" in args:
        mouse_track_mode()
    elif "--help" in args or "-h" in args:
        print(__doc__)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
