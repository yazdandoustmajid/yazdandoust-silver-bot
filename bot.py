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
# اتحادیه طلا، جواهر، نقره و سکه مشهد
# ---------------------------------------------------------

MASHHAD_UNION_URL = os.getenv(
    "MASHHAD_UNION_URL",
    "https://etjmir.ir"
).strip()


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

COIN_MINTING_FEE = 0


# =========================================================
# PRICE TIME
# =========================================================

PRICE_START_HOUR = 10
PRICE_START_MINUTE = 0

PRICE_END_HOUR = 20
PRICE_END_MINUTE = 45


# =========================================================
# DAILY MESSAGE TIMES
# =========================================================

MORNING_HOUR = 8
MORNING_MINUTE = 0

CALENDAR_HOUR = 9
CALENDAR_MINUTE = 0

START_TRADES_HOUR = 10
START_TRADES_MINUTE = 30

END_TRADES_HOUR = 21
END_TRADES_MINUTE = 0

REPORT_24H_HOUR = 21
REPORT_24H_MINUTE = 15


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
# EXCLUDED NEWS
# =========================================================

# خبرهایی که صرفاً قیمت طلا را اعلام می‌کنند
# نباید به عنوان خبر طولانی در کانال منتشر شوند.

PRICE_ONLY_NEWS_KEYWORDS = [

    "قیمت طلا",
    "قیمت طلای ۱۸",
    "قیمت طلای 18",
    "گرم طلای ۱۸",
    "گرم طلای 18",
    "قیمت سکه",
    "قیمت دلار",
    "نرخ طلا",
    "نرخ سکه",
    "آخرین قیمت طلا",

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


def iran_date_parts():

    now = iran_now()

    return gregorian_to_jalali(

        now.year,
        now.month,
        now.day

    )


def iran_date_string():

    jy, jm, jd = iran_date_parts()

    return (
        f"{jy:04d}/"
        f"{jm:02d}/"
        f"{jd:02d}"
    )


def iran_time_string():

    return iran_now().strftime(
        "%H:%M"
    )


def current_minutes():

    now = iran_now()

    return (
        now.hour * 60
        + now.minute
    )


def jalali_date_key():

    jy, jm, jd = iran_date_parts()

    return f"{jy:04d}-{jm:02d}-{jd:02d}"


# =========================================================
# HOLIDAY CONTROL
# =========================================================

# تعطیلات رسمی ۱۴۰۵ ایران
# جمعه‌ها نیز به صورت جداگانه تعطیل محسوب می‌شوند.
#
# این لیست شامل تعطیلات رسمی ثبت‌شده برای ۱۴۰۵ است.
# در صورت اعلام تعطیلی فوق‌العاده جدید، می‌توان تاریخ را
# به این مجموعه اضافه کرد.

OFFICIAL_HOLIDAYS_1405 = {

    "1405-01-01",
    "1405-01-02",
    "1405-01-03",
    "1405-01-04",
    "1405-01-12",
    "1405-01-13",
    "1405-01-24",

    "1405-03-03",
    "1405-03-06",
    "1405-03-14",
    "1405-03-15",

    "1405-04-03",
    "1405-04-04",
    "1405-04-13",
    "1405-04-14",
    "1405-04-15",
    "1405-04-16",

    "1405-05-13",
    "1405-05-21",
    "1405-05-22",
    "1405-05-30",

    "1405-06-08",

    "1405-08-22",

    "1405-10-02",
    "1405-10-16",

    "1405-11-04",
    "1405-11-22",

    "1405-12-09",
    "1405-12-19",
    "1405-12-20",
    "1405-12-29",

}


def is_friday():

    # Python Monday=0 ... Sunday=6
    # Friday = 4
    return iran_now().weekday() == 4


def is_official_holiday():

    return (
        jalali_date_key()
        in
        OFFICIAL_HOLIDAYS_1405
    )


def is_market_holiday():

    return (
        is_friday()
        or
        is_official_holiday()
    )


def market_status_text():

    if is_friday():

        return "جمعه"

    if is_official_holiday():

        return "تعطیل رسمی"

    return "روز کاری"


# =========================================================
# PRICE TIME
# =========================================================

def is_price_time():

    if is_market_holiday():

        return False

    now_minutes = current_minutes()

    start = (
        PRICE_START_HOUR * 60
        + PRICE_START_MINUTE
    )

    end = (
        PRICE_END_HOUR * 60
        + PRICE_END_MINUTE
    )

    return (
        start
        <=
        now_minutes
        <=
        end
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
                "no-cache",

            "Pragma":
                "no-cache"

        },

        timeout=timeout

    )

    response.raise_for_status()

    return response.text


# =========================================================
# TELEGRAM PUBLIC SOURCE
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

        "ounce":
            ounce,

        "tehran":
            tehran

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

    shot_title = (
        "نقره ساچمه 1000 گرمی با عیار 995"
    )

    shot_card = find_product_card(
        soup,
        shot_title
    )

    if shot_card is None:

        raise RuntimeError(
            "محصول دقیق ساچمه پیدا نشد."
        )

    shot_package = (
        get_current_price_from_card(
            shot_card
        )
    )

    if shot_package is None:

        raise RuntimeError(
            "قیمت ساچمه پیدا نشد."
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
            "محصول دقیق شمش نادیر پیدا نشد."
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
            )

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
# MASHHAD UNION GOLD
# =========================================================

def parse_mashhad_union_prices(
    html
):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = normalize_fa(
        soup.get_text(
            " ",
            strip=True
        )
    )

    # -----------------------------
    # طلای ۱۸ عیار
    # -----------------------------

    gold_patterns = [

        r"طلای\s*18\s*(?:عیار)?"
        r".{0,80}?"
        r"([\d,٬ ]{7,})",

        r"۱۸\s*عیار"
        r".{0,80}?"
        r"([\d,٬ ]{7,})",

        r"گرم\s*طلا"
        r".{0,80}?"
        r"([\d,٬ ]{7,})",

    ]

    gold = None

    for pattern in gold_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            candidate = integer_value(
                match.group(1)
            )

            if candidate is not None:

                if candidate < 1_000_000:

                    candidate *= 10

                if (
                    1_000_000
                    <= candidate
                    <= 1_000_000_000
                ):

                    gold = candidate
                    break

    # -----------------------------
    # سکه امامی
    # -----------------------------

    coin_patterns = [

        r"سکه\s*امامی"
        r".{0,80}?"
        r"([\d,٬ ]{8,})",

        r"سکه\s*امام"
        r".{0,80}?"
        r"([\d,٬ ]{8,})",

    ]

    coin = None

    for pattern in coin_patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            candidate = integer_value(
                match.group(1)
            )

            if candidate is not None:

                if candidate < 10_000_000:

                    candidate *= 10

                if (
                    100_000_000
                    <= candidate
                    <= 10_000_000_000
                ):

                    coin = candidate
                    break

    if gold is None:

        log.warning(
            "MASHHAD UNION GOLD NOT FOUND"
        )

        return None

    if coin is None:

        log.warning(
            "MASHHAD UNION COIN NOT FOUND"
        )

        return None

    log.info(
        "MASHHAD UNION | GOLD=%s | COIN=%s",
        gold,
        coin
    )

    return {

        "gold_18_mashhad":
            int(gold),

        "coin_imami":
            int(coin)

    }


def find_latest_mashhad_market():

    try:

        html = http_get(
            MASHHAD_UNION_URL,
            timeout=30
        )

        result = parse_mashhad_union_prices(
            html
        )

        if result:

            result[
                "source_url"
            ] = MASHHAD_UNION_URL

            return result

    except Exception as error:

        log.exception(
            "MASHHAD UNION ERROR: %s",
            error
        )

    return None


async def get_mashhad_market():

    return await asyncio.to_thread(
        find_latest_mashhad_market
    )


# =========================================================
# COIN BUBBLE
# =========================================================

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
            int(
                round(
                    intrinsic
                )
            ),

        "bubble":
            int(
                round(
                    bubble
                )
            )

    }


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

def get_font(
    size
):

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
            "ابعاد board_only_preview.png باید 1086x1448 باشد."
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

        f"📅 تاریخ: {iran_date_string()}\n"
        f"🕐 ساعت: {iran_time_string()}\n\n"

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
# MORNING MESSAGES
# =========================================================

MORNING_MESSAGES = [

    (
        "🌅 صبح بخیر یزدان‌دوست\n\n"
        "هر روز یک فرصت تازه است برای اینکه "
        "یک قدم از دیروز جلوتر برویم.\n\n"
        "✨ با آرامش شروع کن، با تمرکز ادامه بده "
        "و به نتیجه اعتماد داشته باش."
    ),

    (
        "☀️ صبح بخیر\n\n"
        "موفقیت همیشه با یک حرکت بزرگ شروع نمی‌شود؛ "
        "گاهی فقط کافی است امروز را کمی بهتر از دیروز بسازیم.\n\n"
        "💚 روزی پر از آرامش و اتفاق‌های خوب برای شما."
    ),

    (
        "🌱 صبح تازه، شروعی تازه\n\n"
        "آینده از تصمیم‌های کوچک امروز ساخته می‌شود.\n"
        "امروز بهترین زمان برای شروع یک قدم جدید است.\n\n"
        "✨ پرانرژی باشید و به مسیرتان ادامه دهید."
    ),

    (
        "🌞 صبح بخیر دوستان عزیز\n\n"
        "اگر آرام و پیوسته حرکت کنی، "
        "حتی قدم‌های کوچک هم تو را به مقصد می‌رسانند.\n\n"
        "💫 امروز را با امید و انرژی خوب شروع کن."
    ),

    (
        "🌿 یک صبح خوب برای یک شروع خوب\n\n"
        "قرار نیست همه‌چیز یک‌باره تغییر کند؛ "
        "کافی است امروز یک کار درست انجام دهی.\n\n"
        "🤍 امیدواریم روزتان پر از خیر و آرامش باشد."
    ),

    (
        "☀️ صبح بخیر\n\n"
        "به جای نگرانی درباره فردا، "
        "امروزت را درست بساز.\n\n"
        "🚀 استمرار، آرامش و تمرکز سه قدم مهم برای موفقیت‌اند."
    ),

    (
        "🌅 روزتان بخیر\n\n"
        "هیچ موفقیتی یک‌شبه ساخته نمی‌شود؛ "
        "نتیجه‌ی تلاش‌های کوچک و مداوم است.\n\n"
        "✨ امروز هم یک قدم جلوتر برو."
    ),

    (
        "💚 صبح بخیر\n\n"
        "گاهی بهترین اتفاق زندگی، "
        "همان تصمیمی است که برای ادامه دادن می‌گیری.\n\n"
        "🌱 امیدواریم امروز برای شما روزی آرام و پربرکت باشد."
    ),

]


def make_morning_message(
    state
):

    used = state.get(
        "morning_message_history",
        []
    )

    if not isinstance(
        used,
        list
    ):

        used = []

    available = [

        i
        for i in range(
            len(MORNING_MESSAGES)
        )

        if i not in used

    ]

    if not available:

        used = []

        available = list(
            range(
                len(MORNING_MESSAGES)
            )
        )

    # انتخاب بر اساس روز تا ترتیب قابل پیش‌بینی
    index = available[
        len(used)
        %
        len(available)
    ]

    message = MORNING_MESSAGES[
        index
    ]

    used.append(
        index
    )

    state[
        "morning_message_history"
    ] = used[
        -len(MORNING_MESSAGES):
    ]

    return (

        message
        + "\n\n"
        + f"📅 {iran_date_string()}"
        + channel_footer()

    )


# =========================================================
# DAILY CALENDAR
# =========================================================

WEEKDAYS_FA = [

    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنج‌شنبه",
    "جمعه",
    "شنبه",
    "یکشنبه",

]


def iran_weekday_name():

    return WEEKDAYS_FA[
        iran_now().weekday()
    ]


def make_calendar_message():

    jy, jm, jd = iran_date_parts()

    status = market_status_text()

    if is_market_holiday():

        market_line = (
            "🔴 وضعیت معاملات: تعطیل"
        )

    else:

        market_line = (
            "🟢 وضعیت معاملات: فعال"
        )

    return (

        "📅 تقویم امروز\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🗓 {iran_weekday_name()}\n"
        f"📆 {jy:04d}/{jm:02d}/{jd:02d}\n\n"

        f"{market_line}\n"
        f"ℹ️ وضعیت روز: {status}\n\n"

        "⏰ ساعات انتشار نرخ نقره:\n"
        "۱۰:۰۰ تا ۲۰:۴۵\n\n"

        "📌 در روزهای تعطیل رسمی و جمعه، "
        "استیکرهای شروع و پایان معاملات "
        "و پست‌های قیمت معاملاتی منتشر نمی‌شوند."

        + channel_footer()

    )


# =========================================================
# NEWS HELPERS
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

    if len(text) > 1100:

        text = (

            text[:1100]
            .rsplit(
                " ",
                1
            )[0]
            + "…"

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


def is_price_only_news(
    article
):

    title = normalize_fa(
        article.get(
            "title",
            ""
        )
    )

    text = normalize_fa(
        article.get(
            "text",
            ""
        )
    )

    combined = (
        title
        + " "
        + text[:400]
    )

    return keyword_match(
        combined,
        PRICE_ONLY_NEWS_KEYWORDS
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

        # خبر صرفاً قیمت طلا/سکه/دلار نباشد
        if is_price_only_news(
            article
        ):

            log.info(
                "PRICE-ONLY NEWS SKIPPED | %s",
                article["title"]
            )

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

    urgent = is_urgent_news(
        article
    )

    if urgent:

        header = (
            "🚨 خبر فوری بازار"
        )

    else:

        header = (
            "📰 مهم‌ترین خبر بازار"
        )

    return (

        f"{header}\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🔸 {article['title']}\n\n"

        f"{article['text']}\n\n"

        "━━━━━━━━━━━━━━\n"
        f"🕐 {iran_time_string()}"

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
        "━━━━━━━━━━━━━━\n"

        f"📅 {iran_date_string()}\n"
        f"🕐 {iran_time_string()}\n\n"

        "🥇 طلای ۱۸ عیار مشهد\n"
        f"💰 {format_price(market['gold_18_mashhad'])} تومان\n\n"

        "🪙 سکه امامی\n"
        f"💰 {format_price(market['coin_imami'])} تومان\n\n"

        f"{bubble_label}\n\n"

        "📌 ارزش ذاتی محاسبه‌شده سکه\n"
        f"{format_price(bubble['intrinsic'])} تومان"

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

    bubble = calculate_coin_bubble(

        rate,

        market[
            "coin_imami"
        ]

    )

    if bubble["bubble"] > 0:

        bubble_text = (
            f"🔴 +{format_price(bubble['bubble'])} تومان"
        )

    elif bubble["bubble"] < 0:

        bubble_text = (
            f"🟢 -{format_price(abs(bubble['bubble']))} تومان"
        )

    else:

        bubble_text = (
            "⚪ بدون حباب"
        )

    lines = [

        "📊 گزارش ۲۴ ساعته بازار",
        "━━━━━━━━━━━━━━",

        f"📅 {iran_date_string()}",
        f"🕐 {iran_time_string()}",
        "",

        "🥇 طلای ۱۸ عیار مشهد",
        f"💰 {format_price(market['gold_18_mashhad'])} تومان",
        "",

        "🪙 سکه امامی",
        f"💰 {format_price(market['coin_imami'])} تومان",
        f"🎈 حباب سکه: {bubble_text}",
        "",

        "🥈 ساچمه نقره ۹۹۵",
        f"💰 {format_price(products['shot_995'])} تومان",
        "",

        "🧱 شمش نادیر ۹۹۹.۹",
        f"💰 {format_price(products['nader_9999'])} تومان",
        "",

        "⚖️ مثقال نقره ۹۹۵",
        f"💰 {format_price(products['mithqal_995'])} تومان",
        "",

        "🌍 انس نقره",
        f"{rate['ounce']:.2f}",
        "",

        "💵 دلار تهران",
        f"{format_price(rate['tehran'])} تومان",

    ]

    lines.append(
        channel_footer()
    )

    return "\n".join(
        lines
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
            elapsed
            >=
            NEWS_MIN_GAP_MINUTES
        )

    except Exception:

        return True


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
# SAFE FALLBACK DATA FOR 24H REPORT
# =========================================================

def get_saved_rate(
    state
):

    if (
        state.get("ounce") is None
        or
        state.get("tehran") is None
    ):

        return None

    return {

        "ounce":
            float(
                state["ounce"]
            ),

        "tehran":
            int(
                state["tehran"]
            )

    }


def get_saved_products(
    state
):

    required = [

        "shot_995",
        "nader_9999",
        "mithqal_995"

    ]

    if any(
        state.get(x) is None
        for x in required
    ):

        return None

    return {

        "shot_995":
            int(
                state["shot_995"]
            ),

        "nader_9999":
            int(
                state["nader_9999"]
            ),

        "mithqal_995":
            int(
                state["mithqal_995"]
            ),

        "shot_package":
            int(
                state.get(
                    "shot_package",
                    0
                )
            ),

        "nader_package":
            int(
                state.get(
                    "nader_package",
                    0
                )
            )

    }


def get_saved_market(
    state
):

    if (
        state.get(
            "gold_18_mashhad"
        )
        is None
        or
        state.get(
            "coin_imami"
        )
        is None
    ):

        return None

    return {

        "gold_18_mashhad":
            int(
                state[
                    "gold_18_mashhad"
                ]
            ),

        "coin_imami":
            int(
                state[
                    "coin_imami"
                ]
            )

    }


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

    state = load_state()

    reset_news_day_if_needed(
        state
    )

    now = iran_now()

    current_time = now.strftime(
        "%H:%M"
    )

    log.info(
        "IRAN TIME = %s",
        current_time
    )

    log.info(
        "MARKET STATUS = %s",
        market_status_text()
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
        # 08:00 MORNING MESSAGE
        #
        # مهم:
        # دیگر وابسته به پنجره 5 دقیقه‌ای نیست.
        # اگر ربات 08:02، 08:10 یا حتی کمی دیرتر اجرا شود،
        # پیام همان روز را از دست نمی‌دهد.
        # =================================================

        if (

            current_minutes()
            >=
            MORNING_HOUR * 60
            + MORNING_MINUTE

            and

            current_minutes()
            <
            CALENDAR_HOUR * 60

            and

            should_send_daily(
                state,
                "morning"
            )

        ):

            try:

                await send_text_post(

                    client,
                    target,
                    make_morning_message(
                        state
                    )

                )

                mark_daily_sent(
                    state,
                    "morning"
                )

                save_state(
                    state
                )

            except Exception as error:

                log.exception(
                    "MORNING MESSAGE FAILED: %s",
                    error
                )

        # =================================================
        # 09:00 DAILY CALENDAR
        # =================================================

        if (

            current_minutes()
            >=
            CALENDAR_HOUR * 60
            + CALENDAR_MINUTE

            and

            current_minutes()
            <
            START_TRADES_HOUR * 60
            + START_TRADES_MINUTE

            and

            should_send_daily(
                state,
                "daily_calendar"
            )

        ):

            try:

                await send_text_post(

                    client,
                    target,
                    make_calendar_message()

                )

                mark_daily_sent(
                    state,
                    "daily_calendar"
                )

                save_state(
                    state
                )

            except Exception as error:

                log.exception(
                    "CALENDAR FAILED: %s",
                    error
                )

        # =================================================
        # FETCH CURRENT PRICE
        #
        # فقط در روز کاری و ساعات قیمت
        # =================================================

        rate = None
        source_message_id = None

        products = None

        if is_price_time():

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

            try:

                products = (
                    await get_website_prices()
                )

            except Exception as error:

                log.exception(
                    "WEBSITE PRICE FAILED: %s",
                    error
                )

        else:

            log.info(
                "PRICE CHECK SKIPPED | OUTSIDE PRICE HOURS OR HOLIDAY"
            )

        # =================================================
        # PRICE UPDATE
        # فقط در صورت تغییر واقعی
        # =================================================

        if (

            is_price_time()

            and

            rate is not None

            and

            products is not None

        ):

            current_signature = (
                make_price_signature(
                    rate,
                    products
                )
            )

            previous_signature = state.get(
                "price_signature"
            )

            if (
                current_signature
                !=
                previous_signature
            ):

                log.info(
                    "PRICE CHANGED -> SENDING NEW PRICE"
                )

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
                        current_signature,

                    "updated_at":
                        iran_now().isoformat()

                })

                save_state(
                    state
                )

            else:

                log.info(
                    "PRICE NOT CHANGED -> NO POST"
                )

        # =================================================
        # 10:30 START TRADES
        #
        # فقط روز کاری
        # =================================================

        if (

            not is_market_holiday()

            and

            current_minutes()
            >=
            START_TRADES_HOUR * 60
            + START_TRADES_MINUTE

            and

            current_minutes()
            <
            END_TRADES_HOUR * 60
            + END_TRADES_MINUTE

            and

            should_send_daily(
                state,
                "start_trades"
            )

        ):

            try:

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

            except Exception as error:

                log.exception(
                    "START STICKER FAILED: %s",
                    error
                )

        # =================================================
        # MASHHAD REPORTS
        # 11:00 / 15:00 / 18:00
        # =================================================

        report_times = [

            (
                "11:00",
                "mashhad_11"
            ),

            (
                "15:00",
                "mashhad_15"
            ),

            (
                "18:00",
                "mashhad_18"
            )

        ]

        for report_time, report_key in report_times:

            hour, minute = map(
                int,
                report_time.split(":")
            )

            start_minute = (
                hour * 60
                + minute
            )

            # بازه 20 دقیقه‌ای برای جلوگیری از از دست رفتن گزارش
            if (

                start_minute
                <=
                current_minutes()
                <
                start_minute + 20

                and

                not is_market_holiday()

            ):

                if should_send_daily(
                    state,
                    report_key
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

                        mashhad_market = None

                    if mashhad_market:

                        # ذخیره آخرین داده اتحادیه
                        state[
                            "gold_18_mashhad"
                        ] = mashhad_market[
                            "gold_18_mashhad"
                        ]

                        state[
                            "coin_imami"
                        ] = mashhad_market[
                            "coin_imami"
                        ]

                        save_state(
                            state
                        )

                    if mashhad_market is not None:

                        report_rate = rate

                        if report_rate is None:

                            report_rate = (
                                get_saved_rate(
                                    state
                                )
                            )

                        if report_rate is not None:

                            try:

                                await send_text_post(

                                    client,
                                    target,

                                    make_mashhad_report(

                                        mashhad_market,
                                        report_rate

                                    )

                                )

                                mark_daily_sent(
                                    state,
                                    report_key
                                )

                                save_state(
                                    state
                                )

                            except Exception as error:

                                log.exception(
                                    "MASHHAD REPORT SEND FAILED: %s",
                                    error
                                )

        # =================================================
        # NEWS
        #
        # تا نیمه‌شب ادامه دارد
        # حتی بعد از ساعت 21
        # =================================================

        if (

            current_minutes()
            <
            24 * 60

            and

            news_is_due(
                state
            )

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

            if (
                economic_count
                <
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

                try:

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

                except Exception as error:

                    log.exception(
                        "NEWS SEND FAILED: %s",
                        error
                    )

        # =================================================
        # 21:00 END TRADES
        #
        # فقط روز کاری
        # =================================================

        if (

            not is_market_holiday()

            and

            current_minutes()
            >=
            END_TRADES_HOUR * 60
            + END_TRADES_MINUTE

            and

            current_minutes()
            <
            REPORT_24H_HOUR * 60
            + REPORT_24H_MINUTE

            and

            should_send_daily(
                state,
                "end_trades"
            )

        ):

            try:

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

            except Exception as error:

                log.exception(
                    "END STICKER FAILED: %s",
                    error
                )

        # =================================================
        # 21:15 24H REPORT
        #
        # اول تلاش برای دریافت داده جدید
        # در صورت خطا استفاده از آخرین داده ذخیره‌شده
        # =================================================

        if (

            current_minutes()
            >=
            REPORT_24H_HOUR * 60
            + REPORT_24H_MINUTE

            and

            current_minutes()
            <
            22 * 60

            and

            should_send_daily(
                state,
                "24h_report"
            )

        ):

            try:

                report_rate = None
                report_products = None
                mashhad_market = None

                # -----------------------------
                # نرخ جدید
                # -----------------------------

                try:

                    report_rate, _ = (
                        await asyncio.to_thread(
                            find_latest_public_rate
                        )
                    )

                except Exception as error:

                    log.warning(
                        "24H RATE REFRESH FAILED: %s",
                        error
                    )

                if report_rate is None:

                    report_rate = (
                        get_saved_rate(
                            state
                        )
                    )

                # -----------------------------
                # محصولات جدید
                # -----------------------------

                try:

                    report_products = (
                        await get_website_prices()
                    )

                except Exception as error:

                    log.warning(
                        "24H WEBSITE REFRESH FAILED: %s",
                        error
                    )

                if report_products is None:

                    report_products = (
                        get_saved_products(
                            state
                        )
                    )

                # -----------------------------
                # طلای مشهد از اتحادیه
                # -----------------------------

                try:

                    mashhad_market = (
                        await get_mashhad_market()
                    )

                except Exception as error:

                    log.warning(
                        "24H UNION REFRESH FAILED: %s",
                        error
                    )

                if mashhad_market is None:

                    mashhad_market = (
                        get_saved_market(
                            state
                        )
                    )

                # -----------------------------
                # ذخیره داده اتحادیه
                # -----------------------------

                if mashhad_market is not None:

                    state[
                        "gold_18_mashhad"
                    ] = mashhad_market[
                        "gold_18_mashhad"
                    ]

                    state[
                        "coin_imami"
                    ] = mashhad_market[
                        "coin_imami"
                    ]

                    save_state(
                        state
                    )

                # -----------------------------
                # ارسال گزارش
                # -----------------------------

                if (

                    report_rate is not None

                    and

                    report_products is not None

                    and

                    mashhad_market is not None

                ):

                    await send_text_post(

                        client,
                        target,

                        make_24h_report(

                            report_rate,
                            report_products,
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

                    log.info(
                        "24H REPORT SENT SUCCESSFULLY"
                    )

                else:

                    log.error(
                        "24H REPORT SKIPPED | REQUIRED DATA NOT AVAILABLE"
                    )

            except Exception as error:

                log.exception(
                    "24H REPORT FAILED: %s",
                    error
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
