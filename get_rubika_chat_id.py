import os
import asyncio

from rubka import Robot

TOKEN = os.getenv("RUBIKA_TOKEN", "").strip()

CHANNEL_VALUES = [
    "Yazdandoustsilver",
    "@Yazdandoustsilver",
    "https://rubika.ir/Yazdandoustsilver",
]


async def main():
    if not TOKEN:
        print("❌ RUBIKA_TOKEN پیدا نشد")
        return

    bot = Robot(token=TOKEN)

    print("========== RUBIKA CHANNEL DISCOVERY ==========")

    for value in CHANNEL_VALUES:

        print("\n======================================")
        print("TEST VALUE:")
        print(value)
        print("======================================")

        # -----------------------------
        # get_chat
        # -----------------------------
        try:
            result = await bot.get_chat(value)

            print("\nGET_CHAT RESULT:")
            print(result)

        except Exception as e:
            print("\nGET_CHAT ERROR:")
            print(type(e).__name__, e)

        # -----------------------------
        # get_chat_info
        # -----------------------------
        try:
            result = await bot.get_chat_info(value)

            print("\nGET_CHAT_INFO RESULT:")
            print(result)

        except Exception as e:
            print("\nGET_CHAT_INFO ERROR:")
            print(type(e).__name__, e)

    print("\n======================================")
    print("DONE")
    print("======================================")


asyncio.run(main())
