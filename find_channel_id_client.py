import asyncio
from rubpy import Client


USERNAME = "Yazdandoustsilver"


async def main():
    print("=" * 50)
    print("RUBIKA CLIENT CHANNEL ID FINDER")
    print("=" * 50)

    async with Client(name="yazdandoust_client") as client:
        print("✅ Client started")

        print(f"🔎 Searching: @{USERNAME}")

        try:
            result = await client.get_chat(USERNAME)

            print("\n" + "=" * 50)
            print("RESULT")
            print("=" * 50)

            print(result)

        except Exception as e:
            print("\n❌ ERROR:")
            print(type(e).__name__)
            print(str(e))


if __name__ == "__main__":
    asyncio.run(main())
