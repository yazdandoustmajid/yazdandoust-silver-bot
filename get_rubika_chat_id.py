import os
from rubka import Robot

token = os.getenv("RUBIKA_TOKEN", "").strip()

if not token:
    print("❌ RUBIKA_TOKEN پیدا نشد")
    raise SystemExit(1)

print("✅ RUBIKA_TOKEN پیدا شد")

bot = Robot(token=token)

try:
    result = bot.get_updates(limit=20)

    print("\n========== RUBIKA UPDATES ==========\n")
    print(result)
    print("\n====================================\n")

    updates = result.get("updates", []) if isinstance(result, dict) else []

    if not updates:
        print("⚠️ هیچ Updateای پیدا نشد.")
    else:
        print(f"✅ تعداد Updateها: {len(updates)}")

        for i, update in enumerate(updates, 1):
            print(f"\n--- UPDATE {i} ---")
            print(update)

            if isinstance(update, dict):
                chat_id = update.get("chat_id")

                if chat_id:
                    print(f"🎯 CHAT_ID = {chat_id}")

                new_message = update.get("new_message")

                if isinstance(new_message, dict):
                    nested_chat_id = new_message.get("chat_id")

                    if nested_chat_id:
                        print(f"🎯 NESTED CHAT_ID = {nested_chat_id}")

except Exception as e:
    print("❌ ERROR:")
    print(type(e).__name__, str(e))
    raise
