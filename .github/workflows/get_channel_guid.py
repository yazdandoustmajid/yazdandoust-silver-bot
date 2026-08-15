import requests

USERNAME = "Yazdandoustsilver"

print("=" * 50)
print("RUBIKA CHANNEL GUID")
print("=" * 50)
print("USERNAME:", USERNAME)
print()

url = f"https://rubika.ir/{USERNAME}"

try:
    r = requests.get(
        url,
        timeout=15,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    print("HTTP STATUS:", r.status_code)
    print("FINAL URL:", r.url)
    print()

    text = r.text

    # جست‌وجوی عبارت‌های احتمالی مربوط به شناسه کانال
    keys = [
        "object_guid",
        "channel_guid",
        "channelGuid",
        "objectGuid",
        "guid"
    ]

    found = False

    for key in keys:
        pos = text.find(key)
        if pos != -1:
            found = True
            print("FOUND:", key)
            print(text[max(0, pos - 200):pos + 500])
            print("-" * 50)

    if not found:
        print("NO GUID FOUND IN PUBLIC PAGE")
        print()
        print("PAGE LENGTH:", len(text))

except Exception as e:
    print("ERROR:", type(e).__name__)
    print(str(e))

print()
print("=" * 50)
print("DONE")
print("=" * 50)
