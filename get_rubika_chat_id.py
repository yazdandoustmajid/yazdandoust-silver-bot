import os
import asyncio
import inspect
from rubka import Robot

TOKEN = os.getenv("RUBIKA_TOKEN", "").strip()

CHANNEL_USERNAME = "Yazdandoustsilver"


async def main():
    if not TOKEN:
        print("❌ RUBIKA_TOKEN پیدا نشد")
        return

    bot = Robot(token=TOKEN)

    print("========== RUBIKA CHANNEL TEST ==========")
    print("CHANNEL USERNAME:", CHANNEL_USERNAME)

    # ==========================================
    # تست مستقیم کانال با username
    # ==========================================
    try:
        result = await bot.get_chat(CHANNEL_USERNAME)

        print("\n========== GET CHAT RESULT ==========")
        print(result)

        if isinstance(result, dict):
            print("\n========== CHAT FIELDS ==========")

            for key, value in result.items():
                print(f"{key}: {value}")

            # تلاش برای پیدا کردن شناسه
            for key in ["chat_id", "channel_guid", "guid", "object_guid", "id"]:
                if key in result:
                    print(f"\n✅ احتمالی {key}: {result[key]}")

    except Exception as e:
        print("\n❌ get_chat ERROR:")
        print(type(e).__name__, e)

    # ==========================================
    # نمایش امضای متدهای مهم
    # ==========================================
    print("\n========== METHOD SIGNATURES ==========")

    for name in [
        "get_chat",
        "get_chat_info",
        "get_chat_type",
        "get_username",
        "get_bot_chat_id",
        "get_updates"
    ]:
        try:
            attr = getattr(bot, name)
            print(f"{name}{inspect.signature(attr)}")
        except Exception as e:
            print(f"{name}: {e}")

    print("\n=========================================")


asyncio.run(main())
