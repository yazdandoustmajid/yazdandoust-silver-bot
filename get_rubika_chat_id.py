import os
import asyncio
from rubka import Robot

TOKEN = os.getenv("RUBIKA_TOKEN", "").strip()


async def main():

    if not TOKEN:
        print("❌ RUBIKA_TOKEN پیدا نشد")
        return

    bot = Robot(token=TOKEN)

    print("=" * 60)
    print("       RUBIKA CHANNEL LISTENER TEST")
    print("=" * 60)

    try:
        bot_chat_id = await bot.get_bot_chat_id()
        print("🤖 BOT CHAT ID:")
        print(bot_chat_id)
    except Exception as e:
        print("❌ BOT CHAT ID ERROR:")
        print(type(e).__name__, e)

    print()
    print("=" * 60)
    print("📡 ثبت Listener کانال...")
    print("=" * 60)

    @bot.on_message_channel()
    async def channel_message_handler(message):

        print()
        print("=" * 60)
        print("🎯🎯🎯 CHANNEL MESSAGE RECEIVED 🎯🎯🎯")
        print("=" * 60)

        print("TYPE:")
        print(type(message))

        print()
        print("CHAT ID:")
        print(getattr(message, "chat_id", None))

        print()
        print("MESSAGE ID:")
        print(getattr(message, "message_id", None))

        print()
        print("TEXT:")
        print(getattr(message, "text", None))

        print()
        print("SENDER ID:")
        print(getattr(message, "sender_id", None))

        print()
        print("RAW MESSAGE:")
        print(message)

        print()
        print("=" * 60)
        print("✅ CHANNEL CHAT ID FOUND")
        print("=" * 60)

        print()
        print("📌 CHAT ID:")
        print(getattr(message, "chat_id", None))

        print()
        print("=" * 60)

    print()
    print("=" * 60)
    print("🟢 LISTENER فعال شد")
    print("=" * 60)
    print()
    print("حالا داخل کانال یک پیام بفرست:")
    print()
    print("تست ربات")
    print()
    print("⏳ منتظر پیام کانال...")
    print()

    # اجرای دائمی ربات
    try:
        await bot.run()
    except TypeError:
        try:
            bot.run()
        except Exception as e:
            print()
            print("❌ BOT RUN ERROR:")
            print(type(e).__name__, e)

    except Exception as e:
        print()
        print("❌ BOT RUN ERROR:")
        print(type(e).__name__, e)


asyncio.run(main())
