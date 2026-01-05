#!/usr/bin/env python3
"""
生成和保存持久化 Telegram StringSession

运行方式：
    python setup_telegram_session.py

将生成的 StringSession 复制到 test_feishu_notification_event.py 的 TELEGRAM_SESSION 变量
"""

import asyncio
import os
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.network.connection.tcpabridged import ConnectionTcpAbridged

# ============================================================
# Telegram 配置（与 test_feishu_notification_event.py 一致）
# ============================================================

TELEGRAM_API_ID = '11876733'
TELEGRAM_API_HASH = '77f852c41e130ea83bac7674b4160d36'
TELEGRAM_PHONE = '+8618810932403'

# 输出文件
SESSION_FILE = "output/telegram_session_string.txt"
SESSION_JSON_FILE = "output/telegram_session.json"

# 重试次数
MAX_RETRIES = 5


async def generate_session():
    """生成持久化的 Telegram StringSession"""

    # 确保 output 目录存在
    os.makedirs("output", exist_ok=True)

    print("=" * 60)
    print("  Telegram StringSession 生成工具")
    print("=" * 60)
    print()

    # 使用 StringSession（空字符串表示首次登录）
    session = StringSession()

    client = TelegramClient(
        session,
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
        connection=ConnectionTcpAbridged,
        auto_reconnect=True,
        connection_retries=10,
        retry_delay=2,
        timeout=30,
    )

    # 尝试连接，带重试
    connected = False
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f"正在连接 Telegram 服务器... (尝试 {attempt}/{MAX_RETRIES})")
            await client.connect()
            connected = True
            print("[OK] 连接成功")
            break
        except Exception as e:
            print(f"[WARN] 连接失败: {e}")
            if attempt < MAX_RETRIES:
                wait_time = attempt * 2
                print(f"  等待 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)
            else:
                print("[ERROR] 达到最大重试次数，连接失败")
                print()
                print("可能的原因：")
                print("  1. 网络不稳定")
                print("  2. 需要代理/VPN 访问 Telegram")
                print("  3. Telegram 服务器临时问题")
                print()
                print("解决方案：")
                print("  - 检查网络连接")
                print("  - 尝试使用代理")
                print("  - 稍后再试")
                return

    if not connected:
        return

    try:

        # 检查是否已登录
        is_authorized = await client.is_user_authorized()
        if is_authorized:
            print("[OK] 已登录（使用现有会话）")
            me = await client.get_me()
            print(f"  账户: {me.first_name} (@{me.username or 'N/A'})")
        else:
            print("首次登录，需要验证码")
            print()

            # 发送验证码
            phone = (TELEGRAM_PHONE or "").strip()
            if not phone:
                print("请输入你的手机号（带国际区号，如 +86138xxxx）:")
                phone = input("手机号: ").strip()

            await client.send_code_request(phone)
            print("[OK] 验证码已发送")
            print()

            code = input("请输入验证码: ").strip()

            try:
                await client.sign_in(phone, code)
                print("[OK] 登录成功")
            except Exception as e:
                if "two-step" in str(e).lower() or "password" in str(e).lower():
                    print("需要两步验证密码:")
                    password = input("密码: ").strip()
                    await client.sign_in(password=password)
                    print("[OK] 登录成功")
                else:
                    raise

            # 获取用户信息
            me = await client.get_me()
            print(f"  账户: {me.first_name} (@{me.username or 'N/A'})")

        # 获取 StringSession
        session_string = client.session.save()

        print()
        print("=" * 60)
        print("  生成的 StringSession")
        print("=" * 60)
        print()
        print(session_string)
        print()
        print("=" * 60)
        print()

        # 保存到文件
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            f.write(session_string)

        print(f"[OK] 已保存到文件: {SESSION_FILE}")
        print()

        # 提供 JSON 格式备份
        import json
        session_data = {
            "api_id": TELEGRAM_API_ID,
            "api_hash": TELEGRAM_API_HASH,
            "phone": TELEGRAM_PHONE,
            "string_session": session_string,
            "user": {
                "id": me.id,
                "first_name": me.first_name,
                "username": me.username or None,
                "phone": me.phone or None,
            }
        }

        with open(SESSION_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)

        print(f"[OK] JSON 备份已保存: {SESSION_JSON_FILE}")
        print()

        # 使用说明
        print("=" * 60)
        print("  使用方法")
        print("=" * 60)
        print()
        print("1. 打开 test_feishu_notification_event.py")
        print()
        print("2. 找到第 75 行的 TELEGRAM_SESSION 配置:")
        print()
        print(f'   TELEGRAM_SESSION = "{session_string}"')
        print()
        print("   或直接从下面复制：")
        print()
        print(f'   TELEGRAM_SESSION = "{session_string}"')
        print()
        print("3. 替换掉空字符串")
        print()
        print("4. 下次运行时，脚本将直接使用该 session，无需再输入验证码")
        print()
        print("=" * 60)
        print()

    except Exception as e:
        print(f"[ERROR] 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(generate_session())
