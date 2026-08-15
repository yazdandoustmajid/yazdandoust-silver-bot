import os
import asyncio
import json
import inspect

from rubka import Robot


TOKEN = os.getenv("RUBIKA_TOKEN", "").strip()
TEST_TEXT = "تست ۱۲۳"


async def main():
    if not TOKEN:
        print("❌ RUBIKA_TOKEN پیدا نشد")
        return

    bot = Robot(token=TOKEN)

    try:
        print("========== RUBIKA UPDATE SEARCH ==========")
        print("🔎 در حال دریافت آخرین پیام‌ها...")
        print(f"🎯 متن مورد جستجو: {TEST_TEXT}")
        print("==========================================")

        result = await bot.get_updates(limit=20)

        print("\n========== RAW UPDATES ==========")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        print("=================================")

        updates = []

        if isinstance(result, dict):
            data = result.get("data", {})

            if isinstance(data, dict):
                updates = data.get("updates", []) or []

        elif isinstance(result, list):
            updates = result

        print(f"\n📦 تعداد Update دریافت‌شده: {len(updates)}")

        found = False

        for index, update in enumerate(updates, 1):

            print(f"\n---------- UPDATE {index} ----------")

            if not isinstance(update, dict):
                print(update)
                continue

            update_type = update.get("type")
            chat_id = update.get("chat_id")

            print("type:", update_type)
            print("chat_id:", chat_id)

            new_message = update.get("new_message")

            if isinstance(new_message, dict):

                message_text = new_message.get("text", "")
                message_id = new_message.get("message_id")

                print("message_id:", message_id)
                print("text:", message_text)

                if message_text and TEST_TEXT in message_text:

                    found = True

                    print("\n" + "=" * 55)
                    print("✅ پیام تست پیدا شد!")
                    print("=" * 55)
                    print("📌 CHAT ID:")
                    print(chat_id)
                    print("📌 MESSAGE ID:")
                    print(message_id)
                    print("📌 TEXT:")
                    print(message_text)
                    print("=" * 55)

        if not found:
            print("\n⚠️ پیام «تست ۱۲۳» در Updateها پیدا نشد.")
            print("یک بار دیگر پیام تست را در کانال بفرست و Workflow را اجرا کن.")

    except Exception as e:

        print("\n❌ ERROR:")
        print(type(e).__name__, str(e))

    finally:

        # جلوگیری از خطای Unclosed client session / connector
        for attr_name in ("session", "_session", "client_session"):

            try:
                session = getattr(bot, attr_name, None)

                if session is None:
                    continue

                close_method = getattr(session, "close", None)

                if close_method:
                    result = close_method()

                    if inspect.isawaitable(result):
                        await result

                    print("✅ HTTP session closed")
                    break

            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
