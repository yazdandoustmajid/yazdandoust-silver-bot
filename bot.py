import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from telethon import TelegramClient


# =========================================================
# PATHS
# =========================================================

BASE = Path(__file__).resolve().parent

TEMPLATE = BASE / "board_only_preview.png"
CLEAN_TEMPLATE = BASE / "template_blank_clean.png"
STATE = BASE / "state.json"
OUTPUT = BASE / "latest_price.jpg"


# =========================================================
# ENVIRONMENT
# =========================================================

API_ID = os.getenv("API_ID", "").strip()

API_HASH = os.getenv("API_HASH", "").strip()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

SOURCE_CHANNEL = os.getenv(
    "SOURCE_CHANNEL",
    "tghsilver"
).strip().lstrip("@")

TARGET_CHANNEL = os.getenv(
    "TARGET_CHANNEL",
    ""
).strip()

WEBSITE_URL = os.getenv(
    "WEBSITE_URL",
    "https://taghizadegan.com"
).strip()


# =========================================================
# BUSINESS SETTINGS
# =========================================================

PHONE = "09152449600"

TELEGRAM_ID = "@MajidYazdandoust"

IRAN_TZ = ZoneInfo(
    "Asia/Tehran"
)

MITHQAL_GRAMS = 4.6083

SHOT_995_WEIGHT_GRAMS = 1000

NADER_9999_WEIGHT_GRAMS = 1000


MIN_PRODUCT_PRICE = 1_000_000

MAX_PRODUCT_PRICE = 20_000_000_000


# =========================================================
# NUMBER BOXES
# =========================================================

NUMBER_BOXES = [
    (570, 435, 850, 510),
    (570, 550, 850, 635),
    (570, 665, 850, 750),
    (570, 785, 850, 870),
    (570, 900, 850, 990),
]


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
# DIGIT NORMALIZATION
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
        .replace("\ufeff", " ")
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

    try:

        return int(text)

    except ValueError:

        return None


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

    try:

        return float(text)

    except ValueError:

        return None


def format_price(value):

    return f"{int(round(value)):,}"


# =========================================================
# JALALI DATE
# =========================================================

def gregorian_to_jalali(
    gy,
    gm,
    gd
):

    g_days_in_month = [
        31, 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31
    ]

    j_days_in_month = [
        31, 31, 31, 31, 31, 31,
        30, 30, 30, 30, 30, 29
    ]

    gy2 = gy - 1600

    gm2 = gm - 1

    gd2 = gd - 1

    g_day_no = (
        365 * gy2
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
    )

    for i in range(gm2):

        g_day_no += g_days_in_month[i]

    if gm2 > 1 and (
        gy % 4 == 0
        and (
            gy % 100 != 0
            or gy % 400 == 0
        )
    ):

        g_day_no += 1

    g_day_no += gd2

    j_day_no = (
        g_day_no - 79
    )

    j_np = (
        j_day_no // 12053
    )

    j_day_no %= 12053

    jy = (
        979
        + 33 * j_np
        + 4 * (j_day_no // 1461)
    )

    j_day_no %= 1461

    if j_day_no >= 366:

        jy += (
            (j_day_no - 1) // 365
        )

        j_day_no = (
            (j_day_no - 1) % 365
        )

    i = 0

    while (
        i < 11
        and j_day_no >= j_days_in_month[i]
    ):

        j_day_no -= j_days_in_month[i]

        i += 1

    jm = i + 1

    jd = j_day_no + 1

    return jy, jm, jd


def iran_now():

    return datetime.now(
        IRAN_TZ
    )


def iran_date_string():

    now = iran_now()

    jy, jm, jd = gregorian_to_jalali(
        now.year,
        now.month,
        now.day
    )

    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def iran_time_string():

    return iran_now().strftime(
        "%H:%M"
    )


# =========================================================
# SOURCE CHANNEL
# PUBLIC TELEGRAM CHANNEL
# =========================================================

def get_public_channel_url():

    return (
        f"https://t.me/s/"
        f"{SOURCE_CHANNEL}"
    )


def get_public_channel_html():

    response = requests.get(
        get_public_channel_url(),
        headers={
            "User-Agent":
                "Mozilla/5.0 "
                "(iPhone; CPU iPhone OS 26_0 like Mac OS X) "
                "AppleWebKit/605.1.15 "
                "Version/26.0 Mobile/15E148 Safari/604.1",

            "Accept":
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8",

            "Accept-Language":
                "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
        },

        timeout=30
    )

    response.raise_for_status()

    return response.text


def get_public_channel_messages():

    html = get_public_channel_html()

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    messages = soup.select(
        ".tgme_widget_message"
    )

    return messages


def find_latest_public_rate():

    messages = get_public_channel_messages()

    if not messages:

        raise RuntimeError(
            "هیچ پیامی از کانال عمومی تلگرام پیدا نشد."
        )

    log.info(
        "PUBLIC SOURCE | %s messages found",
        len(messages)
    )

    for message in reversed(messages):

        text_element = message.select_one(
            ".tgme_widget_message_text"
        )

        if not text_element:

            continue

        text = text_element.get_text(
            "\n",
            strip=True
        )

        rate = parse_rate_message(
            text
        )

        if rate:

            data_post = message.get(
                "data-post",
                ""
            )

            log.info(
                "PUBLIC SOURCE RATE FOUND | %s",
                data_post
            )

            return {
                "text": text,
                "rate": rate,
                "data_post": data_post
            }

    raise RuntimeError(
        "در آخرین پیام‌های کانال عمومی، "
        "هیچ نرخ معتبر شامل انس و دلار تهران پیدا نشد."
    )


# =========================================================
# SOURCE RATE PARSER
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

    if "انس" not in compact:

        return None

    if "دلارتهران" not in compact:

        return None

    ounce_match = re.search(
        r"انس\s*:?\s*([\d,.]+)",
        text
    )

    if not ounce_match:

        return None

    ounce = decimal_value(
        ounce_match.group(1)
    )

    if ounce is None:

        return None

    tehran_patterns = [

        r"دلار\s*تهران"
        r"\s*(?:حدود)?"
        r"\s*:?\s*"
        r"([\d,٬ ]+)",

        r"دلار\s*تهران"
        r"\s*"
        r"([\d,٬ ]+)",

    ]

    tehran = None

    for pattern in tehran_patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            tehran = integer_value(
                match.group(1)
            )

            if tehran is not None:

                break

    if tehran is None:

        return None

    if not 20 <= ounce <= 150:

        log.warning(
            "Invalid ounce: %s",
            ounce
        )

        return None

    if not 50_000 <= tehran <= 2_000_000:

        log.warning(
            "Invalid Tehran dollar: %s",
            tehran
        )

        return None

    return {
        "ounce": ounce,
        "tehran": tehran
    }


# =========================================================
# WEBSITE PRODUCTS
# =========================================================

PRODUCT_ALIASES = {

    "shot_995": [

        "نقره ساچمه 1000 گرمی با عیار 995",

        "نقره ساچمه 1000 گرمی با عیار ۹۹۵",

        "نقره ساچمه ۱۰۰۰ گرمی با عیار 995",

        "نقره ساچمه ۱۰۰۰ گرمی با عیار ۹۹۵",

        "ساچمه 1000 گرمی 995",

        "ساچمه 1000 گرمی ۹۹۵",

        "ساچمه ۱۰۰۰ گرمی 995",

        "ساچمه ۱۰۰۰ گرمی ۹۹۵",

    ],

    "nader_9999": [

        "شمش 1000 گرمی 999.9 نادیر",

        "شمش 1000 گرمی ۹۹۹.۹ نادیر",

        "شمش ۱۰۰۰ گرمی 999.9 نادیر",

        "شمش ۱۰۰۰ گرمی ۹۹۹.۹ نادیر",

        "شمش 1000 گرمی نادیر",

        "شمش ۱۰۰۰ گرمی نادیر",

    ],
}


def normalize_product_name(text):

    text = clean_text(
        text
    )

    return (
        text
        .replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
        .replace("‌", " ")
        .strip()
    )


def product_name_matches(
    text,
    aliases
):

    normalized = normalize_product_name(
        text
    )

    compact = normalized.replace(
        " ",
        ""
    )

    for alias in aliases:

        alias_normalized = normalize_product_name(
            alias
        )

        if alias_normalized in normalized:

            return True

        alias_compact = (
            alias_normalized
            .replace(" ", "")
        )

        if alias_compact in compact:

            return True

    return False


def extract_prices_from_text(text):

    text = clean_text(
        text
    )

    patterns = [

        r"([\d][\d.,٬ ]*)\s*تومان",

        r"تومان\s*([\d][\d.,٬ ]*)",

    ]

    values = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            text
        )

        for match in matches:

            value = integer_value(
                match
            )

            if value is None:

                continue

            if (
                MIN_PRODUCT_PRICE
                <= value
                <= MAX_PRODUCT_PRICE
            ):

                if value not in values:

                    values.append(
                        value
                    )

    return values


def find_exact_product_price(
    soup,
    aliases
):

    # -----------------------------------------------------
    # First: look for elements containing exact product name
    # -----------------------------------------------------

    elements = soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "a",
            "article",
            "li"
        ]
    )

    for element in elements:

        own_text = element.get_text(
            " ",
            strip=True
        )

        if not own_text:

            continue

        if not product_name_matches(
            own_text,
            aliases
        ):

            continue

        # -------------------------------------------------
        # Search nearby parent containers
        # -------------------------------------------------

        parent = element

        for _ in range(6):

            if parent is None:

                break

            parent_text = parent.get_text(
                " ",
                strip=True
            )

            if (
                0
                < len(parent_text)
                <= 1500
            ):

                prices = extract_prices_from_text(
                    parent_text
                )

                if prices:

                    # Prefer the first valid price
                    # near the exact product.
                    return prices[0]

            parent = parent.parent

    return None


def get_website_prices_sync():

    response = requests.get(
        WEBSITE_URL,
        headers={
            "User-Agent":
                "Mozilla/5.0 "
                "(iPhone; CPU iPhone OS 26_0 like Mac OS X) "
                "AppleWebKit/605.1.15 "
                "Version/26.0 Mobile/15E148 Safari/604.1",

            "Accept":
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8",

            "Accept-Language":
                "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
        },

        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    shot_package = find_exact_product_price(
        soup,
        PRODUCT_ALIASES["shot_995"]
    )

    nader_package = find_exact_product_price(
        soup,
        PRODUCT_ALIASES["nader_9999"]
    )

    log.info(
        "WEBSITE | Shot 995 / 1kg = %s",
        shot_package
    )

    log.info(
        "WEBSITE | Nader 999.9 / 1kg = %s",
        nader_package
    )

    if shot_package is None:

        raise RuntimeError(
            "قیمت دقیق ساچمه 1000 گرمی عیار 995 "
            "در سایت تقی‌زادگان پیدا نشد."
        )

    if nader_package is None:

        raise RuntimeError(
            "قیمت دقیق شمش 1000 گرمی 999.9 نادیر "
            "در سایت تقی‌زادگان پیدا نشد."
        )

    shot_995_per_gram = (
        shot_package
        / SHOT_995_WEIGHT_GRAMS
    )

    nader_9999_per_gram = (
        nader_package
        / NADER_9999_WEIGHT_GRAMS
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
                nader_9999_per_gram
            )
        ),

        "mithqal_995": int(
            mithqal_995
        ),

        "shot_package": int(
            shot_package
        ),

        "nader_package": int(
            nader_package
        )
    }


async def get_website_prices():

    last_error = None

    for attempt in range(1, 5):

        try:

            result = await asyncio.to_thread(
                get_website_prices_sync
            )

            return result

        except Exception as error:

            last_error = error

            log.warning(
                "Website attempt %s/4 failed: %s",
                attempt,
                error
            )

            if attempt < 4:

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
        "DejaVuSans-Bold.ttf",

        "/usr/share/fonts/truetype/liberation2/"
        "LiberationSans-Bold.ttf",

        "/usr/share/fonts/truetype/dejavu/"
        "DejaVuSans.ttf",

    ]

    for path in font_paths:

        if Path(path).exists():

            return ImageFont.truetype(
                path,
                size
            )

    return ImageFont.load_default()


# =========================================================
# TEMPLATE
# =========================================================

def load_clean_template():

    if CLEAN_TEMPLATE.exists():

        image = Image.open(
            CLEAN_TEMPLATE
        ).convert(
            "RGB"
        )

        if image.size != (
            1086,
            1035
        ):

            raise RuntimeError(
                "ابعاد template_blank_clean.png "
                "باید دقیقاً 1086x1035 باشد."
            )

        return image

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
            "خواندن board_only_preview.png "
            "امکان‌پذیر نیست."
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

    for (
        x1,
        y1,
        x2,
        y2
    ) in NUMBER_BOXES:

        pad = 12

        sx1 = max(
            0,
            x1 - pad
        )

        sx2 = min(
            width,
            x2 + pad + 1
        )

        sy1 = max(
            0,
            y1
        )

        sy2 = min(
            height,
            y2 + 1
        )

        source = original[
            sy1:sy2,
            sx1:sx2
        ]

        mask = np.zeros(
            source.shape[:2],
            dtype=np.uint8
        )

        mx1 = x1 - sx1

        mx2 = x2 - sx1

        my1 = 2

        my2 = source.shape[0] - 2

        cv2.rectangle(
            mask,
            (mx1, my1),
            (mx2, my2),
            255,
            -1
        )

        repaired = cv2.inpaint(
            source,
            mask,
            5,
            cv2.INPAINT_TELEA
        )

        cleaned[
            sy1:sy2,
            sx1:sx2
        ] = repaired

    return Image.fromarray(
        cv2.cvtColor(
            cleaned,
            cv2.COLOR_BGR2RGB
        )
    )


def fit_font_to_box(
    draw,
    text,
    box,
    max_size=46,
    min_size=24,
    horizontal_padding=18
):

    x1, y1, x2, y2 = box

    available_width = (
        x2
        - x1
        - horizontal_padding * 2
    )

    available_height = (
        y2
        - y1
        - 8
    )

    for size in range(
        max_size,
        min_size - 1,
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
            bbox[2]
            - bbox[0]
        )

        height = (
            bbox[3]
            - bbox[1]
        )

        if (
            width <= available_width
            and height <= available_height
        ):

            return font

    return get_font(
        min_size
    )


def draw_centered(
    draw,
    box,
    text,
    font,
    color=(235, 213, 170)
):

    x1, y1, x2, y2 = box

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font
    )

    text_width = (
        bbox[2]
        - bbox[0]
    )

    text_height = (
        bbox[3]
        - bbox[1]
    )

    x = (
        x1
        + (
            x2
            - x1
            - text_width
        ) / 2
        - bbox[0]
    )

    y = (
        y1
        + (
            y2
            - y1
            - text_height
        ) / 2
        - bbox[1]
    )

    draw.text(
        (int(x), int(y)),
        text,
        font=font,
        fill=color
    )


def create_board(
    rate,
    products
):

    image = load_clean_template()

    draw = ImageDraw.Draw(
        image
    )

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
        NUMBER_BOXES,
        values
    ):

        if "." in value:

            max_size = 43

        elif len(value) >= 10:

            max_size = 39

        elif len(value) >= 8:

            max_size = 42

        else:

            max_size = 46

        font = fit_font_to_box(
            draw,
            value,
            box,
            max_size=max_size,
            min_size=25,
            horizontal_padding=16
        )

        draw_centered(
            draw,
            box,
            value,
            font
        )

    image.save(
        OUTPUT,
        "JPEG",
        quality=98,
        optimize=True,
        progressive=True,
        subsampling=0
    )

    return OUTPUT


# =========================================================
# CAPTION
# =========================================================

def make_caption():

    date = iran_date_string()

    time = iran_time_string()

    return (
        f"📅 تاریخ: {date}\n"
        f"🕐 ساعت: {time}\n\n"
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

        data = json.loads(
            STATE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(
            data,
            dict
        ):

            return data

        return {}

    except Exception as error:

        log.warning(
            "Could not read state.json: %s",
            error
        )

        return {}


def save_state(state):

    temporary = STATE.with_suffix(
        ".tmp"
    )

    temporary.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temporary.replace(
        STATE
    )


# =========================================================
# TARGET POST
# =========================================================

async def send_or_edit(
    bot_client,
    target,
    image,
    caption
):

    state = load_state()

    message_id = state.get(
        "message_id"
    )

    if message_id:

        try:

            await bot_client.edit_message(
                target,
                int(message_id),
                file=str(image),
                caption=caption
            )

            log.info(
                "TARGET POST EDITED | message_id=%s",
                message_id
            )

            return int(
                message_id
            )

        except Exception as error:

            log.warning(
                "Saved target message could not be edited: %s",
                error
            )

    sent = await bot_client.send_file(
        target,
        str(image),
        caption=caption
    )

    log.info(
        "NEW TARGET POST SENT | message_id=%s",
        sent.id
    )

    return int(
        sent.id
    )


# =========================================================
# MAIN PROCESS
# =========================================================

async def process_update(
    bot_client,
    target
):

    log.info(
        "===================================="
    )

    log.info(
        "STARTING PRICE UPDATE"
    )

    # -----------------------------------------------------
    # PUBLIC TELEGRAM SOURCE
    # -----------------------------------------------------

    source = await asyncio.to_thread(
        find_latest_public_rate
    )

    rate = source["rate"]

    log.info(
        "SOURCE CHANNEL = @%s",
        SOURCE_CHANNEL
    )

    log.info(
        "SOURCE OUNCE = %s",
        rate["ounce"]
    )

    log.info(
        "SOURCE TEHRAN USD = %s",
        rate["tehran"]
    )

    # -----------------------------------------------------
    # WEBSITE
    # -----------------------------------------------------

    products = (
        await get_website_prices()
    )

    log.info(
        "SHOT 995 / GRAM = %s",
        products["shot_995"]
    )

    log.info(
        "NADER 999.9 / GRAM = %s",
        products["nader_9999"]
    )

    log.info(
        "MITHQAL 995 = %s",
        products["mithqal_995"]
    )

    # -----------------------------------------------------
    # SIGNATURE
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # NO CHANGE
    # -----------------------------------------------------

    if (
        state.get("signature")
        == signature
    ):

        log.info(
            "NO PRICE CHANGE - NOTHING TO POST"
        )

        return

    # -----------------------------------------------------
    # CREATE IMAGE
    # -----------------------------------------------------

    image = create_board(
        rate,
        products
    )

    caption = make_caption()

    # -----------------------------------------------------
    # SEND / EDIT
    # -----------------------------------------------------

    message_id = await send_or_edit(
        bot_client,
        target,
        image,
        caption
    )

    # -----------------------------------------------------
    # SAVE STATE
    # -----------------------------------------------------

    save_state(
        {

            "signature":
                signature,

            "message_id":
                message_id,

            "source_channel":
                SOURCE_CHANNEL,

            "source_post":
                source.get(
                    "data_post",
                    ""
                ),

            "ounce":
                rate["ounce"],

            "tehran":
                rate["tehran"],

            "shot_995":
                products["shot_995"],

            "nader_9999":
                products["nader_9999"],

            "mithqal_995":
                products["mithqal_995"],

            "date":
                iran_date_string(),

            "time":
                iran_time_string(),

            "updated_at":
                iran_now().isoformat()
        }
    )

    log.info(
        "YAZDANDOUST BOARD UPDATED SUCCESSFULLY"
    )

    log.info(
        "===================================="
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

    if not SOURCE_CHANNEL:

        raise RuntimeError(
            "SOURCE_CHANNEL خالی است."
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
    # BOT CLIENT ONLY
    # -----------------------------------------------------

    bot_client = TelegramClient(
        str(
            BASE / "bot"
        ),

        api_id,

        API_HASH,

        sequential_updates=False,

        auto_reconnect=True,

        connection_retries=5,

        retry_delay=5,

        flood_sleep_threshold=60
    )

    try:

        # -------------------------------------------------
        # CONNECT BOT
        # -------------------------------------------------

        log.info(
            "Connecting Telegram bot..."
        )

        await bot_client.start(
            bot_token=BOT_TOKEN
        )

        log.info(
            "Telegram bot connected."
        )

        # -------------------------------------------------
        # TARGET
        # -------------------------------------------------

        target_entity = (
            await bot_client.get_entity(
                TARGET_CHANNEL
            )
        )

        log.info(
            "TARGET CONNECTED = %s",
            TARGET_CHANNEL
        )

        # -------------------------------------------------
        # PUBLIC SOURCE TEST
        # -------------------------------------------------

        log.info(
            "PUBLIC SOURCE = https://t.me/s/%s",
            SOURCE_CHANNEL
        )

        # -------------------------------------------------
        # PROCESS ONE UPDATE
        # -------------------------------------------------

        await process_update(
            bot_client,
            target_entity
        )

    finally:

        if bot_client.is_connected():

            await bot_client.disconnect()

        log.info(
            "Bot disconnected."
        )


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

        raise
