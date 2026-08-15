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
    print("RUBIKA UNIVERSAL MESSAGE TEST")
    print("=" * 45)

    found = False

    @bot.on_message()
    async def handler(message):

        nonlocal found
        found = True

        print()
        print("=" * 45)
        print("✅ MESSAGE RECEIVED")
        print("=" * 45)

        print("CHAT ID:", getattr(message, "chat_id", None))
        print("MESSAGE ID:", getattr(message, "message_id", None))
        print("TEXT:", getattr(message, "text", None))
        print("SENDER ID:", getattr(message, "sender_id", None))

        print("=" * 45)

    print("🟢 Listener فعال شد")
    print("📩 حالا داخل کانال یک پیام جدید بفرست:")
    print("تست")

    try:
        await asyncio.wait_for(bot.run(), timeout=10)

    except asyncio.TimeoutError:
        print()
        print("⏱ Timeout")

    except Exception as e:
        print()
        print("❌ ERROR:")
        print(type(e).__name__, e)

    print()

    if not found:
        print("❌ هیچ پیام جدیدی دریافت نشد.")
    else:
        print("🎯 پیام دریافت شد.")


asyncio.run(main())
