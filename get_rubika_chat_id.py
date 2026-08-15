import os
import asyncio
from rubka import Robot

TOKEN = os.getenv("RUBIKA_TOKEN", "").strip()

CHANNEL_USERNAME = "Yazdandoustsilver"


async def main():
    if not TOKEN:
        print("❌ RUBIKA_TOKEN پیدا نشد")
        return

    bot = Robot(token=TOKEN)

    print("========== RUBIKA CHANNEL LOOKUP ==========")
    print("CHANNEL:", CHANNEL_USERNAME)
    print()

    # روش اول: get_chat با username
    try:
        result = await bot.get_chat(CHANNEL_USERNAME)
        print("========== GET_CHAT RESULT ==========")
        print(result)
        print("=====================================")
    except Exception as e:
        print("❌ get_chat ERROR:")
        print(type(e).__name__, str(e))

    # روش دوم: get_chat_info با username
    try:
        result = await bot.get_chat_info(CHANNEL_USERNAME)
        print("\n========== GET_CHAT_INFO RESULT ==========")
        print(result)
        print("===========================================")
    except Exception as e:
        print("❌ get_chat_info ERROR:")
        print(type(e).__name__, str(e))


asyncio.run(main())
