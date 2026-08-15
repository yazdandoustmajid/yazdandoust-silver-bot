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

    print("========== RUBIKA CHANNEL TEST ==========")
    print("CHANNEL USERNAME:", CHANNEL_USERNAME)

    # تست 1: تلاش برای دریافت اطلاعات با username
    try:
        result = bot.get_chat(CHANNEL_USERNAME)
        print("\n========== GET CHAT RESULT ==========")
        print(result)
    except Exception as e:
        print("\n❌ get_chat ERROR:")
        print(type(e).__name__, e)

    # تست 2: بررسی متدهای موجود
    print("\n========== RELEVANT METHODS ==========")

    for name in dir(bot):
        if name.startswith("_"):
            continue

        if any(x in name.lower() for x in [
            "chat",
            "channel",
            "username",
            "search"
        ]):
            try:
                attr = getattr(bot, name)
                print(name)
            except Exception:
                pass

    print("\n======================================")

asyncio.run(main())
