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

    print("========== RUBIKA CHAT METHODS ==========")

    for name in dir(bot):
        if name.startswith("_"):
            continue

        if any(x in name.lower() for x in [
            "chat",
            "channel",
            "list",
            "search",
            "preview",
            "username"
        ]):
            try:
                attr = getattr(bot, name)
                signature = inspect.signature(attr)
                print(f"{name}{signature}")
            except Exception:
                print(name)

    print("=========================================")


asyncio.run(main())
