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

START_STICKER = BASE / "start_trades.webp"
END_STICKER = BASE / "end_trades.webp"


# =========================================================
# ENVIRONMENT
# =========================================================

API_ID = os.getenv("API_ID", "").strip()
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "").strip()

SOURCE_CHANNEL = os.getenv(
    "SOURCE_CHANNEL",
    "tghsilver"
).strip().lstrip("@")

WEBSITE_URL = os.getenv(
    "WEBSITE_URL",
    "https://taghizadegan.com"
).strip()

# ---------------------------------------------------------
# Mashhad gold / coin public source
# ---------------------------------------------------------

MASHHAD_SOURCE_CHANNEL = os.getenv(
    "MASHHAD_SOURCE_CHANNEL",
    "taybadonline"
).strip().lstrip("@")


# =========================================================
# SETTINGS
# =========================================================

PHONE = "09152449600"

TELEGRAM_ID = "@MajidYazdandoust"

CHANNEL_LINK = "https://t.me/yazdandoustsilver"

IRAN_TZ = ZoneInfo("Asia/Tehran")

MITHQAL_GRAMS = 4.6083

COIN_IMAMI_WEIGHT = 8.133
COIN_FINENESS = 0.900

# قابل تنظیم در صورت نیاز
COIN_MINTING_FEE = 0


# =========================================================
# NEWS SETTINGS
# =========================================================

NEWS_ENABLED = True

NEWS_ECONOMIC_MAX_PER_DAY = 7

NEWS_WORLD_MAX_PER_DAY = 3

NEWS_TOTAL_MAX_PER_DAY = 10

NEWS_MIN_GAP_MINUTES = 120

NEWS_HISTORY_LIMIT = 200


# =========================================================
# NEWS SOURCES
# =========================================================

ECONOMIC_SOURCES = [

    "https://www.tasnimnews.ir/fa/service/79/"
    "%D9%BE%D9%88%D9%84-%D8%A7%D8%B1%D8%B2-%D8%A8%D8%A7%D9%86%DA%A9",

    "https://www.tasnimnews.ir/fa/service/1408/"
    "%D9%82%DB%8C%D9%85%D8%AA-%D8%B7%D9%84%D8%A7-%D8%B3%DA%A9%D9%87-%D9%88-%D8%A7%D8%B1%D8%B2",

]


WORLD_SOURCES = [

    "https://www.reuters.com/world/middle-east/",

    "https://www.reuters.com/world/us/",

]


ECONOMIC_KEYWORDS = [

    "طلا",
    "نقره",
    "اونس",
    "انس",
    "دلار",
    "ارز",
    "یورو",
    "سکه",
    "شمش",
    "بانک مرکزی",
    "مرکز مبادله",
    "تورم",
    "نرخ بهره",
    "فدرال رزرو",
    "بازار جهانی",
    "اقتصاد",
    "نفت",

]


WORLD_KEYWORDS = [

    "ترامپ",
    "Trump",
    "ایران",
    "Iran",
    "آمریکا",
    "United States",
    "اسرائیل",
    "Israel",
    "جنگ",
    "war",
    "حمله",
    "حملات",
    "strike",
    "strikes",
    "آتش بس",
    "ceasefire",
    "مذاکرات",
    "talks",
    "تحریم",
    "sanctions",
    "تنگه هرمز",
    "Hormuz",
    "خاورمیانه",
    "Middle East",

]


URGENT_KEYWORDS = [

    "فوری",
    "فوق العاده",
    "حمله",
    "حملات",
    "جنگ",
    "آتش بس",
    "ترامپ",
    "Trump",
    "Trump says",
    "breaking",
    "urgent",
    "strike",
    "strikes",

]


# =========================================================
# IMAGE COORDINATES
# =========================================================

NUMBER_BOXES = [

    # 1 - انس نقره
    (505, 585, 900, 665),

    # 2 - دلار تهران
    (505, 750, 900, 830),

    # 3 - ساچمه 995
    (505, 915, 900, 995),

    # 4 - شمش نادیر 999.9
    (505, 1075, 900, 1155),

    # 5 - مثقال نقره 995
    (505, 1235, 900, 1315),

]


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("YAZDANDOUST")


# =========================================================
# DIGIT HELPERS
# =========================================================

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ENGLISH_DIGITS = "0123456789"

DIGIT_TABLE = str.maketrans(
    PERSIAN_DIGITS + ARABIC_DIGITS,
    ENGLISH_DIGITS + ENGLISH_DIGITS
)


def normalize_digits(text):

    return (text or "").translate(DIGIT_TABLE)


def clean_text(text):

    text = normalize_digits(text)

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


def normalize_fa(text):

    text = clean_text(text)

    return (
        text
        .replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
        .strip()
    )


def integer_value(text):

    text = normalize_digits(text or "")

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

    text = normalize_digits(text or "")

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
# DATE / TIME
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

        g_day_no += g_days_in_month[i]

    if (

        gm2 > 1

        and

        (
            gy % 4 == 0
            and
            (
                gy % 100 != 0
                or
                gy % 400 == 0
            )
        )

    ):

        g_day_no += 1

    g_day_no += gd2

    j_day_no = g_day_no - 79

    j_np = j_day_no // 12053

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
        and
        j_day_no >= j_days_in_month[i]

    ):

        j_day_no -= j_days_in_month[i]

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
# HTTP
# =========================================================

def http_get(
    url,
    timeout=30
):

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

            "Cache-Control":
                "no-cache"

        },

        timeout=timeout

    )

    response.raise_for_status()

    return response.text


# =========================================================
# TELEGRAM SOURCE
# =========================================================

def public_source_url(
    channel,
    before=None
):

    url = (
        "https://t.me/s/"
        f"{channel}"
    )

    if before:

        url += (
            f"?before={int(before)}"
        )

    return url


def fetch_public_page(
    channel,
    before=None
):

    return http_get(

        public_source_url(
            channel,
            before
        ),

        timeout=30

    )


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
        key=lambda x: x[0],
        reverse=True
    )

    return result


# =========================================================
# SILVER RATE
# =========================================================

def parse_rate_message(
    text
):

    text = clean_text(text)

    compact = text.replace(
        " ",
        ""
    )

    if (
        "انس:" not in text
        and
        "انس :" not in text
    ):

        return None

    if "دلارتهران" not in compact:

        return None

    ounce_match = re.search(

        r"انس\s*:?\s*([\d,.]+)",

        text

    )

    if not ounce_match:

        return None

    dollar_match = re.search(

        r"دلار\s*تهران"
        r"\s*(?:حدود)?"
        r"\s*:?\s*"
        r"([\d,٬ ]+)",

        text

    )

    if not dollar_match:

        return None

    ounce = decimal_value(
        ounce_match.group(1)
    )

    tehran = integer_value(
        dollar_match.group(1)
    )

    if (
        ounce is None
        or
        tehran is None
    ):

        return None

    if not (
        20 <= ounce <= 150
    ):

        return None

    if not (
        50_000 <= tehran <= 2_000_000
    ):

        return None

    return {

        "ounce": ounce,

        "tehran": tehran

    }


def find_latest_public_rate():

    before = None

    seen = set()

    for page_number in range(
        1,
        31
    ):

        html = fetch_public_page(
            SOURCE_CHANNEL,
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

        for message_id, text in messages:

            rate = parse_rate_message(
                text
            )

            if rate:

                log.info(
                    "SOURCE RATE FOUND | %s/%s",
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
            x[0]
            for x in messages
        )

        if min_id in seen:

            break

        seen.add(
            min_id
        )

        before = min_id

    raise RuntimeError(
        "هیچ نرخ معتبر شامل انس و دلار تهران پیدا نشد."
    )


# =========================================================
# WEBSITE PRICES
# =========================================================

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


def parse_price_number(
    text
):

    text = normalize_digits(
        text or ""
    )

    text = (
        text
        .replace("٬", ",")
        .replace("٫", ".")
    )

    matches = re.findall(
        r"\d[\d,\.]*",
        text
    )

    values = []

    for item in matches:

        raw = item.replace(
            ",",
            ""
        )

        raw = raw.replace(
            ".",
            ""
        )

        if not raw:

            continue

        try:

            value = int(raw)

        except ValueError:

            continue

        if (
            1_000_000
            <= value
            <= 20_000_000_000
        ):

            values.append(
                value
            )

    if not values:

        return None

    return values[-1]


def find_product_card(
    soup,
    exact_title
):

    wanted = normalize_product_name(
        exact_title
    )

    title_nodes = soup.select(

        "h2.woocommerce-loop-product__title,"
        "h3.woocommerce-loop-product__title,"
        "h2,"
        "h3"

    )

    for title in title_nodes:

        title_text = normalize_product_name(

            title.get_text(
                " ",
                strip=True
            )

        )

        if title_text != wanted:

            continue

        card = title.find_parent(

            "li",

            class_=lambda c:
                c and
                "product" in c

        )

        if card:

            return card

        parent = title

        for _ in range(8):

            parent = parent.parent

            if parent is None:

                break

            classes = " ".join(

                parent.get(
                    "class",
                    []
                )

            )

            if "product" in classes:

                return parent

    return None


def get_current_price_from_card(
    card
):

    ins = card.select_one(
        ".price ins"
    )

    if ins:

        price = parse_price_number(

            ins.get_text(
                " ",
                strip=True
            )

        )

        if price:

            return price

    for selector in [

        ".woocommerce-Price-amount",

        ".price"

    ]:

        nodes = card.select(
            selector
        )

        for node in reversed(nodes):

            price = parse_price_number(

                node.get_text(
                    " ",
                    strip=True
                )

            )

            if price:

                return price

    return None


def get_website_prices_sync():

    html = http_get(
        WEBSITE_URL,
        timeout=30
    )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # -----------------------------------------------------
    # EXACT PRODUCT 1
    # -----------------------------------------------------

    shot_title = (
        "نقره ساچمه 1000 گرمی با عیار 995"
    )

    shot_card = find_product_card(
        soup,
        shot_title
    )

    if shot_card is None:

        raise RuntimeError(
            "محصول دقیق «نقره ساچمه 1000 گرمی با عیار 995» پیدا نشد."
        )

    shot_package = (
        get_current_price_from_card(
            shot_card
        )
    )

    if shot_package is None:

        raise RuntimeError(
            "قیمت ساچمه 1000 گرمی 995 پیدا نشد."
        )

    # -----------------------------------------------------
    # EXACT PRODUCT 2
    # -----------------------------------------------------

    nader_title = (
        "شمش 1000 گرمی 999.9 نادیر"
    )

    nader_card = find_product_card(
        soup,
        nader_title
    )

    if nader_card is None:

        raise RuntimeError(
            "محصول دقیق «شمش 1000 گرمی 999.9 نادیر» پیدا نشد."
        )

    nader_package = (
        get_current_price_from_card(
            nader_card
        )
    )

    if nader_package is None:

        raise RuntimeError(
            "قیمت شمش نادیر پیدا نشد."
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

    result = {

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
            )

    }

    log.info(
        "SHOT 995 / GRAM = %s",
        format_price(
            result["shot_995"]
        )
    )

    log.info(
        "NADER 999.9 / GRAM = %s",
        format_price(
            result["nader_9999"]
        )
    )

    log.info(
        "MITHQAL 995 = %s",
        format_price(
            result["mithqal_995"]
        )
    )

    return result


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

                "WEBSITE ATTEMPT %s/4 FAILED: %s",

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
# MASHHAD GOLD / COIN
# =========================================================

def parse_mashhad_market_message(
    text
):

    if not text:

        return None

    text = clean_text(
        text
    )

    compact = text.replace(
        " ",
        ""
    )

    # -----------------------------------------------------
    # Gold 18 in Mashhad
    # -----------------------------------------------------

    gold_patterns = [

        r"گرم\s*طلای\s*18\s*در\s*مشهد\s*:?\s*([\d,٬ ]+)",

        r"طلای\s*18\s*(?:عیار)?\s*در\s*مشهد\s*:?\s*([\d,٬ ]+)",

        r"طلای\s*18\s*مشهد\s*:?\s*([\d,٬ ]+)",

    ]

    gold = None

    for pattern in gold_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            gold = integer_value(
                match.group(1)
            )

            break

    if gold is None:

        return None

    # -----------------------------------------------------
    # Imam coin
    # -----------------------------------------------------

    coin_patterns = [

        r"سکه\s*امام(?:ی)?\s*:?\s*([\d,٬ ]+)",

        r"سکه\s*امامی\s*:?\s*([\d,٬ ]+)",

    ]

    coin = None

    for pattern in coin_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            coin = integer_value(
                match.group(1)
            )

            break

    if coin is None:

        return None

    # Values on public channels may be in تومان.
    # We normalize obvious small values.
    if gold < 1_000_000:

        gold *= 10

    if coin < 10_000_000:

        coin *= 10

    if not (
        1_000_000 <= gold <= 1_000_000_000
    ):

        return None

    if not (
        100_000_000 <= coin <= 10_000_000_000
    ):

        return None

    return {

        "gold_18_mashhad":
            int(gold),

        "coin_imami":
            int(coin)

    }


def find_latest_mashhad_market():

    before = None

    seen = set()

    for page_number in range(
        1,
        16
    ):

        try:

            html = fetch_public_page(

                MASHHAD_SOURCE_CHANNEL,

                before

            )

        except Exception as error:

            log.warning(

                "MASHHAD SOURCE ERROR: %s",

                error

            )

            return None

        messages = parse_public_messages(
            html
        )

        if not messages:

            break

        for message_id, text in messages:

            market = parse_mashhad_market_message(
                text
            )

            if market:

                market[
                    "source_message_id"
                ] = message_id

                log.info(

                    "MASHHAD MARKET FOUND | gold=%s | coin=%s",

                    market[
                        "gold_18_mashhad"
                    ],

                    market[
                        "coin_imami"
                    ]

                )

                return market

        min_id = min(
            x[0]
            for x in messages
        )

        if min_id in seen:

            break

        seen.add(
            min_id
        )

        before = min_id

    log.warning(
        "NO MASHHAD MARKET DATA FOUND"
    )

    return None


def calculate_coin_bubble(
    rate,
    coin_price
):

    intrinsic = (

        rate["ounce"]
        * rate["tehran"]
        / 31.1034768
        * COIN_FINENESS
        * COIN_IMAMI_WEIGHT

    )

    intrinsic += COIN_MINTING_FEE

    bubble = (
        coin_price
        - intrinsic
    )

    return {

        "intrinsic":
            int(round(intrinsic)),

        "bubble":
            int(round(bubble))

    }


async def get_mashhad_market():

    return await asyncio.to_thread(
        find_latest_mashhad_market
    )


# =========================================================
# PRICE SIGNATURE
# =========================================================

def make_price_signature(
    rate,
    products
):

    data = {

        "ounce":
            round(
                float(
                    rate["ounce"]
                ),
                4
            ),

        "tehran":
            int(
                rate["tehran"]
            ),

        "shot_995":
            int(
                products["shot_995"]
            ),

        "nader_9999":
            int(
                products["nader_9999"]
            ),

        "mithqal_995":
            int(
                products["mithqal_995"]
            )

    }

    return json.dumps(

        data,

        sort_keys=True,

        ensure_ascii=False

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
        "DejaVuSans.ttf"

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
    min_size=25
):

    x1, y1, x2, y2 = box

    available_width = (
        x2 - x1 - 30
    )

    available_height = (
        y2 - y1 - 10
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
            and
            height <= available_height

        ):

            return font

    return get_font(
        min_size
    )


def clear_number_box(
    draw,
    box
):

    x1, y1, x2, y2 = box

    draw.rectangle(

        (
            x1 + 8,
            y1 + 7,
            x2 - 8,
            y2 - 7
        ),

        fill=(7, 32, 24)

    )


def draw_centered(
    draw,
    box,
    text,
    font
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

        fill=(235, 213, 170)

    )


def create_board(
    rate,
    products
):

    if not TEMPLATE.exists():

        raise RuntimeError(
            "board_only_preview.png پیدا نشد."
        )

    image = Image.open(
        TEMPLATE
    ).convert(
        "RGB"
    )

    if image.size != (
        1086,
        1448
    ):

        raise RuntimeError(

            "ابعاد board_only_preview.png "
            "باید 1086x1448 باشد."

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
        )

    ]

    for box, value in zip(

        NUMBER_BOXES,

        values

    ):

        clear_number_box(
            draw,
            box
        )

        if len(value) >= 10:

            max_size = 38

        elif len(value) >= 8:

            max_size = 41

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
# CAPTIONS
# =========================================================

def channel_footer():

    return (
        "\n\n"
        "━━━━━━━━━━━━━━\n"
        "📲 عضویت در کانال یزدان‌دوست:\n"
        f"{CHANNEL_LINK}"
    )


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

        + channel_footer()

    )


# =========================================================
# NEWS
# =========================================================

def remove_bad_nodes(
    soup
):

    for selector in [

        "script",
        "style",
        "noscript",
        "iframe",
        "svg",
        "nav",
        "header",
        "footer",
        ".share",
        ".social",
        ".related",
        ".comments",
        ".comment",
        ".advertisement",
        ".ads",
        ".banner",
        ".tags",
        ".keywords",

    ]:

        for node in soup.select(
            selector
        ):

            node.decompose()


def extract_title(
    soup,
    fallback=""
):

    selectors = [

        "h1",

        "meta[property='og:title']",

        "meta[name='twitter:title']",

        "title"

    ]

    for selector in selectors:

        node = soup.select_one(
            selector
        )

        if not node:

            continue

        if node.name == "meta":

            value = node.get(
                "content",
                ""
            )

        else:

            value = node.get_text(
                " ",
                strip=True
            )

        value = normalize_fa(
            value
        )

        if len(value) >= 5:

            return value

    return normalize_fa(
        fallback
    )


def clean_article_paragraph(
    text
):

    text = normalize_fa(
        text
    )

    if not text:

        return ""

    bad_starts = [

        "انتهای پیام",
        "R101",
        "واژه های کاربردی",
        "لیگ ایران و جهان",
        "منبع:",
        "منبع :",
        "کد خبر:",

    ]

    for bad in bad_starts:

        if text.startswith(bad):

            return ""

    if len(text) < 25:

        return ""

    return text


def collect_paragraphs(
    node
):

    paragraphs = []

    if not node:

        return paragraphs

    for p in node.select(
        "p"
    ):

        text = clean_article_paragraph(

            p.get_text(
                " ",
                strip=True
            )

        )

        if not text:

            continue

        if text in paragraphs:

            continue

        paragraphs.append(
            text
        )

    return paragraphs


def extract_news_body(
    soup
):

    selectors = [

        "#news_content",
        "#newsContent",
        ".news-content",
        ".newsContent",
        ".article-content",
        ".articleContent",
        ".news-detail-content",
        ".news-detail",
        ".single-content",
        ".content-detail",
        "article",
        "main",

    ]

    best = []

    for selector in selectors:

        node = soup.select_one(
            selector
        )

        if not node:

            continue

        paragraphs = collect_paragraphs(
            node
        )

        if len(paragraphs) > len(
            best
        ):

            best = paragraphs

    if best:

        return best

    candidates = []

    for node in soup.select(
        "article, main, section, div"
    ):

        paragraphs = collect_paragraphs(
            node
        )

        if len(paragraphs) < 2:

            continue

        total_length = sum(
            len(x)
            for x in paragraphs
        )

        if total_length < 150:

            continue

        score = (
            len(paragraphs) * 100
            + total_length
        )

        candidates.append(
            (
                score,
                paragraphs
            )
        )

    if candidates:

        candidates.sort(
            key=lambda x: x[0],
            reverse=True
        )

        return candidates[0][1]

    for selector in [

        "meta[property='og:description']",

        "meta[name='description']",

        "meta[name='twitter:description']"

    ]:

        node = soup.select_one(
            selector
        )

        if node:

            value = normalize_fa(

                node.get(
                    "content",
                    ""
                )

            )

            if len(value) >= 100:

                return [
                    value
                ]

    return []


def build_news_text(
    paragraphs
):

    clean = []

    for paragraph in paragraphs:

        paragraph = clean_article_paragraph(
            paragraph
        )

        if not paragraph:

            continue

        if paragraph in clean:

            continue

        clean.append(
            paragraph
        )

    if not clean:

        return ""

    text = "\n\n".join(
        clean
    )

    if len(text) > 1500:

        text = (

            text[:1500]

            .rsplit(
                " ",
                1
            )[0]

            + "..."

        )

    return text.strip()


def is_valid_news_body(
    paragraphs
):

    if not paragraphs:

        return False

    total_length = sum(

        len(
            clean_article_paragraph(p)
        )

        for p in paragraphs

    )

    return (
        total_length >= 150
    )


def parse_news_index(
    html,
    base_url
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    result = []

    seen = set()

    for anchor in soup.select(
        "a[href]"
    ):

        href = anchor.get(
            "href",
            ""
        ).strip()

        if not href:

            continue

        from urllib.parse import urljoin

        url = urljoin(
            base_url,
            href
        )

        if url in seen:

            continue

        title = normalize_fa(

            anchor.get_text(
                " ",
                strip=True
            )

        )

        if len(title) < 20:

            continue

        if any(

            x in url.lower()

            for x in [

                "/service/",
                "/category/",
                "/tag/",
                "/search",
                "#"

            ]

        ):

            continue

        seen.add(
            url
        )

        result.append({

            "url":
                url,

            "title":
                title

        })

    return result


def fetch_news_index(
    source_url
):

    try:

        html = http_get(
            source_url,
            timeout=30
        )

    except Exception as error:

        log.warning(
            "NEWS INDEX ERROR | %s | %s",
            source_url,
            error
        )

        return []

    return parse_news_index(
        html,
        source_url
    )


def fetch_news_article(
    item
):

    try:

        html = http_get(
            item["url"],
            timeout=30
        )

    except Exception as error:

        log.warning(
            "NEWS ARTICLE ERROR | %s | %s",
            item["url"],
            error
        )

        return None

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    title = extract_title(

        soup,

        item.get(
            "title",
            ""
        )

    )

    remove_bad_nodes(
        soup
    )

    paragraphs = extract_news_body(
        soup
    )

    if not is_valid_news_body(
        paragraphs
    ):

        log.warning(
            "NEWS SKIPPED - NO REAL BODY | %s",
            item["url"]
        )

        return None

    body = build_news_text(
        paragraphs
    )

    if len(body) < 150:

        return None

    return {

        "url":
            item["url"],

        "title":
            title,

        "text":
            body

    }


def keyword_match(
    text,
    keywords
):

    text = normalize_fa(
        text
    ).lower()

    return any(

        keyword.lower() in text

        for keyword in keywords

    )


def get_candidate_from_sources(
    sources,
    keywords,
    history
):

    history = set(

        str(x)

        for x in history

    )

    all_items = []

    for source in sources:

        items = fetch_news_index(
            source
        )

        all_items.extend(
            items
        )

    seen_urls = set()

    for item in all_items:

        url = item.get(
            "url",
            ""
        )

        if not url:

            continue

        if url in seen_urls:

            continue

        seen_urls.add(
            url
        )

        if url in history:

            continue

        title = item.get(
            "title",
            ""
        )

        if not keyword_match(
            title,
            keywords
        ):

            continue

        article = fetch_news_article(
            item
        )

        if not article:

            continue

        combined = (

            article["title"]
            + " "
            + article["text"]

        )

        if not keyword_match(
            combined,
            keywords
        ):

            continue

        if len(
            article["text"]
        ) < 150:

            continue

        return article

    return None


async def get_economic_news(
    history
):

    return await asyncio.to_thread(

        get_candidate_from_sources,

        ECONOMIC_SOURCES,

        ECONOMIC_KEYWORDS,

        history

    )


async def get_world_news(
    history
):

    return await asyncio.to_thread(

        get_candidate_from_sources,

        WORLD_SOURCES,

        WORLD_KEYWORDS,

        history

    )


def is_urgent_news(
    article
):

    combined = (

        article.get(
            "title",
            ""
        )

        + " "

        + article.get(
            "text",
            ""
        )

    )

    return keyword_match(
        combined,
        URGENT_KEYWORDS
    )


def make_news_caption(
    article
):

    if is_urgent_news(
        article
    ):

        header = (
            "🚨 خبر فوری:"
        )

    else:

        header = (
            "📰 خبر مهم:"
        )

    return (

        f"{header}\n\n"

        f"{article['text']}\n\n"

        f"🕐 {iran_time_string()}"

        + channel_footer()

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

    except Exception as error:

        log.warning(
            "STATE READ ERROR: %s",
            error
        )

    return {}


def save_state(
    state
):

    temp = STATE.with_suffix(
        ".tmp"
    )

    temp.write_text(

        json.dumps(

            state,

            ensure_ascii=False,

            indent=2

        ),

        encoding="utf-8"

    )

    temp.replace(
        STATE
    )


def today_key():

    return iran_date_string()


def daily_key(
    name
):

    return (
        f"{today_key()}_{name}"
    )


# =========================================================
# DAILY MESSAGE CONTROL
# =========================================================

def should_send_daily(
    state,
    name
):

    return (
        state.get(
            daily_key(name)
        )
        !=
        True
    )


def mark_daily_sent(
    state,
    name
):

    state[
        daily_key(name)
    ] = True


# =========================================================
# NEWS DAILY CONTROL
# =========================================================

def reset_news_day_if_needed(
    state
):

    today = today_key()

    if state.get(
        "news_date"
    ) != today:

        state[
            "news_date"
        ] = today

        state[
            "economic_news_count"
        ] = 0

        state[
            "world_news_count"
        ] = 0

        state[
            "news_count"
        ] = 0

        state[
            "news_last_posted_at"
        ] = None

        save_state(
            state
        )


def news_is_due(
    state
):

    if not NEWS_ENABLED:

        return False

    reset_news_day_if_needed(
        state
    )

    total = int(

        state.get(
            "news_count",
            0
        )

        or 0

    )

    if total >= NEWS_TOTAL_MAX_PER_DAY:

        return False

    last = state.get(
        "news_last_posted_at"
    )

    if not last:

        return True

    try:

        last_dt = datetime.fromisoformat(
            last
        )

        if last_dt.tzinfo is None:

            last_dt = last_dt.replace(
                tzinfo=IRAN_TZ
            )

        elapsed = (

            iran_now()
            - last_dt.astimezone(
                IRAN_TZ
            )

        ).total_seconds() / 60

        return (
            elapsed >= NEWS_MIN_GAP_MINUTES
        )

    except Exception:

        return True


# =========================================================
# TELEGRAM SENDERS
# =========================================================

async def send_rate_post(
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
        "RATE POST CREATED | %s",
        sent.id
    )

    return int(
        sent.id
    )


async def send_text_post(
    client,
    target,
    text
):

    sent = await client.send_message(

        target,

        text,

        link_preview=False

    )

    log.info(
        "TEXT POST CREATED | %s",
        sent.id
    )

    return int(
        sent.id
    )


async def send_news_post(
    client,
    target,
    article
):

    if not article:

        return None

    if len(
        article.get(
            "text",
            ""
        ).strip()
    ) < 150:

        log.warning(
            "NEWS SEND BLOCKED - EMPTY BODY"
        )

        return None

    caption = make_news_caption(
        article
    )

    return await send_text_post(
        client,
        target,
        caption
    )


async def send_sticker(
    client,
    target,
    sticker_path
):

    if not sticker_path.exists():

        log.warning(
            "STICKER NOT FOUND | %s",
            sticker_path
        )

        return None

    sent = await client.send_file(

        target,

        str(sticker_path),

        force_document=False

    )

    log.info(
        "STICKER SENT | %s",
        sent.id
    )

    return int(
        sent.id
    )


# =========================================================
# MORNING MESSAGE
# =========================================================

def make_morning_message():

    return (

        "☀️ امروز را با امید شروع کن\n\n"

        "هر روز یک فرصت تازه‌ست "
        "برای ساختن یک قدم بهتر.\n"

        "آروم، هوشمند و با انرژی جلو برو؛ "
        "اتفاق‌های خوب در راه‌اند ✨\n\n"

        f"📅 {iran_date_string()}"

        + channel_footer()

    )


# =========================================================
# MASHHAD REPORT
# =========================================================

def make_mashhad_report(
    market,
    rate
):

    bubble = calculate_coin_bubble(

        rate,

        market[
            "coin_imami"
        ]

    )

    bubble_text = format_price(
        abs(
            bubble["bubble"]
        )
    )

    if bubble["bubble"] > 0:

        bubble_label = (
            f"🔴 حباب مثبت: {bubble_text} تومان"
        )

    elif bubble["bubble"] < 0:

        bubble_label = (
            f"🟢 حباب منفی: {bubble_text} تومان"
        )

    else:

        bubble_label = (
            "⚪ حباب: بدون حباب"
        )

    return (

        "🪙 گزارش بازار طلا و سکه مشهد\n"

        f"📅 {iran_date_string()}\n"
        f"🕐 {iran_time_string()}\n\n"

        "🥇 طلای ۱۸ عیار مشهد:\n"
        f"💰 {format_price(market['gold_18_mashhad'])} تومان\n\n"

        "🪙 سکه امامی:\n"
        f"💰 {format_price(market['coin_imami'])} تومان\n\n"

        f"{bubble_label}\n\n"

        "📌 ارزش ذاتی محاسبه‌شده سکه:\n"
        f"{format_price(bubble['intrinsic'])} تومان\n"

        + channel_footer()

    )


# =========================================================
# 24 HOUR REPORT
# =========================================================

def make_24h_report(
    rate,
    products,
    market
):

    lines = [

        "📊 گزارش ۲۴ ساعته بازار",

        f"📅 {iran_date_string()}",
        f"🕐 {iran_time_string()}",
        "",

        "🥇 طلای ۱۸ عیار مشهد:",
        (
            f"{format_price(market['gold_18_mashhad'])} تومان"
        ),

        "",

        "🪙 سکه امامی:",
        (
            f"{format_price(market['coin_imami'])} تومان"
        ),

        "",

        "🥈 ساچمه نقره ۹۹۵:",
        (
            f"{format_price(products['shot_995'])} تومان"
        ),

        "🧱 شمش نادیر ۹۹۹.۹:",
        (
            f"{format_price(products['nader_9999'])} تومان"
        ),

        "⚖️ مثقال نقره ۹۹۵:",
        (
            f"{format_price(products['mithqal_995'])} تومان"
        ),

        "",

        "🌍 انس نقره:",
        f"{rate['ounce']:.2f}",

        "💵 دلار تهران:",
        (
            f"{format_price(rate['tehran'])} تومان"
        ),

    ]

    bubble = calculate_coin_bubble(

        rate,

        market[
            "coin_imami"
        ]

    )

    lines.extend([

        "",

        "🎈 حباب سکه امامی:",

        (
            f"{format_price(abs(bubble['bubble']))} تومان "
            + (
                "(مثبت)"
                if bubble["bubble"] > 0
                else "(منفی)"
                if bubble["bubble"] < 0
                else "(بدون حباب)"
            )
        ),

    ])

    lines.append(
        channel_footer()
    )

    return "\n".join(
        lines
    )


# =========================================================
# NEWS STATE HELPERS
# =========================================================

def update_news_state(
    state,
    article,
    message_id
):

    if is_urgent_news(
        article
    ):

        state[
            "world_news_count"
        ] = (

            int(
                state.get(
                    "world_news_count",
                    0
                )
                or 0
            )
            + 1

        )

    else:

        state[
            "economic_news_count"
        ] = (

            int(
                state.get(
                    "economic_news_count",
                    0
                )
                or 0
            )
            + 1

        )

    state[
        "news_count"
    ] = (

        int(
            state.get(
                "news_count",
                0
            )
            or 0
        )
        + 1

    )

    state[
        "news_last_posted_at"
    ] = iran_now().isoformat()

    history = state.get(
        "news_history",
        []
    )

    if not isinstance(
        history,
        list
    ):

        history = []

    history.append(
        article["url"]
    )

    state[
        "news_history"
    ] = history[
        -NEWS_HISTORY_LIMIT:
    ]

    state[
        "last_news_message_id"
    ] = int(
        message_id
    )


# =========================================================
# MAIN
# =========================================================

async def main():

    missing = []

    if not API_ID:
        missing.append("API_ID")

    if not API_HASH:
        missing.append("API_HASH")

    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")

    if not TARGET_CHANNEL:
        missing.append("TARGET_CHANNEL")

    if missing:

        raise RuntimeError(

            "Secrets missing: "
            + ", ".join(missing)

        )

    try:

        api_id = int(
            API_ID
        )

    except ValueError:

        raise RuntimeError(
            "API_ID باید عدد باشد."
        )

    if not TEMPLATE.exists():

        raise RuntimeError(
            "board_only_preview.png پیدا نشد."
        )

    # =====================================================
    # LOAD STATE
    # =====================================================

    state = load_state()

    reset_news_day_if_needed(
        state
    )

    # =====================================================
    # CURRENT TIME
    # =====================================================

    now = iran_now()

    current_time = now.strftime(
        "%H:%M"
    )

    log.info(
        "IRAN TIME = %s",
        current_time
    )

    # =====================================================
    # FETCH RATE
    # =====================================================

    rate = None
    source_message_id = None

    try:

        rate, source_message_id = (

            await asyncio.to_thread(
                find_latest_public_rate
            )

        )

    except Exception as error:

        log.exception(
            "RATE FETCH FAILED: %s",
            error
        )

    # =====================================================
    # FETCH WEBSITE PRODUCTS
    # =====================================================

    products = None

    if rate is not None:

        try:

            products = (
                await get_website_prices()
            )

        except Exception as error:

            log.exception(
                "WEBSITE PRICE FAILED: %s",
                error
            )

    # =====================================================
    # FETCH MASHHAD MARKET
    # =====================================================

    mashhad_market = None

    if (
        current_time in [
            "11:00",
            "15:00",
            "18:00",
            "21:15"
        ]
        or
        should_send_daily(
            state,
            "mashhad_report_" + current_time
        )
    ):

        try:

            mashhad_market = (
                await get_mashhad_market()
            )

        except Exception as error:

            log.exception(
                "MASHHAD MARKET FAILED: %s",
                error
            )

    # =====================================================
    # TELEGRAM CONNECTION
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

    try:

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
        # PRICE POST - EVERY WORKFLOW RUN
        # =================================================

        if (
            rate is not None
            and
            products is not None
        ):

            image = create_board(

                rate,
                products

            )

            caption = make_caption()

            target_message_id = (

                await send_rate_post(

                    client,

                    target,

                    image,

                    caption

                )

            )

            state.update({

                "source_message_id":
                    int(
                        source_message_id
                    ),

                "target_message_id":
                    int(
                        target_message_id
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

                "shot_package":
                    products["shot_package"],

                "nader_package":
                    products["nader_package"],

                "price_signature":
                    make_price_signature(
                        rate,
                        products
                    ),

                "updated_at":
                    iran_now().isoformat()

            })

            save_state(
                state
            )

        # =================================================
        # 08:00 MORNING MESSAGE
        # =================================================

        if (

            current_time == "08:00"

            and

            should_send_daily(
                state,
                "morning"
            )

        ):

            await send_text_post(

                client,

                target,

                make_morning_message()

            )

            mark_daily_sent(
                state,
                "morning"
            )

            save_state(
                state
            )

        # =================================================
        # 10:30 START TRADES STICKER
        # =================================================

        if (

            current_time == "10:30"

            and

            should_send_daily(
                state,
                "start_trades"
            )

        ):

            message_id = await send_sticker(

                client,

                target,

                START_STICKER

            )

            if message_id:

                mark_daily_sent(
                    state,
                    "start_trades"
                )

                save_state(
                    state
                )

        # =================================================
        # MASHHAD REPORTS
        # 11:00 / 15:00 / 18:00
        # =================================================

        if current_time in [

            "11:00",
            "15:00",
            "18:00"

        ]:

            report_key = (

                "mashhad_"
                + current_time
            )

            if (

                should_send_daily(
                    state,
                    report_key
                )

                and

                mashhad_market is not None

                and

                rate is not None

            ):

                await send_text_post(

                    client,

                    target,

                    make_mashhad_report(

                        mashhad_market,

                        rate

                    )

                )

                mark_daily_sent(
                    state,
                    report_key
                )

                save_state(
                    state
                )

        # =================================================
        # NEWS
        # =================================================

        if news_is_due(
            state
        ):

            history = state.get(

                "news_history",

                []

            )

            if not isinstance(
                history,
                list
            ):

                history = []

            economic_count = int(

                state.get(
                    "economic_news_count",
                    0
                )
                or 0

            )

            world_count = int(

                state.get(
                    "world_news_count",
                    0
                )
                or 0

            )

            news_article = None

            # 7 economic first
            if economic_count < (

                NEWS_ECONOMIC_MAX_PER_DAY

            ):

                try:

                    news_article = (
                        await get_economic_news(
                            history
                        )
                    )

                except Exception as error:

                    log.exception(
                        "ECONOMIC NEWS FAILED: %s",
                        error
                    )

            # Then 3 world / war / Trump
            if (

                news_article is None

                and

                world_count
                <
                NEWS_WORLD_MAX_PER_DAY

            ):

                try:

                    news_article = (
                        await get_world_news(
                            history
                        )
                    )

                except Exception as error:

                    log.exception(
                        "WORLD NEWS FAILED: %s",
                        error
                    )

            if news_article:

                news_message_id = (

                    await send_news_post(

                        client,

                        target,

                        news_article

                    )

                )

                if news_message_id:

                    update_news_state(

                        state,

                        news_article,

                        news_message_id

                    )

                    save_state(
                        state
                    )

        # =================================================
        # 21:00 END TRADES STICKER
        # =================================================

        if (

            current_time == "21:00"

            and

            should_send_daily(
                state,
                "end_trades"
            )

        ):

            message_id = await send_sticker(

                client,

                target,

                END_STICKER

            )

            if message_id:

                mark_daily_sent(
                    state,
                    "end_trades"
                )

                save_state(
                    state
                )

        # =================================================
        # 21:15 DAILY 24H REPORT
        # =================================================

        if (

            current_time == "21:15"

            and

            should_send_daily(
                state,
                "24h_report"
            )

            and

            rate is not None

            and

            products is not None

            and

            mashhad_market is not None

        ):

            await send_text_post(

                client,

                target,

                make_24h_report(

                    rate,

                    products,

                    mashhad_market

                )

            )

            mark_daily_sent(
                state,
                "24h_report"
            )

            save_state(
                state
            )

    finally:

        await client.disconnect()

    log.info(
        "RUN COMPLETED SUCCESSFULLY"
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
            "STOPPED"
        )

    except Exception:

        log.exception(
            "FATAL ERROR"
        )

        raise
