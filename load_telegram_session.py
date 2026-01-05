#!/usr/bin/env python3
"""
快速加载已保存的 Telegram StringSession

如果已经生成过 session，可以用这个脚本直接读取保存的 session 字符串
无需重新登录和输入验证码
"""

import os
import json
import sys


def load_session_from_file():
    """从文件中加载已保存的 StringSession"""
    session_file = "output/telegram_session_string.txt"

    if not os.path.exists(session_file):
        print("✗ 未找到保存的 session 文件")
        print(f"  路径: {session_file}")
        print()
        print("  请先运行: python setup_telegram_session.py")
        return None

    try:
        with open(session_file, 'r', encoding='utf-8') as f:
            session_string = f.read().strip()

        if not session_string:
            print("✗ session 文件为空")
            return None

        print("✓ 已加载 StringSession")
        print(f"  长度: {len(session_string)} 字符")
        print()

        return session_string

    except Exception as e:
        print(f"✗ 读取文件失败: {e}")
        return None


def load_session_info():
    """加载 session 的元数据信息"""
    info_file = "output/telegram_session.json"

    if not os.path.exists(info_file):
        print("  (未找到元数据文件)")
        return None

    try:
        with open(info_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return data

    except Exception as e:
        print(f"  警告：读取元数据失败: {e}")
        return None


def show_usage():
    """显示使用说明"""
    print("=" * 60)
    print("  Telegram StringSession 加载工具")
    print("=" * 60)
    print()

    session = load_session_from_file()
    if not session:
        return

    info = load_session_info()

    if info:
        user = info.get('user', {})
        print(f"  账户信息:")
        print(f"    用户ID: {user.get('id')}")
        print(f"    名称: {user.get('first_name')}")
        print(f"    用户名: @{user.get('username', 'N/A')}")
        print(f"    手机号: {user.get('phone')}")
        print()

    print("  StringSession 字符串:")
    print()
    print(f"  {session}")
    print()
    print("=" * 60)
    print()
    print("  使用方法：")
    print()
    print("  1. 在 test_feishu_notification_event.py 第 75 行:")
    print()
    print(f'     TELEGRAM_SESSION = "{session}"')
    print()
    print("  2. 或在代码中使用此脚本加载:")
    print()
    print("     from load_telegram_session import load_session_from_file")
    print("     TELEGRAM_SESSION = load_session_from_file()")
    print()
    print("=" * 60)
    print()


def copy_to_clipboard(text):
    """复制到剪贴板（Windows）"""
    try:
        import subprocess
        process = subprocess.Popen(
            ['clip'],
            stdin=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        process.communicate(input=text.encode('utf-8'))
        return True
    except Exception:
        return False


if __name__ == "__main__":
    show_usage()

    # 如果有 --copy 参数，复制到剪贴板
    if len(sys.argv) > 1 and sys.argv[1] == '--copy':
        session = load_session_from_file()
        if session and copy_to_clipboard(session):
            print("✓ StringSession 已复制到剪贴板")
        else:
            print("✗ 无法复制到剪贴板")
