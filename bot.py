import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from telethon import TelegramClient


# =========================================================
# PATHS
# =========================================================

BASE = Path(__file__).resolve().parent

TEMPLATE = BASE / "board_only_preview.png"
OUTPUT = BASE / "latest_price.jpg"
STATE = BASE / "state.json"


# =========================================================
# ENVIRONMENT
# =========================================================

API_ID = os.getenv(
    "API_ID",
    ""
).strip()

API_HASH = os.getenv(
    "API_HASH",
    ""
).strip()

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    ""
).strip()

TARGET_CHANNEL = os.getenv(
    "TARGET_CHANNEL",
    ""
).strip()

SOURCE_CHANNEL = os.getenv(
    "SOURCE_CHANNEL",
    "tghsilver"
).strip().lstrip("@")

WEBSITE_URL = os.getenv(
    "WEBSITE_URL",
    "https://taghizadegan.com"
).strip()


# =========================================================
# FIXED SETTINGS
# =========================================================

PHONE = "09152449600"

TELEGRAM_ID = "@MajidYazdandoust"

IRAN_TZ = ZoneInfo(
    "Asia/Tehran"
)

MITHQAL_GRAMS = 4.6083


MIN_PRODUCT_PRICE = 1_000_000

MAX_PRODUCT_PRICE = 20_000_000_000


# =========================================================
# IMAGE SETTINGS
# =========================================================
#
# REAL TEMPLATE:
# 1086 x 1448
#
# The five boxes correspond to:
#
# 1. Ounce
# 2. Tehran Dollar
# 3. Shot 995
# 4. Nader 999.9
# 5. Mithqal 995
#
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
        text or ""
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
        text or ""
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
# IRAN DATE / TIME
# =========================================================

def iran_now():

    return datetime.now(
        IRAN_TZ
    )


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

        g_day_no += (
            g_days_in_month[i]
        )

    if (
        gm2 > 1
        and (
            gy % 4 == 0
            and (
                gy % 100 != 0
                or gy % 400 == 0
            )
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

        j_day_no -= (
            j_days_in_month[i]
        )

        i += 1

    jm = i + 1

    jd = j_day_no + 1

    return jy, jm, jd


def iran_date_string():

    now = iran_now()

    jy, jm, jd = gregorian_to_jalali(
        now.year,
        now.month,
        now.day
    )

    return (
        f"{jy:04d}/"
        f"{jm:02d}/"
        f"{jd:02d}"
    )


def iran_time_string():

    return iran_now().strftime(
        "%H:%M"
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

    if not any(
        marker in compact
        for marker in (
            "جدولنرخ",
            "نرخخریددفروش",
            "نرخ"
        )
    ):

        return None

    ounce_match = re.search(
        r"انس\s*:?\s*([\d,.]+)",
        text
    )

    if not ounce_match:

        return None

    tehran_match = re.search(
        r"دلار\s*تهران"
        r"\s*(?:حدود)?"
        r"\s*:?\s*"
        r"([\d,٬ ]+)",
        text
    )

    if not tehran_match:

        return None

    ounce = decimal_value(
        ounce_match.group(1)
    )

    tehran = integer_value(
        tehran_match.group(1)
    )

    if ounce is None:

        return None

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

        "ounce":
            ounce,

        "tehran":
            tehran

    }


# =========================================================
# PUBLIC TELEGRAM SOURCE
# =========================================================

def public_source_url(
    before=None
):

    url = (
        "https://t.me/s/"
        f"{SOURCE_CHANNEL}"
    )

    if before:

        url += (
            f"?before={int(before)}"
        )

    return url


def fetch_public_page(
    before=None
):

    url = public_source_url(
        before
    )

    response = requests.get(

        url,

        headers={

            "User-Agent":
                "Mozilla/5.0 "
                "(iPhone; CPU iPhone OS 26_0) "
                "AppleWebKit/605.1.15 "
                "Version/26.0 "
                "Mobile/15E148 "
                "Safari/604.1",

            "Accept":
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8",

            "Accept-Language":
                "fa-IR,fa;q=0.9,"
                "en-US;q=0.8,en;q=0.7",

        },

        timeout=30

    )

    response.raise_for_status()

    return response.text


def parse_public_messages(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    result = []

    for node in soup.select(
        "div.tgme_widget_message"
    ):

        data_post = node.get(
            "data-post",
            ""
        )

        try:

            message_id = int(
                data_post.rsplit(
                    "/",
                    1
                )[1]
            )

        except (
            ValueError,
            IndexError
        ):

            continue

        text_node = node.select_one(
            "div.tgme_widget_message_text"
        )

        if text_node:

            text = text_node.get_text(
                "\n",
                strip=True
            )

        else:

            text = ""

        result.append(
            (
                message_id,
                text
            )
        )

    result.sort(
        key=lambda item: item[0],
        reverse=True
    )

    return result


def find_latest_public_rate():

    before = None

    seen_min_ids = set()

    # Search backwards through public
    # Telegram pages.
    #
    # The first valid rate message found
    # is the newest valid rate message.

    for page_number in range(
        1,
        31
    ):

        html = fetch_public_page(
            before
        )

        messages = parse_public_messages(
            html
        )

        if not messages:

            break

        log.info(
            "PUBLIC SOURCE | page=%s | messages=%s",
            page_number,
            len(messages)
        )

        for (
            message_id,
            text
        ) in messages:

            rate = parse_rate_message(
                text
            )

            if rate:

                log.info(
                    "PUBLIC SOURCE RATE FOUND | %s/%s",
                    SOURCE_CHANNEL,
                    message_id
                )

                log.info(
                    "SOURCE OUNCE = %s",
                    rate["ounce"]
                )

                log.info(
                    "SOURCE TEHRAN USD = %s",
                    rate["tehran"]
                )

                return (
                    rate,
                    message_id
                )

        min_id = min(
            message_id
            for message_id, _ in messages
        )

        if min_id in seen_min_ids:

            break

        seen_min_ids.add(
            min_id
        )

        before = min_id

    raise RuntimeError(
        "هیچ پیام معتبر شامل "
        "انس و دلار تهران "
        "در کانال عمومی پیدا نشد."
    )


# =========================================================
# WEBSITE PRODUCTS
# =========================================================

PRODUCT_ALIASES = {

    "shot_995": [

        "نقره ساچمه 1000 گرمی با عیار 995",

        "نقره ساچمه ۱۰۰۰ گرمی با عیار ۹۹۵",

        "ساچمه 1000 گرمی 995",

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


def normalize_product_name(
    text
):

    text = clean_text(
        text
    )

    return (
        text
        .replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
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

        alias_normalized = (
            normalize_product_name(
                alias
            )
        )

        if (
            alias_normalized
            in normalized
        ):

            return True

        alias_compact = (
            alias_normalized
            .replace(" ", "")
        )

        if (
            alias_compact
            in compact
        ):

            return True

    return False


def extract_prices_from_text(
    text
):

    text = clean_text(
        text
    )

    values = []

    patterns = [

        r"([\d][\d.,٬ ]*)\s*تومان",

        r"تومان\s*([\d][\d.,٬ ]*)",

    ]

    for pattern in patterns:

        for match in re.findall(
            pattern,
            text
        ):

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

    candidates = soup.find_all(

        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "a",
            "li",
            "div",
            "article",
            "section"
        ]

    )

    for element in candidates:

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

        parent = element

        for _ in range(10):

            if parent is None:

                break

            parent_text = parent.get_text(
                " ",
                strip=True
            )

            if len(parent_text) > 1800:

                parent = parent.parent

                continue

            prices = extract_prices_from_text(
                parent_text
            )

            if prices:

                return prices[-1]

            parent = parent.parent

    return None


def get_website_prices_sync():

    response = requests.get(

        WEBSITE_URL,

        headers={

            "User-Agent":
                "Mozilla/5.0 "
                "(iPhone; CPU iPhone OS 26_0) "
                "AppleWebKit/605.1.15 "
                "Version/26.0 "
                "Mobile/15E148 "
                "Safari/604.1",

            "Accept":
                "text/html,"
                "application/xhtml+xml,"
                "application/xml;q=0.9,"
                "*/*;q=0.8",

            "Accept-Language":
                "fa-IR,fa;q=0.9,"
                "en-US;q=0.8,en;q=0.7",

        },

        timeout=30

    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    shot_package = (
        find_exact_product_price(
            soup,
            PRODUCT_ALIASES[
                "shot_995"
            ]
        )
    )

    nader_package = (
        find_exact_product_price(
            soup,
            PRODUCT_ALIASES[
                "nader_9999"
            ]
        )
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
            "قیمت دقیق ساچمه "
            "1000 گرمی عیار 995 "
            "در سایت تقی‌زادگان پیدا نشد."
        )

    if nader_package is None:

        raise RuntimeError(
            "قیمت دقیق شمش "
            "1000 گرمی 999.9 نادیر "
            "در سایت تقی‌زادگان پیدا نشد."
        )

    shot_995_per_gram = (
        shot_package / 1000
    )

    nader_9999_per_gram = (
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
                    nader_9999_per_gram
                )
            ),

        "mithqal_995":
            int(
                mithqal_995
            ),

        "shot_package":
            int(
                shot_package
            ),

        "nader_package":
            int(
                nader_package
            ),

    }


async def get_website_prices():

    last_error = None

    for attempt in range(
        1,
        5
    ):

        try:

            return await asyncio.to_thread(
                get_website_prices_sync
            )

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
# IMAGE
# =========================================================

def fit_font_to_box(

    draw,
    text,
    box,
    max_size=46,
    min_size=24,
    horizontal_padding=16

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

            width
            <= available_width

            and

            height
            <= available_height

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

        (
            int(x),
            int(y)
        ),

        text,

        font=font,

        fill=color

    )


def create_board(
    rate,
    products
):

    if not TEMPLATE.exists():

        raise RuntimeError(
            "فایل "
            "board_only_preview.png "
            "کنار bot.py پیدا نشد."
        )

    image = Image.open(
        TEMPLATE
    ).convert(
        "RGB"
    )

    # IMPORTANT:
    # Actual template dimensions are 1086 x 1448.

    if image.size != (
        1086,
        1448
    ):

        raise RuntimeError(

            "ابعاد "
            "board_only_preview.png "
            "باید دقیقاً "
            "1086x1448 باشد. "
            f"ابعاد فعلی: "
            f"{image.size[0]}x"
            f"{image.size[1]}"

        )

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
        ),

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
            min_size=25

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

    return (

        f"📅 تاریخ: "
        f"{iran_date_string()}\n"

        f"🕐 ساعت: "
        f"{iran_time_string()}\n\n"

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

        if not isinstance(
            data,
            dict
        ):

            return {}

        return data

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
# SEND NEW POST
# =========================================================

async def send_new_post(

    client,
    target,
    image,
    caption

):

    sent = await client.send_file(

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

    try:

        api_id = int(
            API_ID
        )

    except ValueError:

        raise RuntimeError(
            "API_ID باید فقط عدد باشد."
        )

    if not TEMPLATE.exists():

        raise RuntimeError(

            "فایل "
            "board_only_preview.png "
            "باید کنار bot.py باشد."

        )

    log.info(
        "===================================="
    )

    log.info(
        "YAZDANDOUST SILVER BOT"
    )

    log.info(
        "ONE SHOT RUN"
    )

    log.info(
        "PUBLIC SOURCE = https://t.me/s/%s",
        SOURCE_CHANNEL
    )

    log.info(
        "TARGET = %s",
        TARGET_CHANNEL
    )

    log.info(
        "WEBSITE = %s",
        WEBSITE_URL
    )

    log.info(
        "MODE = NEW POST FOR EVERY NEW SOURCE RATE MESSAGE"
    )

    log.info(
        "===================================="
    )

    # =====================================================
    # 1. FIND LATEST VALID SOURCE MESSAGE
    # =====================================================

    (
        rate,
        source_message_id
    ) = await asyncio.to_thread(

        find_latest_public_rate

    )

    # =====================================================
    # 2. LOAD STATE
    # =====================================================

    state = load_state()

    last_source_message_id = state.get(
        "source_message_id"
    )

    log.info(
        "LAST SOURCE MESSAGE ID = %s",
        last_source_message_id
    )

    log.info(
        "CURRENT SOURCE MESSAGE ID = %s",
        source_message_id
    )

    # =====================================================
    # 3. IMPORTANT:
    #
    # Only message ID matters.
    #
    # If source posted a NEW message:
    #     create a NEW target post.
    #
    # Even if prices are identical.
    #
    # If source message ID is unchanged:
    #     do nothing.
    #
    # =====================================================

    if (

        last_source_message_id is not None

        and

        int(
            last_source_message_id
        )
        == int(
            source_message_id
        )

    ):

        log.info(
            "SAME SOURCE MESSAGE - NOTHING TO POST"
        )

        return

    # =====================================================
    # 4. GET WEBSITE PRICES
    # =====================================================

    products = (
        await get_website_prices()
    )

    log.info(
        "SOURCE OUNCE = %s",
        rate["ounce"]
    )

    log.info(
        "SOURCE TEHRAN USD = %s",
        rate["tehran"]
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

    # =====================================================
    # 5. CREATE NEW BOARD
    # =====================================================

    image = create_board(

        rate,
        products

    )

    caption = make_caption()

    # =====================================================
    # 6. CONNECT BOT
    # =====================================================

    client = TelegramClient(

        str(
            BASE / "bot"
        ),

        api_id,

        API_HASH,

        sequential_updates=False,

        auto_reconnect=True,

        connection_retries=10,

        retry_delay=5,

        flood_sleep_threshold=60

    )

    message_id = None

    try:

        log.info(
            "Connecting Telegram bot..."
        )

        await client.start(

            bot_token=BOT_TOKEN

        )

        target = (
            await client.get_entity(
                TARGET_CHANNEL
            )
        )

        log.info(
            "TARGET CONNECTED = %s",
            TARGET_CHANNEL
        )

        # =================================================
        # 7. ALWAYS SEND A NEW POST
        # =================================================

        message_id = (
            await send_new_post(

                client,

                target,

                image,

                caption

            )
        )

    finally:

        await client.disconnect()

    # =====================================================
    # 8. SAVE SOURCE MESSAGE ID
    # =====================================================
    #
    # This does NOT edit or delete old Telegram posts.
    #
    # It only remembers which source message has already
    # been processed.
    #
    # =====================================================

    save_state(

        {

            "source_message_id":
                int(
                    source_message_id
                ),

            "target_message_id":
                int(
                    message_id
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
        "SOURCE MESSAGE PROCESSED"
    )

    log.info(
        "NEW TARGET POST CREATED"
    )

    log.info(
        "===================================="
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
