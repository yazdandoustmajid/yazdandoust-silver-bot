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
    print(f"CHANNEL USERNAME: {CHANNEL_USERNAME}")
    print()

    # 1) بررسی متدهای موجود در نسخه Rubka نصب‌شده
    print("========== AVAILABLE METHODS ==========")

    methods = [
        x for x in dir(bot)
        if not x.startswith("_")
    ]

    for name in methods:
        if any(word in name.lower() for word in [
            "chat",
            "channel",
            "search",
            "username",
            "object"
        ]):
            print(name)

    print()
    print("========================================")


asyncio.run(main())
