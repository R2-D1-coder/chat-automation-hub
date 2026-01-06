"""
获取 Telegram 频道/群组 ID

用于查找心跳包或消息转发的目标频道 ID
"""

import asyncio
import os
import json

def main():
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("请先安装 telethon: pip install telethon")
        return

    # 从 config.json 读取配置
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if not os.path.exists(config_path):
        print(f"配置文件不存在: {config_path}")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    tg_config = config.get("feishu_monitor", {}).get("telegram", {})
    session = tg_config.get("session", "")
    api_id = tg_config.get("api_id", "")
    api_hash = tg_config.get("api_hash", "")

    if not session or not api_id or not api_hash:
        print("Telegram 配置不完整，请检查 config.json 中的 feishu_monitor.telegram 配置")
        return

    async def list_dialogs():
        client = TelegramClient(StringSession(session), int(api_id), api_hash)
        await client.connect()

        if not await client.is_user_authorized():
            print("Telegram session 无效或已过期")
            await client.disconnect()
            return

        me = await client.get_me()
        print(f"已登录: {me.first_name} (@{me.username or 'N/A'})")
        print()
        print("频道/群组列表：")
        print("-" * 50)

        async for dialog in client.iter_dialogs(limit=100):
            name = dialog.name or "(无名称)"
            print(f"  {name}: {dialog.id}")

        print("-" * 50)
        print()
        print("将上面的 ID（如 -1003215157978）填入 config.json 的 chat 字段即可")

        await client.disconnect()

    asyncio.run(list_dialogs())


if __name__ == "__main__":
    main()
