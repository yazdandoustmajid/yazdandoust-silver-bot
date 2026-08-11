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
# SETTINGS
# =========================================================

PHONE = "09152449600"

TELEGRAM_ID = "@MajidYazdandoust"

IRAN_TZ = ZoneInfo("Asia/Tehran")

MITHQAL_GRAMS = 4.6083


# =========================================================
# IMPORTANT IMAGE COORDINATES
#
# Template = 1086 x 1448
#
# These coordinates are the ACTUAL five number boxes.
# =========================================================

NUMBER_BOXES = [

    # 1 - انس نقره
    (505, 585, 900, 665),

    # 2 - دلار
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
# IRAN DATE
# =========================================================

def iran_now():

    return datetime.now(IRAN_TZ)


def gregorian_to_jalali(gy, gm, gd):

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
        and j_day_no >= j_days_in_month[i]
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

    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def iran_time_string():

    return iran_now().strftime("%H:%M")


# =========================================================
# TELEGRAM PUBLIC SOURCE
# =========================================================

def public_source_url(before=None):

    url = (
        "https://t.me/s/"
        f"{SOURCE_CHANNEL}"
    )

    if before:
        url += f"?before={int(before)}"

    return url


def fetch_public_page(before=None):

    response = requests.get(

        public_source_url(before),

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

        timeout=30

    )

    response.raise_for_status()

    return response.text


def parse_public_messages(html):

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

def parse_rate_message(text):

    text = clean_text(text)

    compact = text.replace(
        " ",
        ""
    )

    # Must be an actual rate-table message.
    if "انس:" not in text and "انس :" not in text:
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
        r"دلار\s*تهران\s*(?:حدود)?\s*:?\s*([\d,٬ ]+)",
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

    if ounce is None or tehran is None:
        return None

    if not 20 <= ounce <= 150:
        return None

    if not 50_000 <= tehran <= 2_000_000:
        return None

    return {
        "ounce": ounce,
        "tehran": tehran
    }


def find_latest_public_rate():

    before = None

    seen = set()

    for page_number in range(1, 31):

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

                return rate, message_id

        min_id = min(
            x[0]
            for x in messages
        )

        if min_id in seen:
            break

        seen.add(min_id)

        before = min_id

    raise RuntimeError(
        "هیچ نرخ معتبر شامل انس و دلار تهران پیدا نشد."
    )


# =========================================================
# WEBSITE PRICE EXTRACTION
# =========================================================

def normalize_product_name(text):

    text = clean_text(text)

    return (
        text
        .replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
        .strip()
    )


def parse_price_number(text):

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

            values.append(value)

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

    # WooCommerce product title elements.
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

        # The product card is normally
        # the nearest <li class="product">.
        card = title.find_parent(
            "li",
            class_=lambda c:
                c and "product" in c
        )

        if card:
            return card

        # Fallback: nearest element with
        # product-related class.
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


def get_current_price_from_card(card):

    # BEST CASE:
    # WooCommerce sale product has:
    #
    # <del>old price</del>
    # <ins>new price</ins>
    #
    # We ALWAYS prefer <ins>.

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

    # Second choice:
    # Any explicit current-price class.
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
                "en-US;q=0.8,en;q=0.7"

        },

        timeout=30

    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    # =====================================================
    # EXACT PRODUCT 1
    # =====================================================

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

    shot_package = get_current_price_from_card(
        shot_card
    )

    if shot_package is None:

        raise RuntimeError(
            "قیمت محصول دقیق ساچمه 1000 گرمی 995 پیدا نشد."
        )

    # =====================================================
    # EXACT PRODUCT 2
    # =====================================================

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

    nader_package = get_current_price_from_card(
        nader_card
    )

    if nader_package is None:

        raise RuntimeError(
            "قیمت محصول دقیق شمش نادیر 1000 گرمی پیدا نشد."
        )

    # =====================================================
    # CALCULATIONS
    # =====================================================

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

    # Round to nearest 100 تومان.
    mithqal_995 = (
        round(
            mithqal_995 / 100
        )
        * 100
    )

    log.info(
        "WEBSITE EXACT PRODUCT:"
    )

    log.info(
        "Shot 995 / 1kg = %s",
        format_price(
            shot_package
        )
    )

    log.info(
        "Nader 999.9 / 1kg = %s",
        format_price(
            nader_package
        )
    )

    log.info(
        "Shot 995 / gram = %s",
        format_price(
            shot_995_per_gram
        )
    )

    log.info(
        "Nader 999.9 / gram = %s",
        format_price(
            nader_9999_per_gram
        )
    )

    log.info(
        "Mithqal 995 = %s",
        format_price(
            mithqal_995
        )
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

    for attempt in range(1, 5):

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

                await asyncio.sleep(5)

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
# IMAGE DRAWING
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

    # IMPORTANT:
    # The clean template should already contain
    # the original green/gold box.
    #
    # We only clear the central text area,
    # not the borders.

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
            x2 - x1 - text_width
        ) / 2
        - bbox[0]
    )

    y = (
        y1
        + (
            y2 - y1 - text_height
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
            "فایل board_only_preview.png "
            "کنار bot.py پیدا نشد."
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

            "ابعاد فایل board_only_preview.png "
            "باید 1086x1448 باشد. "
            f"ابعاد فعلی: {image.size}"

        )

    draw = ImageDraw.Draw(
        image
    )

    # =====================================================
    # EXACT VALUES
    # =====================================================

    values = [

        # 1
        f"{rate['ounce']:.2f}",

        # 2
        format_price(
            rate["tehran"]
        ),

        # 3
        format_price(
            products["shot_995"]
        ),

        # 4
        format_price(
            products["nader_9999"]
        ),

        # 5
        format_price(
            products["mithqal_995"]
        )

    ]

    # =====================================================
    # DRAW EACH VALUE IN ITS OWN ROW
    # =====================================================

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

        if isinstance(
            data,
            dict
        ):

            return data

    except Exception as error:

        log.warning(
            "State read error: %s",
            error
        )

    return {}


def save_state(state):

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
        "NEW POST CREATED | target_message_id=%s",
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
    # GET LATEST SOURCE RATE
    # =====================================================

    rate, source_message_id = (
        await asyncio.to_thread(
            find_latest_public_rate
        )
    )

    # =====================================================
    # LOAD STATE
    # =====================================================

    state = load_state()

    last_source_message_id = (
        state.get(
            "source_message_id"
        )
    )

    log.info(
        "LAST SOURCE MESSAGE = %s",
        last_source_message_id
    )

    log.info(
        "CURRENT SOURCE MESSAGE = %s",
        source_message_id
    )

    # =====================================================
    # SAME MESSAGE = DO NOTHING
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
            "SOURCE MESSAGE ALREADY PROCESSED."
        )

        return

    # =====================================================
    # GET EXACT WEBSITE PRICES
    # =====================================================

    products = (
        await get_website_prices()
    )

    # =====================================================
    # CREATE IMAGE
    # =====================================================

    image = create_board(
        rate,
        products
    )

    caption = make_caption()

    # =====================================================
    # TELEGRAM
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

    target_message_id = None

    try:

        log.info(
            "Connecting Telegram..."
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
        # NEW POST
        # =================================================

        target_message_id = (
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
    # SAVE STATE
    # =====================================================

    save_state({

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

        "updated_at":
            iran_now().isoformat()

    })

    log.info(
        "STATE SAVED"
    )

    log.info(
        "SUCCESS"
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
