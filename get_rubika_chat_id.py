import os
import asyncio
from rubka import Robot

TOKEN = os.getenv("RUBIKA_TOKEN", "").strip()

if not TOKEN:
    print("❌ RUBIKA_TOKEN پیدا نشد")
    raise SystemExit(1)


async def main():
    bot = Robot(token=TOKEN)

    print("========== RUBIKA BOT INFO ==========")

    try:
        result = await bot.get_me()
        print(result)
    except Exception as e:
        print("❌ get_me ERROR:")
        print(type(e).__name__, str(e))

    print("=====================================")


asyncio.run(main())
