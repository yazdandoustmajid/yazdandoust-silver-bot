import os
import asyncio
from rubka import Robot

TOKEN = os.getenv("RUBIKA_TOKEN", "").strip()


async def main():
    if not TOKEN:
        print("❌ RUBIKA_TOKEN پیدا نشد")
        return

    bot = Robot(token=TOKEN)

    print("========== ADMIN CHAT TEST ==========")

    try:
        result = await bot.get_admin_chat()

        print("========== GET_ADMIN_CHAT RESULT ==========")
        print(result)
        print("============================================")

    except Exception as e:
        print("❌ get_admin_chat ERROR:")
        print(type(e).__name__, str(e))

    print("============================================")


asyncio.run(main())
