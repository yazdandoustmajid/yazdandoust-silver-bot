import os
import asyncio
from rubka import Robot

TOKEN = os.getenv("RUBIKA_TOKEN", "").strip()


async def main():

    if not TOKEN:
        print("❌ RUBIKA_TOKEN پیدا نشد")
        return

    bot = Robot(token=TOKEN)

    print("=" * 45)
    print("RUBIKA CHANNEL TEST")
    print("=" * 45)

    found = False

    @bot.on_message_channel()
    async def channel_handler(message):
        nonlocal found
        found = True

        print()
        print("✅ CHANNEL MESSAGE RECEIVED")
        print("-" * 45)

        print("CHAT ID:", getattr(message, "chat_id", None))
        print("MESSAGE ID:", getattr(message, "message_id", None))
        print("TEXT:", getattr(message, "text", None))

        print("-" * 45)

    print("🟢 Listener فعال شد")
    print("📩 الان داخل کانال یک پیام بفرست:")
    print("تست")

    try:
        await asyncio.wait_for(bot.run(), timeout=12)

    except asyncio.TimeoutError:
        print()
        print("⏱ Timeout — تست تمام شد")

    except Exception as e:
        print()
        print("❌ ERROR:")
        print(type(e).__name__, e)

    print()

    if not found:
        print("❌ در این ۱۲ ثانیه پیام کانال دریافت نشد.")
    else:
        print("🎯 CHAT ID با موفقیت دریافت شد.")


asyncio.run(main())
