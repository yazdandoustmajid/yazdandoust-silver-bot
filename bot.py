# -*- coding: utf-8 -*-

import asyncio
import json
import logging
import os
import re
from pathlib import Path

import cv2
import numpy as np
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from telethon import TelegramClient, events
from telethon.sessions import StringSession


# =========================================================
# YAZDANDOUST SILVER BOT
# =========================================================

BASE = Path(__file__).resolve().parent

TEMPLATE = BASE / "board_only_preview.png"
STATE = BASE / "state.json"
OUTPUT = BASE / "latest_price.jpg"


# =========================================================
# TELEGRAM CONFIG
# =========================================================

API_ID = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

SOURCE_SESSION = os.getenv(
    "SOURCE_SESSION",
    ""
).strip()

SOURCE_CHANNEL = os.getenv(
    "SOURCE_CHANNEL",
    "tghsilver"
).strip()

TARGET_CHANNEL = os.getenv(
    "TARGET_CHANNEL",
    ""
).strip()


# =========================================================
# WEBSITE
# =========================================================

WEBSITE_URL = os.getenv(
    "WEBSITE_URL",
    "https://taghizadegan.com"
).strip()


# =========================================================
# CONTACT
# =========================================================

PHONE = "09152449600"

TELEGRAM_ID = "@MajidYazdandoust"


# =========================================================
# CONSTANTS
# =========================================================

MITHQAL_GRAMS = 4.6083


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger(
    "YAZDANDOUST"
)


# =========================================================
# DIGITS
# =========================================================

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ENGLISH_DIGITS = "0123456789"

DIGIT_TABLE = str.maketrans(
    PERSIAN_DIGITS + ARABIC_DIGITS,
    ENGLISH_DIGITS + ENGLISH_DIGITS
)


def normalize_digits(text):

    return (
        text or ""
    ).translate(
        DIGIT_TABLE
    )


def clean_text(text):

    text = normalize_digits(
        text
    )

    text = (
        text
        .replace("٬", ",")
        .replace("٫", ".")
        .replace("\u200c", " ")
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def integer_value(text):

    text = normalize_digits(
        text
    )

    text = (
        text
        .replace(",", "")
        .replace("٬", "")
        .replace(" ", "")
    )

    text = re.sub(
        r"[^\d]",
        "",
        text
    )

    if not text:
        return None

    return int(text)


def decimal_value(text):

    text = normalize_digits(
        text
    )

    text = (
        text
        .replace(",", "")
        .replace("٬", "")
        .replace("٫", ".")
    )

    text = re.sub(
        r"[^\d.]",
        "",
        text
    )

    if not text:
        return None

    return float(text)


def format_price(value):

    return f"{int(round(value)):,}"


# =========================================================
# PARSE TGH TELEGRAM RATE
# =========================================================

def parse_rate_message(text):

    if not text:
        return None

    text = clean_text(
        text
    )

    compact = text.replace(
        " ",
        ""
    )

    # فقط پست‌های نرخ
    if "انس" not in compact:
        return None

    if "دلارتهران" not in compact:
        return None

    if (
        "جدولنرخ" not in compact
        and "نرخخریدفروش" not in compact
        and "نرخخریدفروش" not in compact
    ):
        return None

    # -----------------------------------------------------
    # OUNCE
    # -----------------------------------------------------

    ounce_match = re.search(
        r"انس\s*:?\s*(\d+(?:[.,]\d+)?)",
        text
    )

    if not ounce_match:
        return None

    ounce = decimal_value(
        ounce_match.group(1)
    )

    # -----------------------------------------------------
    # TEHRAN DOLLAR
    # -----------------------------------------------------

    tehran_match = re.search(
        r"دلار\s*تهران\s*"
        r"(?:حدود)?\s*:?\s*"
        r"([\d,]+)",
        text
    )

    if not tehran_match:
        return None

    tehran = integer_value(
        tehran_match.group(1)
    )

    # -----------------------------------------------------
    # DATE
    # -----------------------------------------------------

    date_match = re.search(
        r"تاریخ\s*:?\s*"
        r"(\d{4}/\d{1,2}/\d{1,2})",
        text
    )

    date = (
        date_match.group(1)
        if date_match
        else ""
    )

    # -----------------------------------------------------
    # TIME
    # -----------------------------------------------------

    time_match = re.search(
        r"ساعت\s*:?\s*"
        r"(\d{1,2}:\d{2})",
        text
    )

    time = (
        time_match.group(1)
        if time_match
        else ""
    )

    # -----------------------------------------------------
    # SANITY CHECK
    # -----------------------------------------------------

    if ounce is None:
        return None

    if tehran is None:
        return None

    if not 20 <= ounce <= 150:
        return None

    if not 50_000 <= tehran <= 2_000_000:
        return None

    return {
        "ounce": ounce,
        "tehran": tehran,
        "date": date,
        "time": time
    }


# =========================================================
# WEBSITE PRICE READER
# =========================================================

def find_product_price(
    page_text,
    product_names
):

    text = clean_text(
        page_text
    )

    for product_name in product_names:

        product_name = clean_text(
            product_name
        )

        position = text.find(
            product_name
        )

        if position < 0:
            continue

        area = text[
            position:
            position + 500
        ]

        matches = re.findall(
            r"([\d.]{6,})\s*تومان",
            area
        )

        for match in matches:

            value = integer_value(
                match
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


def get_website_prices():

    response = requests.get(
        WEBSITE_URL,
        headers={
            "User-Agent":
            "Mozilla/5.0 "
            "(iPhone; CPU iPhone OS 26_0 like Mac OS X) "
            "AppleWebKit/605.1.15 "
            "Version/26.0 Mobile/15E148 Safari/604.1"
        },
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    page_text = soup.get_text(
        " ",
        strip=True
    )

    # -----------------------------------------------------
    # SAچمه 995 - 1KG
    # -----------------------------------------------------

    shot_package = find_product_price(
        page_text,
        [
            "نقره ساچمه 1000 گرمی با عیار 995",
            "نقره ساچمه 1000 گرمی با عیار ۹۹۵",
            "نقره ساچمه ۱۰۰۰ گرمی با عیار 995",
            "نقره ساچمه ۱۰۰۰ گرمی با عیار ۹۹۵"
        ]
    )

    # -----------------------------------------------------
    # NADER 999.9 - 1KG
    # -----------------------------------------------------

    nader_package = find_product_price(
        page_text,
        [
            "شمش 1000 گرمی 999.9 نادیر",
            "شمش 1000 گرمی ۹۹۹.۹ نادیر",
            "شمش ۱۰۰۰ گرمی 999.9 نادیر",
            "شمش ۱۰۰۰ گرمی ۹۹۹.۹ نادیر"
        ]
    )

    if shot_package is None:

        raise RuntimeError(
            "قیمت ساچمه 995 در سایت تقی زادگان پیدا نشد."
        )

    if nader_package is None:

        raise RuntimeError(
            "قیمت شمش نادیر 999.9 در سایت تقی زادگان پیدا نشد."
        )

    # -----------------------------------------------------
    # PRICE PER GRAM
    # -----------------------------------------------------

    shot_995_per_gram = (
        shot_package / 1000
    )

    nader_9999_per_gram = (
        nader_package / 1000
    )

    # -----------------------------------------------------
    # MITHQAL 995
    # -----------------------------------------------------

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
                nader_9999_per_gram
            )
        ),

        "mithqal_995":
        int(
            mithqal_995
        )
    }


async def get_website_prices():

    last_error = None

    for attempt in range(
        4
    ):

        try:

            return await asyncio.to_thread(
                get_website_prices
            )

        except Exception as error:

            last_error = error

            log.warning(
                "Website attempt %s failed: %s",
                attempt + 1,
                error
            )

            await asyncio.sleep(
                5
            )

    raise RuntimeError(
        f"خطا در دریافت قیمت سایت: {last_error}"
    )


# =========================================================
# FONT
# =========================================================

def get_font(size):

    font_paths = [

        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSerif.ttf",

        "/usr/share/fonts/truetype/liberation2/"
        "LiberationSerif-Regular.ttf"
    ]

    for path in font_paths:

        if Path(path).exists():

            return ImageFont.truetype(
                path,
                size
            )

    return ImageFont.load_default()


# =========================================================
# CLEAN CURRENT TEMPLATE
# =========================================================

def load_clean_template():

    if not TEMPLATE.exists():

        raise FileNotFoundError(
            "فایل board_only_preview.png "
            "کنار bot.py پیدا نشد."
        )

    original = cv2.imread(
        str(TEMPLATE)
    )

    if original is None:

        raise RuntimeError(
            "خواندن فایل قالب امکان‌پذیر نیست."
        )

    height, width = (
        original.shape[:2]
    )

    if (
        width != 1086
        or height != 1035
    ):

        raise RuntimeError(
            "ابعاد board_only_preview.png "
            "باید دقیقاً 1086x1035 باشد."
        )

    cleaned = original.copy()

    # -----------------------------------------------------
    # محل عددهای نمونه در قالب فعلی
    # واحد USD و تومان دست‌نخورده می‌ماند.
    # -----------------------------------------------------

    number_boxes = [

        (570, 435, 850, 510),

        (570, 550, 850, 635),

        (570, 665, 850, 750),

        (570, 785, 850, 870),

        (570, 900, 850, 990)
    ]

    for (
        x1,
        y1,
        x2,
        y2
    ) in number_boxes:

        clean_band = original[
            y1:y2 + 1,
            565:585
        ]

        row_average = (
            clean_band
            .mean(
                axis=1,
                keepdims=True
            )
            .astype(
                np.float32
            )
        )

        row_average = cv2.GaussianBlur(
            row_average,
            (1, 15),
            0
        )

        fill = np.repeat(
            row_average,
            x2 - x1 + 1,
            axis=1
        )

        cleaned[
            y1:y2 + 1,
            x1:x2 + 1
        ] = fill.astype(
            np.uint8
        )

    return Image.fromarray(
        cv2.cvtColor(
            cleaned,
            cv2.COLOR_BGR2RGB
        )
    )


# =========================================================
# DRAW NUMBER
# =========================================================

def draw_centered(
    draw,
    box,
    text,
    font,
    color=(232, 207, 161)
):

    x1, y1, x2, y2 = box

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font
    )

    text_width = (
        bbox[2] - bbox[0]
    )

    text_height = (
        bbox[3] - bbox[1]
    )

    x = (
        x1
        + (
            x2 - x1 - text_width
        ) / 2
    )

    y = (
        y1
        + (
            y2 - y1 - text_height
        ) / 2
        - bbox[1]
    )

    draw.text(
        (x, y),
        text,
        font=font,
        fill=color
    )


# =========================================================
# CREATE FINAL BOARD
# =========================================================

def create_board(
    rate,
    products
):

    image = load_clean_template()

    draw = ImageDraw.Draw(
        image
    )

    # دقیقاً ۵ ردیف موجود در قالب
    number_boxes = [

        # انس
        (570, 435, 850, 510),

        # دلار تهران
        (570, 550, 850, 635),

        # ساچمه 995
        (570, 665, 850, 750),

        # شمش نادیر 999.9
        (570, 785, 850, 870),

        # مثقال 995
        (570, 900, 850, 990)
    ]

    values = [

        f"{rate['ounce']:.2f}",

        format_price(
            rate["tehran"]
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
        number_boxes,
        values
    ):

        if len(value) <= 7:
            size = 44
        else:
            size = 42

        draw_centered(
            draw,
            box,
            value,
            get_font(size)
        )

    image.save(
        OUTPUT,
        "JPEG",
        quality=97,
        optimize=True,
        progressive=True
    )

    return OUTPUT


# =========================================================
# CAPTION
# =========================================================

def make_caption(
    rate
):

    return (

        f"📅 تاریخ: {rate['date']}\n"

        f"🕐 ساعت: {rate['time']}\n\n"

        f"📞 {PHONE}\n\n"

        "✅ خرید بالای ۲ کیلو "
        "تماس تلفنی جهت استعلام نرخ\n\n"

        "🔹 خرید و فروش انواع "
        "شمش‌های معتبر (قانونی)\n"

        "🔹 خرید مستعمل نقره\n"

        "🔹 نرخ خرید فاکتورهای مجموعه "
        "همانند همیشه هست\n\n"

        "💬 برای خرید یا هرگونه سؤال:\n"

        f"{TELEGRAM_ID}"
    )


# =========================================================
# STATE
# =========================================================

def load_state():

    if not STATE.exists():
        return {}

    try:

        return json.loads(
            STATE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return {}


def save_state(state):

    STATE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# =========================================================
# FIND OLD TELEGRAM POST
# =========================================================

async def find_old_post(
    client,
    target
):

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
# SEND OR EDIT
# =========================================================

async def send_or_edit(
    client,
    target,
    image,
    caption
):

    state = load_state()

    message_id = state.get(
        "message_id"
    )

    # -----------------------------------------------------
    # EDIT SAVED MESSAGE
    # -----------------------------------------------------

    if message_id:

        try:

            await client.edit_message(
                target,
                int(message_id),
                file=str(image),
                caption=caption
            )

            return int(
                message_id
            )

        except Exception as error:

            log.warning(
                "Saved message edit failed: %s",
                error
            )

    # -----------------------------------------------------
    # SEARCH OLD MESSAGE
    # -----------------------------------------------------

    old = await find_old_post(
        client,
        target
    )

    if old:

        try:

            await client.edit_message(
                target,
                old.id,
                file=str(image),
                caption=caption
            )

            return int(
                old.id
            )

        except Exception as error:

            log.warning(
                "Old message edit failed: %s",
                error
            )

    # -----------------------------------------------------
    # SEND FIRST MESSAGE
    # -----------------------------------------------------

    sent = await client.send_file(
        target,
        str(image),
        caption=caption
    )

    return int(
        sent.id
    )


# =========================================================
# UPDATE LOCK
# =========================================================

UPDATE_LOCK = asyncio.Lock()


# =========================================================
# PROCESS RATE MESSAGE
# =========================================================

async def process_rate_message(
    message,
    bot_client,
    target
):

    rate = parse_rate_message(
        message.raw_text or ""
    )

    if not rate:
        return

    async with UPDATE_LOCK:

        log.info(
            "RATE FOUND | "
            "OUNCE=%s | "
            "TEHRAN=%s",
            rate["ounce"],
            rate["tehran"]
        )

        products = (
            await get_website_prices()
        )

        signature = json.dumps(
            {
                "ounce":
                    rate["ounce"],

                "tehran":
                    rate["tehran"],

                "shot_995":
                    products["shot_995"],

                "nader_9999":
                    products["nader_9999"],

                "mithqal_995":
                    products["mithqal_995"]
            },
            sort_keys=True,
            ensure_ascii=False
        )

        state = load_state()

        # اگر هیچ چیزی تغییر نکرده، دوباره پست نکن
        if (
            state.get("signature")
            == signature
        ):

            log.info(
                "NO PRICE CHANGE"
            )

            return

        image = create_board(
            rate,
            products
        )

        text = make_caption(
            rate
        )

        message_id = await send_or_edit(
            bot_client,
            target,
            image,
            text
        )

        save_state(
            {
                "signature":
                    signature,

                "message_id":
                    message_id,

                "source_message_id":
                    message.id,

                "date":
                    rate["date"],

                "time":
                    rate["time"]
            }
        )

        log.info(
            "YAZDANDOUST BOARD UPDATED"
        )


# =========================================================
# MAIN
# =========================================================

async def main():

    missing = []

    if not API_ID:
        missing.append(
            "API_ID"
        )

    if not API_HASH:
        missing.append(
            "API_HASH"
        )

    if not BOT_TOKEN:
        missing.append(
            "BOT_TOKEN"
        )

    if not TARGET_CHANNEL:
        missing.append(
            "TARGET_CHANNEL"
        )

    if missing:

        raise RuntimeError(
            "این متغیرها تنظیم نشده‌اند: "
            + ", ".join(missing)
        )

    if not TEMPLATE.exists():

        raise RuntimeError(
            "فایل board_only_preview.png "
            "باید کنار bot.py باشد."
        )

    try:

        api_id = int(
            API_ID
        )

    except ValueError:

        raise RuntimeError(
            "API_ID باید فقط عدد باشد."
        )

    # -----------------------------------------------------
    # SOURCE TELEGRAM ACCOUNT
    # -----------------------------------------------------

    if SOURCE_SESSION:

        source_client = TelegramClient(

            StringSession(
                SOURCE_SESSION
            ),

            api_id,
            API_HASH,

            sequential_updates=True,

            auto_reconnect=True,

            connection_retries=10,

            retry_delay=5
        )

    else:

        source_client = TelegramClient(

            str(
                BASE / "source"
            ),

            api_id,
            API_HASH,

            sequential_updates=True,

            auto_reconnect=True,

            connection_retries=10,

            retry_delay=5
        )

    # -----------------------------------------------------
    # BOT
    # -----------------------------------------------------

    bot_client = TelegramClient(

        str(
            BASE / "bot"
        ),

        api_id,
        API_HASH,

        sequential_updates=True,

        auto_reconnect=True,

        connection_retries=10,

        retry_delay=5
    )

    # -----------------------------------------------------
    # CONNECT
    # -----------------------------------------------------

    await source_client.start()

    await bot_client.start(
        bot_token=BOT_TOKEN
    )

    source_entity = (
        await source_client.get_entity(
            SOURCE_CHANNEL
        )
    )

    target_entity = (
        await bot_client.get_entity(
            TARGET_CHANNEL
        )
    )

    log.info(
        "SOURCE CONNECTED: @%s",
        SOURCE_CHANNEL
    )

    log.info(
        "TARGET CONNECTED: %s",
        TARGET_CHANNEL
    )

    # -----------------------------------------------------
    # INITIAL UPDATE
    # -----------------------------------------------------

    async for message in source_client.iter_messages(
        source_entity,
        limit=100
    ):

        if parse_rate_message(
            message.raw_text or ""
        ):

            try:

                await process_rate_message(
                    message,
                    bot_client,
                    target_entity
                )

            except Exception:

                log.exception(
                    "INITIAL UPDATE FAILED"
                )

            break

    # -----------------------------------------------------
    # NEW RATE
    # -----------------------------------------------------

    @source_client.on(
        events.NewMessage(
            chats=source_entity
        )
    )
    async def new_rate(event):

        try:

            await process_rate_message(
                event.message,
                bot_client,
                target_entity
            )

        except Exception:

            log.exception(
                "NEW MESSAGE ERROR"
            )

    # -----------------------------------------------------
    # EDITED RATE
    # -----------------------------------------------------

    @source_client.on(
        events.MessageEdited(
            chats=source_entity
        )
    )
    async def edited_rate(event):

        try:

            await process_rate_message(
                event.message,
                bot_client,
                target_entity
            )

        except Exception:

            log.exception(
                "EDITED MESSAGE ERROR"
            )

    log.info(
        "===================================="
    )

    log.info(
        "YAZDANDOUST SILVER BOT IS RUNNING"
    )

    log.info(
        "LIVE RATE UPDATE ENABLED"
    )

    log.info(
        "DOLLAR = TEHRAN ONLY"
    )

    log.info(
        "MASHHAD DOLLAR = NOT USED"
    )

    log.info(
        "===================================="
    )

    await source_client.run_until_disconnected()


# =========================================================
# START
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
