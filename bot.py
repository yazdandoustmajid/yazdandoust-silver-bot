import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
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


# =========================================================
# GENERAL SETTINGS
# =========================================================

PHONE = "09152449600"
TELEGRAM_ID = "@MajidYazdandoust"

IRAN_TZ = ZoneInfo("Asia/Tehran")

MITHQAL_GRAMS = 4.6083


# =========================================================
# IMAGE COORDINATES
# TEMPLATE MUST BE 1086 x 1448
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
# NEWS SETTINGS
# =========================================================

NEWS_ENABLED = True

# 7 economic / market news per day
NEWS_ECONOMIC_MAX_PER_DAY = 7

# 3 important war / geopolitical / Trump news per day
NEWS_WORLD_MAX_PER_DAY = 3

# Total maximum
NEWS_TOTAL_MAX_PER_DAY = 10

# Minimum time between news posts
NEWS_MIN_GAP_MINUTES = 120

# Number of old URLs kept in state
NEWS_HISTORY_LIMIT = 150


# =========================================================
# NEWS SOURCES
# =========================================================

# Economic / Iranian market sources
ECONOMIC_SOURCES = [

    "https://www.tasnimnews.ir/fa/service/79/%D9%BE%D9%88%D9%84-%D8%A7%D8%B1%D8%B2-%D8%A8%D8%A7%D9%86%DA%A9",

    "https://www.tasnimnews.ir/fa/service/1408/%D9%82%DB%8C%D9%85%D8%AA-%D8%B7%D9%84%D8%A7-%D8%B3%DA%A9%D9%87-%D9%88-%D8%A7%D8%B1%D8%B2",

]


# International / geopolitical source
WORLD_SOURCES = [

    "https://www.reuters.com/world/middle-east/",

    "https://www.reuters.com/world/us/",

]


# =========================================================
# KEYWORDS
# =========================================================

ECONOMIC_KEYWORDS = [

    "طلا",
    "طلای جهانی",
    "اونس",
    "انس جهانی",

    "نقره",
    "قیمت نقره",

    "دلار",
    "ارز",
    "قیمت دلار",

    "سکه",
    "شمش",

    "مرکز مبادله",
    "بانک مرکزی",

    "تورم",
    "نرخ بهره",

    "فدرال رزرو",
    "بورس",

    "اقتصاد",
    "بازار جهانی",

    "نفت",
    "تحریم",

]


WORLD_KEYWORDS = [

    "ترامپ",
    "Trump",

    "ایران",
    "Iran",

    "اسرائیل",
    "Israel",

    "آمریکا",
    "United States",
    "US",

    "جنگ",
    "war",

    "حمله",
    "strike",

    "حملات",
    "attacks",

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


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(

    level=logging.INFO,

    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    )

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


def normalize_fa(text):

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

        g_day_no += (
            g_days_in_month[i]
        )

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

        + 4 * (
            j_day_no // 1461
        )

    )

    j_day_no %= 1461

    if j_day_no >= 366:

        jy += (
            (j_day_no - 1)
            // 365
        )

        j_day_no = (
            j_day_no - 1
        ) % 365

    i = 0

    while (

        i < 11

        and

        j_day_no
        >=
        j_days_in_month[i]

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
                "en-US;q=0.8,en;q=0.7"

        },

        timeout=timeout

    )

    response.raise_for_status()

    return response.text


# =========================================================
# TELEGRAM PUBLIC CHANNEL
# =========================================================

def public_source_url():

    return (
        "https://t.me/s/"
        f"{SOURCE_CHANNEL}"
    )


def fetch_public_page():

    return http_get(
        public_source_url(),
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
# RATE PARSER
# =========================================================

def parse_rate_message(
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
        50_000
        <= tehran
        <= 2_000_000
    ):

        return None

    return {

        "ounce": ounce,

        "tehran": tehran

    }


def find_latest_public_rate():

    html = fetch_public_page()

    messages = parse_public_messages(
        html
    )

    if not messages:

        raise RuntimeError(
            "کانال عمومی منبع هیچ پیامی برنگرداند."
        )

    for message_id, text in messages:

        rate = parse_rate_message(
            text
        )

        if rate:

            log.info(
                "SOURCE RATE FOUND | message=%s",
                message_id
            )

            log.info(
                "SOURCE OUNCE = %s",
                rate["ounce"]
            )

            log.info(
                "SOURCE TEHRAN = %s",
                rate["tehran"]
            )

            return (
                rate,
                message_id
            )

    raise RuntimeError(
        "هیچ نرخ معتبر شامل انس و دلار تهران پیدا نشد."
    )


# =========================================================
# WEBSITE PRODUCT PRICES
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

        title_text = (
            normalize_product_name(
                title.get_text(
                    " ",
                    strip=True
                )
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

    selectors = [

        ".woocommerce-Price-amount",

        ".price"

    ]

    for selector in selectors:

        nodes = card.select(
            selector
        )

        for node in reversed(
            nodes
        ):

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

    shot_title = (
        "نقره ساچمه 1000 گرمی با عیار 995"
    )

    shot_card = find_product_card(

        soup,

        shot_title

    )

    if shot_card is None:

        raise RuntimeError(

            "محصول دقیق ساچمه "
            "1000 گرمی 995 پیدا نشد."

        )

    shot_package = (
        get_current_price_from_card(
            shot_card
        )
    )

    if shot_package is None:

        raise RuntimeError(

            "قیمت دقیق ساچمه "
            "1000 گرمی 995 پیدا نشد."

        )

    nader_title = (
        "شمش 1000 گرمی 999.9 نادیر"
    )

    nader_card = find_product_card(

        soup,

        nader_title

    )

    if nader_card is None:

        raise RuntimeError(

            "محصول دقیق شمش "
            "1000 گرمی 999.9 نادیر پیدا نشد."

        )

    nader_package = (
        get_current_price_from_card(
            nader_card
        )
    )

    if nader_package is None:

        raise RuntimeError(

            "قیمت دقیق شمش نادیر "
            "1000 گرمی پیدا نشد."

        )

    shot_per_gram = (
        shot_package / 1000
    )

    nader_per_gram = (
        nader_package / 1000
    )

    mithqal = (
        shot_per_gram
        * MITHQAL_GRAMS
    )

    mithqal = (
        round(
            mithqal / 100
        )
        * 100
    )

    result = {

        "shot_995":
            int(
                round(
                    shot_per_gram
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
                mithqal
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
        "WEBSITE SHOT 995 / 1KG = %s",
        format_price(
            shot_package
        )
    )

    log.info(
        "WEBSITE NADER 999.9 / 1KG = %s",
        format_price(
            nader_package
        )
    )

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

            "فایل "
            "board_only_preview.png "
            "پیدا نشد."

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

            "ابعاد "
            "board_only_preview.png "
            "باید 1086x1448 باشد. "
            f"ابعاد فعلی: {image.size}"

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
# RATE CAPTION
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


# =========================================================
# NEWS HELPERS
# =========================================================

def keyword_match(
    text,
    keywords
):

    text = normalize_fa(
        text
    ).lower()

    return any(

        keyword.lower()
        in text

        for keyword in keywords

    )


def extract_article_text(
    soup
):

    selectors = [

        "article",

        ".article-content",

        ".news-content",

        ".news-detail",

        ".content",

        ".story-content",

        ".article-body",

        "main"

    ]

    best = ""

    for selector in selectors:

        node = soup.select_one(
            selector
        )

        if not node:

            continue

        paragraphs = []

        for p in node.select(
            "p"
        ):

            text = normalize_fa(

                p.get_text(
                    " ",
                    strip=True
                )

            )

            if len(text) >= 30:

                paragraphs.append(
                    text
                )

        if paragraphs:

            candidate = "\n".join(
                paragraphs
            )

            if len(candidate) > len(
                best
            ):

                best = candidate

    if not best:

        paragraphs = []

        for p in soup.select(
            "p"
        ):

            text = normalize_fa(

                p.get_text(
                    " ",
                    strip=True
                )

            )

            if len(text) >= 40:

                paragraphs.append(
                    text
                )

        best = "\n".join(
            paragraphs[:12]
        )

    return best


def extract_title(
    soup,
    fallback=""
):

    title = ""

    h1 = soup.find(
        "h1"
    )

    if h1:

        title = normalize_fa(

            h1.get_text(
                " ",
                strip=True
            )

        )

    if not title:

        meta = soup.find(

            "meta",

            attrs={
                "property":
                    "og:title"
            }

        )

        if meta:

            title = normalize_fa(

                meta.get(
                    "content",
                    ""
                )

            )

    if not title:

        title = normalize_fa(
            fallback
        )

    return title


def extract_description(
    soup
):

    description = ""

    meta = soup.find(

        "meta",

        attrs={
            "property":
                "og:description"
        }

    )

    if meta:

        description = normalize_fa(

            meta.get(
                "content",
                ""
            )

        )

    if not description:

        meta = soup.find(

            "meta",

            attrs={
                "name":
                    "description"
            }

        )

        if meta:

            description = normalize_fa(

                meta.get(
                    "content",
                    ""
                )

            )

    return description


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

        url = urljoin(
            base_url,
            href
        )

        title = normalize_fa(

            anchor.get_text(
                " ",
                strip=True
            )

        )

        if len(title) < 20:

            continue

        if url in seen:

            continue

        seen.add(
            url
        )

        result.append({

            "url": url,

            "title": title

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

            "NEWS INDEX FAILED | %s | %s",

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

            "NEWS ARTICLE FAILED | %s | %s",

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

    article_text = (
        extract_article_text(
            soup
        )
    )

    description = (
        extract_description(
            soup
        )
    )

    if len(article_text) < 100:

        if len(description) >= 100:

            article_text = description

        else:

            return None

    # Remove excessive whitespace.
    article_text = re.sub(

        r"\n{3,}",

        "\n\n",

        article_text

    ).strip()

    if len(article_text) < 100:

        return None

    # Keep Telegram post readable.
    if len(article_text) > 1300:

        article_text = (

            article_text[:1300]

            .rsplit(
                " ",
                1
            )[0]

            + "..."

        )

    return {

        "url":
            item["url"],

        "title":
            title,

        "text":
            article_text

    }


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

        url = item["url"]

        if url in seen_urls:

            continue

        seen_urls.add(
            url
        )

        if url in history:

            continue

        if not keyword_match(

            item["title"],

            keywords

        ):

            continue

        article = fetch_news_article(
            item
        )

        if not article:

            continue

        full_text = (

            article["title"]

            + " "

            + article["text"]

        )

        if not keyword_match(

            full_text,

            keywords

        ):

            continue

        # Very important:
        # If the article has no real body,
        # NEVER publish it.
        if len(
            article["text"]
        ) < 100:

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


def parse_saved_datetime(
    value
):

    if not value:

        return None

    try:

        result = datetime.fromisoformat(
            str(value)
        )

        if result.tzinfo is None:

            result = result.replace(
                tzinfo=IRAN_TZ
            )

        return result.astimezone(
            IRAN_TZ
        )

    except Exception:

        return None


def reset_news_day_if_needed(
    state
):

    today = iran_date_string()

    if state.get(
        "news_date"
    ) != today:

        state["news_date"] = today

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

    try:

        total = int(

            state.get(
                "news_count",
                0
            )
            or 0

        )

    except Exception:

        total = 0

    if total >= NEWS_TOTAL_MAX_PER_DAY:

        return False

    last_post = parse_saved_datetime(

        state.get(
            "news_last_posted_at"
        )

    )

    if last_post is None:

        return True

    elapsed = (

        iran_now()
        - last_post

    ).total_seconds() / 60

    return (
        elapsed
        >= NEWS_MIN_GAP_MINUTES
    )


def make_news_caption(
    article,
    category
):

    if category == "economic":

        header = (
            "📰 خبر مهم اقتصادی و بازار"
        )

    else:

        header = (
            "🌍 خبر مهم سیاسی و ژئوپلیتیک"
        )

    title = normalize_fa(
        article["title"]
    )

    text = normalize_fa(
        article["text"]
    )

    return (

        f"{header}\n\n"

        f"🔸 {title}\n\n"

        f"{text}\n\n"

        f"🕐 {iran_time_string()}\n\n"

        "💬 برای خرید یا هرگونه سؤال:\n"

        f"{TELEGRAM_ID}"

    )


# =========================================================
# TELEGRAM SEND
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

        "RATE POST CREATED | message_id=%s",

        sent.id

    )

    return int(
        sent.id
    )


async def send_news_post(
    client,
    target,
    article,
    category
):

    sent = await client.send_message(

        target,

        make_news_caption(

            article,

            category

        ),

        link_preview=False

    )

    log.info(

        "NEWS POST CREATED | "
        "category=%s | message_id=%s",

        category,

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

            "Secrets missing: "

            + ", ".join(
                missing
            )

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

            "board_only_preview.png "
            "پیدا نشد."

        )

    # =====================================================
    # LOAD STATE
    # =====================================================

    state = load_state()

    reset_news_day_if_needed(
        state
    )

    # =====================================================
    # SOURCE RATE
    # =====================================================

    rate, source_message_id = (

        await asyncio.to_thread(

            find_latest_public_rate

        )

    )

    # =====================================================
    # CURRENT WEBSITE PRICES
    # =====================================================

    products = (
        await get_website_prices()
    )

    # =====================================================
    # PRICE SIGNATURE
    # =====================================================

    current_signature = (

        make_price_signature(

            rate,

            products

        )

    )

    previous_signature = (

        state.get(
            "price_signature",
            ""
        )

    )

    price_changed = (

        current_signature

        !=

        previous_signature

    )

    log.info(

        "PRICE CHANGED = %s",

        price_changed

    )

    # =====================================================
    # NEWS DECISION
    # =====================================================

    news_article = None

    news_category = None

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

        try:

            economic_count = int(

                state.get(
                    "economic_news_count",
                    0
                )
                or 0

            )

        except Exception:

            economic_count = 0

        try:

            world_count = int(

                state.get(
                    "world_news_count",
                    0
                )
                or 0

            )

        except Exception:

            world_count = 0

        # Economic news gets priority until 7 are reached.
        if economic_count < (
            NEWS_ECONOMIC_MAX_PER_DAY
        ):

            news_article = (
                await get_economic_news(
                    history
                )
            )

            if news_article:

                news_category = "economic"

        # Then world / war / Trump.
        if (

            news_article is None

            and

            world_count
            <
            NEWS_WORLD_MAX_PER_DAY

        ):

            news_article = (
                await get_world_news(
                    history
                )
            )

            if news_article:

                news_category = "world"

        # If economic quota is full but world quota remains,
        # look directly for world news.
        if (

            news_article is None

            and

            economic_count
            >=
            NEWS_ECONOMIC_MAX_PER_DAY

            and

            world_count
            <
            NEWS_WORLD_MAX_PER_DAY

        ):

            news_article = (
                await get_world_news(
                    history
                )
            )

            if news_article:

                news_category = "world"

    # =====================================================
    # NOTHING TO POST
    # =====================================================

    if (

        not price_changed

        and

        news_article is None

    ):

        log.info(
            "NO PRICE CHANGE / NO NEW NEWS"
        )

        return

    # =====================================================
    # TELEGRAM CLIENT
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

        # =================================================
        # RATE POST
        # =================================================

        if price_changed:

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

                "price_signature":
                    current_signature,

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

                "updated_at":
                    iran_now().isoformat()

            })

            save_state(
                state
            )

        # =================================================
        # NEWS POST
        # =================================================

        if news_article:

            news_message_id = (

                await send_news_post(

                    client,

                    target,

                    news_article,

                    news_category

                )

            )

            if news_category == "economic":

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

            else:

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

            state["news_count"] = (

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

                news_article["url"]

            )

            state["news_history"] = (

                history[
                    -NEWS_HISTORY_LIMIT:
                ]

            )

            state[
                "last_news_message_id"
            ] = int(
                news_message_id
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
