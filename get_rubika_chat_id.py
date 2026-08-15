import os
import asyncio
import inspect
from rubka import Robot

TOKEN = os.getenv("RUBIKA_TOKEN", "").strip()

async def main():
    if not TOKEN:
        print("❌ RUBIKA_TOKEN پیدا نشد")
        return

    bot = Robot(token=TOKEN)

    print("========== RUBIKA BOT CHAT ID ==========")

    try:
        bot_chat_id = await bot.get_bot_chat_id()

        print("BOT CHAT ID:")
        print(bot_chat_id)

    except Exception as e:
        print("❌ get_bot_chat_id ERROR:")
        print(type(e).__name__, e)

    print("\n========== UPDATE CHECK ==========")

    try:
        updates = await bot.get_updates(limit=100)

        print("RAW UPDATES:")
        print(updates)

    except Exception as e:
        print("❌ get_updates ERROR:")
        print(type(e).__name__, e)

    print("\n========== DONE ==========")

asyncio.run(main())
