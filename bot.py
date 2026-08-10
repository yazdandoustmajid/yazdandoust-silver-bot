# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from telethon import TelegramClient


BASE_DIR = Path(__file__).resolve().parent

TEMPLATE_FILE = BASE_DIR / "board_only_preview.png"
OUTPUT_FILE = BASE_DIR / "latest_price.jpg"
STATE_FILE = BASE_DIR / "state.json"

API_ID = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "").strip()

SOURCE_URL = "https://t.me/s/tghsilver"
WEBSITE_URL = "https://taghizadegan.com"

PHONE = "09152449600"
TELEGRAM_ID = "@MajidYazdandoust"

MITHQAL_GRAMS = 4.6083
CHECK_INTERVAL = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("YAZDANDOUST")

PERSIAN = "۰۱۲۳۴۵۶۷۸۹"
ARABIC = "٠١٢٣٤٥٦٧٨٩"
ENGLISH = "0123456789"

DIGIT_TABLE = str.maketrans(
    PERSIAN + ARABIC,
    ENGLISH + ENGLISH
)


def normalize_digits(text):
    return (text or "").translate(DIGIT_TABLE)


def clean_text(text):
    text = normalize_digits(text)
    text = (
        text
        .replace("\u200c", " ")
        .replace("٬", ",")
        .replace("٫", ".")
    )
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def integer_value(text):
    text = normalize_digits(text)
    text = (
        text
        .replace(",", "")
        .replace("٬", "")
        .replace(" ", "")
    )
    text = re.sub(r"[^\d]", "", text)

    if not text:
        return None

    return int(text)


def decimal_value(text):
    text = normalize_digits(text)
    text = (
        text
        .replace(",", "")
        .replace("٬", "")
        .replace("٫", ".")
    )
    text = re.sub(r"[^\d.]", "", text)

    if not text:
        return None

    return float(text)


def format_price(value):
    return f"{int(round(value)):,}"


def iran_time():
    return datetime.now(
        ZoneInfo("Asia/Tehran")
    )


SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent":
        "Mozilla/5.0 "
        "(iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
})


def http_get(url):
    response = SESSION.get(
        url,
        timeout=30
    )

    response.raise_for_status()

    return response.text


def get_source_page():
    return http_get(
        SOURCE_URL
    )


def parse_telegram_rate(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = clean_text(
        soup.get_text(
            "\n",
            strip=True
        )
    )

    ounce_match = re.search(
        r"انس\s*[:：]?\s*"
        r"(\d+(?:[.,]\d+)?)",
        text
    )

    if not ounce_match:
        return None

    ounce = decimal_value(
        ounce_match.group(1)
    )

    dollar_match = re.search(
        r"دلار\s*تهران\s*"
        r"(?:حدود)?\s*"
        r"[:：]?\s*"
        r"([\d,]+)",
        text
    )

    if not dollar_match:
        return None

    dollar_tehran = integer_value(
        dollar_match.group(1)
    )

    date_match = re.search(
        r"تاریخ\s*[:：]?\s*"
        r"(\d{4}/\d{1,2}/\d{1,2})",
        text
    )

    source_date = (
        date_match.group(1)
        if date_match
        else ""
    )

    if ounce is None:
        return None

    if dollar_tehran is None:
        return None

    if not 20 <= ounce <= 150:
        return None

    if not 50_000 <= dollar_tehran <= 2_000_000:
        return None

    now = iran_time()

    return {
        "ounce": ounce,
        "dollar_tehran": dollar_tehran,
        "date": source_date,
        "time": now.strftime("%H:%M")
    }


def get_website_page():
    return http_get(
        WEBSITE_URL
    )


def extract_product_price(
    text,
    product_name
):

    normalized = clean_text(
        text
    )

    position = normalized.find(
        clean_text(product_name)
    )

    if position < 0:
        return None

    area = normalized[
        position:
        position + 500
    ]

    matches = re.findall(
        r"([\d.]+)\s*تومان",
        area
    )

    for item in matches:

        value = integer_value(
            item
        )

        if value is None:
            continue

        if (
            1_000_000
            <= value
            <= 10_000_000_000
        ):
            return value

    return None


def parse_website_prices(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = soup.get_text(
        "\n",
        strip=True
    )

    shot_995_package = extract_product_price(
        text,
        "نقره ساچمه 1000 گرمی با عیار 995"
    )

    if shot_995_package is None:

        shot_995_package = extract_product_price(
            text,
            "نقره ساچمه ۱۰۰۰ گرمی با عیار ۹۹۵"
        )

    nader_package = extract_product_price(
        text,
        "شمش 1000 گرمی 999.9 نادیر"
    )

    if nader_package is None:

        nader_package = extract_product_price(
            text,
            "شمش 1000 گرمی ۹۹۹.۹ نادیر"
        )

    if shot_995_package is None:

        raise RuntimeError(
            "قیمت ساچمه 995 در سایت تقی زادگان پیدا نشد."
        )

    if nader_package is None:

        raise RuntimeError(
            "قیمت شمش نادیر 999.9 در سایت تقی زادگان پیدا نشد."
        )

    shot_995_per_gram = (
        shot_995_package / 1000
    )

    nader_per_gram = (
        nader_package / 1000
    )

    mithqal_995 = (
        shot_995_per_gram
        * MITHQAL_GRAMS
    )

    mithqal_995 = (
        round(
            mithqal_995 / 100
        )
        * 100
    )

    return {
        "shot_995": int(
            round(
                shot_995_per_gram
            )
        ),

        "nader_9999": int(
            round(
                nader_per_gram
            )
        ),

        "mithqal_995": int(
            mithqal_995
        )
    }


def get_font(size):

    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]

    for path in candidates:

        if Path(path).exists():

            return ImageFont.truetype(
                path,
                size
            )

    return ImageFont.load_default()


def load_template():

    if not TEMPLATE_FILE.exists():

        raise FileNotFoundError(
            "board_only_preview.png "
            "در کنار bot.py پیدا نشد."
        )

    return Image.open(
        TEMPLATE_FILE
    ).convert(
        "RGB"
    )


def draw_centered(
    draw,
    box,
    text,
    font,
    fill=(235, 214, 175)
):

    x1, y1, x2, y2 = box

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font
    )

    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]

    x = (
        x1
        + (x2 - x1 - width) / 2
    )

    y = (
        y1
        + (y2 - y1 - height) / 2
        - bbox[1]
    )

    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill,
        stroke_width=0
    )


def create_board(
    rate,
    products
):

    image = load_template()

    draw = ImageDraw.Draw(
        image
    )

    base_width = 1060
    base_height = 1410

    sx = image.width / base_width
    sy = image.height / base_height

    def box(x1, y1, x2, y2):

        return (
            int(x1 * sx),
            int(y1 * sy),
            int(x2 * sx),
            int(y2 * sy)
        )

    boxes = [

        box(
            485,
            505,
            870,
            650
        ),

        box(
            485,
            665,
            870,
            805
        ),

        box(
            485,
            815,
            870,
            960
        ),

        box(
            485,
            970,
            870,
            1115
        ),

        box(
            485,
            1135,
            870,
            1280
        )
    ]

    values = [

        f"{rate['ounce']:.2f}",

        format_price(
            rate["dollar_tehran"]
        ),

        format_price(
            products["shot_995"]
        ),

        format_price(
            products["nader_9999"]
        ),

        format_price(
            products["mithqal_995"]
        )
    ]

    for index, (
        current_box,
        value
    ) in enumerate(
        zip(
            boxes,
            values
        )
    ):

        if index == 0:
            size = int(48 * sx)
        else:
            size = int(43 * sx)

        draw_centered(
            draw,
            current_box,
            value,
            get_font(size)
        )

    image.save(
        OUTPUT_FILE,
        "JPEG",
        quality=97,
        optimize=True,
        progressive=True
    )

    return OUTPUT_FILE


def make_caption(rate):

    now = iran_time()

    iran_clock = now.strftime(
        "%H:%M"
    )

    date_value = rate.get(
        "date",
        ""
    )

    return (
        f"📅 تاریخ: {date_value}\n"
        f"🕐 ساعت: {iran_clock}\n\n"
        f"📞 {PHONE}\n\n"
        "✅ خرید بالای ۲ کیلو "
        "تماس تلفنی جهت استعلام نرخ\n\n"
        "🔹 خرید و فروش انواع شمش‌های معتبر (قانونی)\n"
        "🔹 خرید مستعمل نقره\n"
        "🔹 نرخ خرید فاکتورهای مجموعه همانند همیشه هست\n\n"
        "💬 برای خرید یا هرگونه سؤال:\n"
        f"{TELEGRAM_ID}"
    )


def load_state():

    if not STATE_FILE.exists():
        return {}

    try:

        return json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return {}


def save_state(state):

    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


async def get_bot_client():

    if not API_ID:
        raise RuntimeError(
            "API_ID تنظیم نشده است."
        )

    if not API_HASH:
        raise RuntimeError(
            "API_HASH تنظیم نشده است."
        )

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN تنظیم نشده است."
        )

    return TelegramClient(
        "publisher_bot",
        int(API_ID),
        API_HASH
    )


async def find_existing_post(
    client,
    target
):

    state = load_state()

    saved_id = state.get(
        "message_id"
    )

    if saved_id:

        try:

            message = await client.get_messages(
                target,
                ids=int(saved_id)
            )

            if message:
                return message

        except Exception as error:

            log.warning(
                "Saved message not found: %s",
                error
            )

    async for message in client.iter_messages(
        target,
        limit=50
    ):

        text = (
            message.raw_text
            or ""
        )

        if (
            message.photo
            and PHONE in text
        ):

            return message

    return None


async def publish(
    client,
    rate,
    products
):

    target = TARGET_CHANNEL

    create_board(
        rate,
        products
    )

    caption = make_caption(
        rate
    )

    old = await find_existing_post(
        client,
        target
    )

    if old:

        await client.edit_message(
            target,
            old.id,
            file=str(OUTPUT_FILE),
            caption=caption
        )

        message_id = old.id

        log.info(
            "Existing Telegram post edited: %s",
            message_id
        )

    else:

        sent = await client.send_file(
            target,
            str(OUTPUT_FILE),
            caption=caption
        )

        message_id = sent.id

        log.info(
            "First Telegram post created: %s",
            message_id
        )

    now = iran_time()

    signature = json.dumps(
        {
            "ounce":
                rate["ounce"],

            "dollar_tehran":
                rate["dollar_tehran"],

            "shot_995":
                products["shot_995"],

            "nader_9999":
                products["nader_9999"],

            "mithqal_995":
                products["mithqal_995"],

            "date":
                rate["date"],

            "time":
                now.strftime("%H:%M")
        },
        sort_keys=True,
        ensure_ascii=False
    )

    save_state(
        {
            "message_id":
                message_id,

            "signature":
                signature
        }
    )


async def update_once(
    client
):

    telegram_html = await asyncio.to_thread(
        get_source_page
    )

    rate = parse_telegram_rate(
        telegram_html
    )

    if rate is None:

        raise RuntimeError(
            "نرخ معتبر انس و دلار تهران "
            "در کانال تقی زادگان پیدا نشد."
        )

    website_html = await asyncio.to_thread(
        get_website_page
    )

    products = parse_website_prices(
        website_html
    )

    now = iran_time()

    current_time = now.strftime(
        "%H:%M"
    )

    signature = json.dumps(
        {
            "ounce":
                rate["ounce"],

            "dollar_tehran":
                rate["dollar_tehran"],

            "shot_995":
                products["shot_995"],

            "nader_9999":
                products["nader_9999"],

            "mithqal_995":
                products["mithqal_995"],

            "date":
                rate["date"],

            "time":
                current_time
        },
        sort_keys=True,
        ensure_ascii=False
    )

    state = load_state()

    if (
        state.get("signature")
        == signature
    ):

        log.info(
            "No change: "
            "ounce=%s | dollar=%s | "
            "shot995=%s | nader=%s | "
            "mithqal=%s | time=%s",
            rate["ounce"],
            rate["dollar_tehran"],
            products["shot_995"],
            products["nader_9999"],
            products["mithqal_995"],
            current_time
        )

        return False

    rate["time"] = current_time

    await publish(
        client,
        rate,
        products
    )

    return True


async def main():

    if not TARGET_CHANNEL:

        raise RuntimeError(
            "TARGET_CHANNEL تنظیم نشده است."
        )

    client = await get_bot_client()

    await client.start(
        bot_token=BOT_TOKEN
    )

    log.info(
        "======================================"
    )

    log.info(
        "YAZDANDOUST SILVER BOT STARTED"
    )

    log.info(
        "SOURCE: %s",
        SOURCE_URL
    )

    log.info(
        "WEBSITE: %s",
        WEBSITE_URL
    )

    log.info(
        "TARGET: %s",
        TARGET_CHANNEL
    )

    log.info(
        "DOLLAR SOURCE: TEHRAN"
    )

    log.info(
        "TIME SOURCE: ASIA/TEHRAN"
    )

    log.info(
        "======================================"
    )

    while True:

        try:

            await update_once(
                client
            )

        except Exception as error:

            log.exception(
                "UPDATE ERROR: %s",
                error
            )

        await asyncio.sleep(
            CHECK_INTERVAL
        )


if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        log.info(
            "BOT STOPPED"
        )

    except Exception:

        log.exception(
            "FATAL ERROR"
        )
