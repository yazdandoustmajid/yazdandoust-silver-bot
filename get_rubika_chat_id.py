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

    print("========== RUBIKA CHANNEL UPDATE TEST ==========")
    print()
    print("🤖 BOT CHAT ID:")
    
    try:
        bot_chat_id = await bot.get_bot_chat_id()
        print(bot_chat_id)
    except Exception as e:
        print("خطا:", type(e).__name__, e)

    print()
    print("========== CHANNEL METHOD ==========")

    method = getattr(bot, "on_message_channel", None)

    if method is None:
        print("❌ on_message_channel پیدا نشد")
        return

    print("✅ on_message_channel پیدا شد")

    try:
        print("SIGNATURE:")
        print(inspect.signature(method))
    except Exception as e:
        print("SIGNATURE ERROR:", e)

    print()
    print("====================================")
    print("حالا یک پیام تست داخل کانال بفرست.")
    print("====================================")
    print()

    # دریافت آپدیت‌ها
    try:
        result = await bot.get_updates(limit=100)

        print("========== RAW UPDATES ==========")
        print(result)
        print("=================================")

        updates = result.get("data", {}).get("updates", [])

        print()
        print("تعداد Update ها:", len(updates))
        print()

        for i, update in enumerate(updates, 1):

            print(f"---------- UPDATE {i} ----------")

            print("TYPE:")
            print(update.get("type"))

            print("CHAT ID:")
            print(update.get("chat_id"))

            print("FULL UPDATE:")
            print(update)

            print()

    except Exception as e:
        print("❌ GET UPDATES ERROR:")
        print(type(e).__name__, e

        )

    print("========== DONE ==========")


asyncio.run(main())
