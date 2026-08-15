import os
import asyncio
from rubka import Robot

TOKEN = os.getenv("RUBIKA_TOKEN", "").strip()

CHANNEL_USERNAME = "Yazdandoustsilver"
CHANNEL_LINK = "https://rubika.ir/Yazdandoustsilver"


async def main():
    if not TOKEN:
        print("❌ RUBIKA_TOKEN پیدا نشد")
        return

    bot = Robot(token=TOKEN)

    print("========== RUBIKA CHANNEL INFO ==========")
    print("CHANNEL:", CHANNEL_USERNAME)
    print("LINK:", CHANNEL_LINK)
    print()

    # بررسی متد get_username
    try:
        result = await bot.get_username(CHANNEL_USERNAME)

        print("========== GET_USERNAME RESULT ==========")
        print(result)
        print("=========================================")

    except Exception as e:
        print("❌ get_username ERROR:")
        print(type(e).__name__, str(e))

    print()

    # بررسی get_bot_chat_id
    try:
        result = await bot.get_bot_chat_id()

        print("========== GET_BOT_CHAT_ID RESULT ==========")
        print(result)
        print("=============================================")

    except Exception as e:
        print("❌ get_bot_chat_id ERROR:")
        print(type(e).__name__, str(e))


asyncio.run(main())
