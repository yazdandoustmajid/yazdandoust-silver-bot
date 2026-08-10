# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import os
import re
import hashlib
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

IRAN_TZ = ZoneInfo("Asia/Tehran")


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

    if ounce is None:
        return None

    if dollar_tehran is None:
        return None

    if not 20 <= ounce <= 150:
        return None

    if not 50_000 <= dollar_tehran <= 2_000_000:
        return None

    return {
        "ounce": ounce,
        "dollar_tehran": dollar_tehran
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

    shot_995_package = (
        extract_product_price(
            text,
            "نقره ساچمه 1000 گرمی با عیار 995"
        )
    )

    if shot_995_package is None:

        shot_995_package = (
            extract_product_price(
                text,
                "نقره ساچمه ۱۰۰۰ گرمی با عیار ۹۹۵"
            )
        )

    nader_package = (
        extract_product_price(
            text,
            "شمش 1000 گرمی 999.9 نادیر"
        )
    )

    if nader_package is None:

        nader_package = (
            extract_product_price(
                text,
                "شمش 1000 گرمی ۹۹۹.۹ نادیر"
            )
        )

    if shot_995_package is None:

        raise RuntimeError(
            "\u0642\u06cc\u0645\u062a \u0633\u0627\u0686\u0645\u0647 995 \u062f\u0631 \u0633\u0627\u06cc\u062a \u062a\u0642\u06cc \u0632\u0627\u062f\u06af\u0627\u0646 \u067e\u06cc\u062f\u0627 \u0646\u0634\u062f."
        )

    if nader_package is None:

        raise RuntimeError(
            "\u0642\u06cc\u0645\u062a \u0634\u0645\u0634 \u0646\u0627\u062f\u06cc\u0631 999.9 \u062f\u0631 \u0633\u0627\u06cc\u062a \u067e\u06cc\u062f\u0627 \u0646\u0634\u062f."
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
        "shot_995":
            int(
                round(
                    shot_995_per_gram
                )
            ),

        "nader_9999":
            int(
                round(
                    nader_per_gram
                )
            ),

        "mithqal_995":
            int(
                mithqal_995
            )
    }


# =========================================================
# FONT - BOLD PRICE FONT
# =========================================================

def get_font(size):

    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]

    for path in candidates:

        if Path(path).exists():

            return ImageFont.truetype(
                path,
                size
            )

    return ImageFont.load_default()


def get_best_font(
    draw,
    text,
    box
):

    x1, y1, x2, y2 = box

    max_width = (
        x2 - x1
    ) * 0.82

    max_height = (
        y2 - y1
    ) * 0.70

    for size in range(
        48,
        27,
        -1
    ):

        font = get_font(
            size
        )

        bbox = draw.textbbox(
            (0, 0),
            text,
            font=font
        )

        width = (
            bbox[2] - bbox[0]
        )

        height = (
            bbox[3] - bbox[1]
        )

        if (
            width <= max_width
            and height <= max_height
        ):

            return font

    return get_font(28)


# =========================================================
# TEMPLATE
# =========================================================

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


def get_template_hash():

    if not TEMPLATE_FILE.exists():
        return ""

    sha = hashlib.sha256()

    with open(
        TEMPLATE_FILE,
        "rb"
    ) as file:

        while True:

            chunk = file.read(
                1024 * 1024
            )

            if not chunk:
                break

            sha.update(
                chunk
            )

    return sha.hexdigest()


# =========================================================
# DRAW
# =========================================================

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

    width = (
        bbox[2] - bbox[0]
    )

    height = (
        bbox[3] - bbox[1]
    )

    x = (
        x1
        + (
            x2 - x1 - width
        ) / 2
    )

    y = (
        y1
        + (
            y2 - y1 - height
        ) / 2
        - bbox[1]
    )

    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill
    )


# =========================================================
# CREATE BOARD
# =========================================================

def create_board(
    rate,
    products
):

    image = load_template()

    draw = ImageDraw.Draw(
        image
    )

    width, height = image.size

    # =====================================================
    # EXACT BOXES FOR THE SELECTED TEMPLATE
    # board_only_preview.png = 1086 x 1448
    # =====================================================

    original_width = 1086
    original_height = 1448

    base_boxes = [

        # 1 - OUNCE
        (
            487,
            531,
            865,
            663
        ),

        # 2 - DOLLAR
        (
            487,
            690,
            865,
            823
        ),

        # 3 - SHOT 995
        (
            487,
            850,
            865,
            982
        ),

        # 4 - NADER 999.9
        (
            487,
            1012,
            865,
            1145
        ),

        # 5 - MITHQAL 995
        (
            487,
            1174,
            865,
            1307
        )
    ]

    boxes = []

    for x1, y1, x2, y2 in base_boxes:

        boxes.append(
            (
                int(
                    x1
                    * width
                    / original_width
                ),

                int(
                    y1
                    * height
                    / original_height
                ),

                int(
                    x2
                    * width
                    / original_width
                ),

                int(
                    y2
                    * height
                    / original_height
                )
            )
        )

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

    for box, value in zip(
        boxes,
        values
    ):

        font = get_best_font(
            draw,
            value,
            box
        )

        draw_centered(
            draw,
            box,
            value,
            font
        )

    image.save(
        OUTPUT_FILE,
        "JPEG",
        quality=97,
        optimize=True,
        progressive=True
    )

    return OUTPUT_FILE


# =========================================================
# IRAN DATE / TIME
# =========================================================

def gregorian_to_jalali(
    gy,
    gm,
    gd
):

    g_days = [
        31, 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31
    ]

    j_days = [
        31, 31, 31, 31, 31, 31,
        30, 30, 30, 30, 30, 29
    ]

    gy -= 1600
    gm -= 1
    gd -= 1

    days = (
        365 * gy
        + (gy + 3) // 4
        - (gy + 99) // 100
        + (gy + 399) // 400
    )

    for i in range(gm):
        days += g_days[i]

    if (
        gm > 1
        and (
            (gy + 1600) % 4 == 0
            and (
                (gy + 1600) % 100 != 0
                or (gy + 1600) % 400 == 0
            )
        )
    ):
        days += 1

    days += gd
    days -= 79

    jy = 979 + 33 * (days // 12053)

    days %= 12053

    jy += 4 * (days // 1461)

    days %= 1461

    if days >= 366:

        jy += (
            days - 1
        ) // 365

        days = (
            days - 1
        ) % 365

    i = 0

    while (
        i < 11
        and days >= j_days[i]
    ):

        days -= j_days[i]

        i += 1

    return (
        jy,
        i + 1,
        days + 1
    )


def get_iran_datetime():

    return datetime.now(
        IRAN_TZ
    )


def get_iran_date():

    now = get_iran_datetime()

    jy, jm, jd = (
        gregorian_to_jalali(
            now.year,
            now.month,
            now.day
        )
    )

    return (
        f"{jy:04d}/"
        f"{jm:02d}/"
        f"{jd:02d}"
    )


def get_iran_time():

    return get_iran_datetime().strftime(
        "%H:%M"
    )


# =========================================================
# CAPTION
# =========================================================

def make_caption():

    date = get_iran_date()

    clock = get_iran_time()

    return (
        "\U0001f4c5 "
        "\u062a\u0627\u0631\u06cc\u062e: "
        f"{date}\n"

        "\U0001f550 "
        "\u0633\u0627\u0639\u062a: "
        f"{clock}\n\n"

        "\U0001f4de "
        f"{PHONE}\n\n"

        "\u2705 "
        "\u062e\u0631\u06cc\u062f \u0628\u0627\u0644\u0627\u06cc "
        "\u06f2 \u06a9\u06cc\u0644\u0648 "
        "\u062a\u0645\u0627\u0633 \u062a\u0644\u0641\u0646\u06cc "
        "\u062c\u0647\u062a \u0627\u0633\u062a\u0639\u0644\u0627\u0645 \u0646\u0631\u062e\n\n"

        "\U0001f539 "
        "\u062e\u0631\u06cc\u062f \u0648 \u0641\u0631\u0648\u0634 "
        "\u0627\u0646\u0648\u0627\u0639 \u0634\u0645\u0634\u200c\u0647\u0627\u06cc "
        "\u0645\u0639\u062a\u0628\u0631 "
        "(\u0642\u0627\u0646\u0648\u0646\u06cc)\n"

        "\U0001f539 "
        "\u062e\u0631\u06cc\u062f \u0645\u0633\u062a\u0639\u0645\u0644 \u0646\u0642\u0631\u0647\n"

        "\U0001f539 "
        "\u0646\u0631\u062e \u062e\u0631\u06cc\u062f "
        "\u0641\u0627\u06a9\u062a\u0648\u0631\u0647\u0627\u06cc "
        "\u0645\u062c\u0645\u0648\u0639\u0647 "
        "\u0647\u0645\u0627\u0646\u0646\u062f \u0647\u0645\u06cc\u0634\u0647 \u0647\u0633\u062a\n\n"

        "\U0001f4ac "
        "\u0628\u0631\u0627\u06cc \u062e\u0631\u06cc\u062f "
        "\u06cc\u0627 \u0647\u0631\u06af\u0648\u0646\u0647 \u0633\u0624\u0627\u0644:\n"

        f"{TELEGRAM_ID}"
    )


# =========================================================
# STATE
# =========================================================

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


# =========================================================
# TELEGRAM BOT CLIENT
# =========================================================

async def get_bot_client():

    if not API_ID:
        raise RuntimeError(
            "API_ID"
        )

    if not API_HASH:
        raise RuntimeError(
            "API_HASH"
        )

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN"
        )

    return TelegramClient(
        "publisher_bot",
        int(API_ID),
        API_HASH
    )


# =========================================================
# TARGET MESSAGE
# =========================================================

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


# =========================================================
# PUBLISH
# =========================================================

async def publish(
    client,
    rate,
    products
):

    target = TARGET_CHANNEL

    image = create_board(
        rate,
        products
    )

    caption = make_caption()

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

            "template":
                get_template_hash()
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


# =========================================================
# ONE UPDATE
# =========================================================

async def update_once(
    client
):

    telegram_html = (
        await asyncio.to_thread(
            get_source_page
        )
    )

    rate = parse_telegram_rate(
        telegram_html
    )

    if rate is None:

        raise RuntimeError(
            "Invalid ounce/dollar data"
        )

    website_html = (
        await asyncio.to_thread(
            get_website_page
        )
    )

    products = (
        parse_website_prices(
            website_html
        )
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

            "template":
                get_template_hash()
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
            "shot995=%s | nader=%s | mithqal=%s",
            rate["ounce"],
            rate["dollar_tehran"],
            products["shot_995"],
            products["nader_9999"],
            products["mithqal_995"]
        )

        return False

    await publish(
        client,
        rate,
        products
    )

    return True


# =========================================================
# MAIN LOOP
# =========================================================

async def main():

    if not TARGET_CHANNEL:

        raise RuntimeError(
            "TARGET_CHANNEL"
        )

    client = await get_bot_client()

    await client.start(
        bot_token=BOT_TOKEN
    )

    log.info(
        "YAZDANDOUST SILVER BOT STARTED"
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


# =========================================================
# RUN
# =========================================================

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
