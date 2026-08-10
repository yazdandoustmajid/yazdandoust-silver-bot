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
from telethon import TelegramClient, events
from telethon.sessions import StringSession
BASE = Path(__file__).resolve().parent
TEMPLATE = BASE / "board_only_preview.png"
CLEAN_TEMPLATE = BASE / "template_blank_clean.png"
STATE = BASE / "state.json"
OUTPUT = BASE / "latest_price.jpg"
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
WEBSITE_URL = os.getenv(
    "WEBSITE_URL",
    "https://taghizadegan.com"
).strip()
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
NUMBER_BOXES = [
    (570, 435, 850, 510),
    (570, 550, 850, 635),
    (570, 665, 850, 750),
    (570, 785, 850, 870),
    (570, 900, 850, 990),
]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger(
    "YAZDANDOUST"
)
PERSIAN_DIGITS = "Û°Û±Û²Û³Û´ÛµÛ¶Û·Û¸Û¹"
ARABIC_DIGITS = "Ù Ù¡Ù¢Ù£Ù¤Ù¥Ù¦Ù§Ù¨Ù©"
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
    text = normalize_digits(text)
    text = (
        text
        .replace("Ù¬", ",")
        .replace("Ù«", ".")
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
        .replace("Ù¬", "")
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
        .replace("Ù¬", "")
        .replace("Ù«", ".")
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
def gregorian_to_jalali(gy, gm, gd):
    """
    ØªØ¨Ø¯ÛÙ ØªØ§Ø±ÛØ® ÙÛÙØ§Ø¯Û Ø¨Ù Ø´ÙØ³Û Ø¨Ø¯ÙÙ ÙÛØ§Ø² Ø¨Ù Ù¾Ú©ÛØ¬ Ø®Ø§Ø±Ø¬Û.
    """
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
    if "Ø§ÙØ³" not in compact:
        return None
    if "Ø¯ÙØ§Ø±ØªÙØ±Ø§Ù" not in compact:
        return None
    if not any(
        marker in compact
        for marker in (
            "Ø¬Ø¯ÙÙÙØ±Ø®",
            "ÙØ±Ø®Ø®Ø±ÛØ¯ÙØ±ÙØ´",
            "ÙØ±Ø®"
        )
    ):
        return None
    ounce_match = re.search(
        r"Ø§ÙØ³\s*:?\s*"
        r"([\d,.]+)",
        text
    )
    if not ounce_match:
        return None
    ounce = decimal_value(
        ounce_match.group(1)
    )
    tehran_match = re.search(
        r"Ø¯ÙØ§Ø±\s*ØªÙØ±Ø§Ù"
        r"\s*(?:Ø­Ø¯ÙØ¯)?"
        r"\s*:?\s*"
        r"([\d,Ù¬ ]+)",
        text
    )
    if not tehran_match:
        return None
    tehran = integer_value(
        tehran_match.group(1)
    )
    if ounce is None:
        return None
    if tehran is None:
        return None
    if not 20 <= ounce <= 150:
        log.warning(
            "Invalid ounce received: %s",
            ounce
        )
        return None
    if not 50_000 <= tehran <= 2_000_000:
        log.warning(
            "Invalid Tehran dollar received: %s",
            tehran
        )
        return None
    return {
        "ounce": ounce,
        "tehran": tehran
    }
PRODUCT_ALIASES = {
    "shot_995": [
        "ÙÙØ±Ù Ø³Ø§ÚÙÙ 1000 Ú¯Ø±ÙÛ Ø¨Ø§ Ø¹ÛØ§Ø± 995",
        "ÙÙØ±Ù Ø³Ø§ÚÙÙ 1000 Ú¯Ø±ÙÛ Ø¨Ø§ Ø¹ÛØ§Ø± Û¹Û¹Ûµ",
        "ÙÙØ±Ù Ø³Ø§ÚÙÙ Û±Û°Û°Û° Ú¯Ø±ÙÛ Ø¨Ø§ Ø¹ÛØ§Ø± 995",
        "ÙÙØ±Ù Ø³Ø§ÚÙÙ Û±Û°Û°Û° Ú¯Ø±ÙÛ Ø¨Ø§ Ø¹ÛØ§Ø± Û¹Û¹Ûµ",
    ],
    "nader_9999": [
        "Ø´ÙØ´ 1000 Ú¯Ø±ÙÛ 999.9 ÙØ§Ø¯ÛØ±",
        "Ø´ÙØ´ 1000 Ú¯Ø±ÙÛ Û¹Û¹Û¹.Û¹ ÙØ§Ø¯ÛØ±",
        "Ø´ÙØ´ Û±Û°Û°Û° Ú¯Ø±ÙÛ 999.9 ÙØ§Ø¯ÛØ±",
        "Ø´ÙØ´ Û±Û°Û°Û° Ú¯Ø±ÙÛ Û¹Û¹Û¹.Û¹ ÙØ§Ø¯ÛØ±",
    ],
}
def extract_prices_from_text(text):
    """
    ØªÙØ§Ù ÙÛÙØªâÙØ§Û ØªÙÙØ§Ù ÙÙØ¬ÙØ¯ Ø¯Ø± ÛÚ© ÙØ·Ø¹Ù DOM Ø±Ø§ Ù¾ÛØ¯Ø§ ÙÛâÚ©ÙØ¯.
    """
    text = clean_text(
        text
    )
    patterns = [
        r"([\d][\d.,Ù¬ ]*)\s*ØªÙÙØ§Ù",
        r"ØªÙÙØ§Ù\s*([\d][\d.,Ù¬ ]*)",
    ]
    values = []
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
                values.append(
                    value
                )
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
def normalize_product_name(text):
    text = clean_text(
        text
    )
    return (
        text
        .replace("Ù", "Û")
        .replace("Ù", "Ú©")
        .replace("â", " ")
        .strip()
    )
def product_name_matches(
    text,
    aliases
):
    normalized = normalize_product_name(
        text
    )
    normalized_compact = normalized.replace(
        " ",
        ""
    )
    for alias in aliases:
        alias_normalized = normalize_product_name(
            alias
        )
        if alias_normalized in normalized:
            return True
        if (
            alias_normalized.replace(" ", "")
            in normalized_compact
        ):
            return True
    return False
def find_exact_product_price(
    soup,
    aliases
):
    """
    Ø§Ø³Ù ÙØ­ØµÙÙ Ø±Ø§ Ù¾ÛØ¯Ø§ ÙÛâÚ©ÙØ¯ Ù Ø¯Ø± ÙØ²Ø¯ÛÚ©âØªØ±ÛÙ Ú©Ø§Ø±Øª ÙØ­ØµÙÙØ
    ÙÛÙØª ÙÙØ§Ù ÙØ­ØµÙÙ Ø±Ø§ Ø¨Ø±ÙÛâÚ¯Ø±Ø¯Ø§ÙØ¯.
    """
    candidates = soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "a",
            "li",
            "div"
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
        for _ in range(8):
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
        "WEBSITE | shot 995 / 1kg = %s",
        shot_package
    )
    log.info(
        "WEBSITE | Nader 999.9 / 1kg = %s",
        nader_package
    )
    if shot_package is None:
        raise RuntimeError(
            "ÙÛÙØª Ø¯ÙÛÙ Ø³Ø§ÚÙÙ 1000 Ú¯Ø±ÙÛ Ø¹ÛØ§Ø± 995 "
            "Ø¯Ø± Ø³Ø§ÛØª ØªÙÛâØ²Ø§Ø¯Ú¯Ø§Ù Ù¾ÛØ¯Ø§ ÙØ´Ø¯."
        )
    if nader_package is None:
        raise RuntimeError(
            "ÙÛÙØª Ø¯ÙÛÙ Ø´ÙØ´ 1000 Ú¯Ø±ÙÛ 999.9 ÙØ§Ø¯ÛØ± "
            "Ø¯Ø± Ø³Ø§ÛØª ØªÙÛâØ²Ø§Ø¯Ú¯Ø§Ù Ù¾ÛØ¯Ø§ ÙØ´Ø¯."
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
                await asyncio.sleep(5)
    raise RuntimeError(
        f"Ø®Ø·Ø§ Ø¯Ø± Ø¯Ø±ÛØ§ÙØª ÙÛÙØª Ø³Ø§ÛØª: {last_error}"
    )
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
                "Ø§Ø¨Ø¹Ø§Ø¯ template_blank_clean.png "
                "Ø¨Ø§ÛØ¯ Ø¯ÙÛÙØ§Ù 1086x1035 Ø¨Ø§Ø´Ø¯."
            )
        return image
    if not TEMPLATE.exists():
        raise FileNotFoundError(
            "ÙØ§ÛÙ board_only_preview.png "
            "Ú©ÙØ§Ø± bot.py Ù¾ÛØ¯Ø§ ÙØ´Ø¯."
        )
    original = cv2.imread(
        str(TEMPLATE)
    )
    if original is None:
        raise RuntimeError(
            "Ø®ÙØ§ÙØ¯Ù board_only_preview.png "
            "Ø§ÙÚ©Ø§ÙâÙ¾Ø°ÛØ± ÙÛØ³Øª."
        )
    height, width = (
        original.shape[:2]
    )
    if (
        width != 1086
        or height != 1035
    ):
        raise RuntimeError(
            "Ø§Ø¨Ø¹Ø§Ø¯ board_only_preview.png "
            "Ø¨Ø§ÛØ¯ Ø¯ÙÛÙØ§Ù 1086x1035 Ø¨Ø§Ø´Ø¯."
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
        x2 - x1
        - horizontal_padding * 2
    )
    available_height = (
        y2 - y1
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
            bbox[2] - bbox[0]
        )
        height = (
            bbox[3] - bbox[1]
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
        bbox[2] - bbox[0]
    )
    text_height = (
        bbox[3] - bbox[1]
    )
    x = (
        x1
        + (
            x2 - x1
            - text_width
        ) / 2
        - bbox[0]
    )
    y = (
        y1
        + (
            y2 - y1
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
def make_caption():
    date = iran_date_string()
    time = iran_time_string()
    return (
        f"ð ØªØ§Ø±ÛØ®: {date}\n"
        f"ð Ø³Ø§Ø¹Øª: {time}\n\n"
        f"ð {PHONE}\n\n"
        "â Ø®Ø±ÛØ¯ Ø¨Ø§ÙØ§Û Û² Ú©ÛÙÙ "
        "ØªÙØ§Ø³ ØªÙÙÙÛ Ø¬ÙØª Ø§Ø³ØªØ¹ÙØ§Ù ÙØ±Ø®\n\n"
        "ð¹ Ø®Ø±ÛØ¯ Ù ÙØ±ÙØ´ Ø§ÙÙØ§Ø¹ "
        "Ø´ÙØ´âÙØ§Û ÙØ¹ØªØ¨Ø± (ÙØ§ÙÙÙÛ)\n"
        "ð¹ Ø®Ø±ÛØ¯ ÙØ³ØªØ¹ÙÙ ÙÙØ±Ù\n"
        "ð¹ ÙØ±Ø® Ø®Ø±ÛØ¯ ÙØ§Ú©ØªÙØ±ÙØ§Û ÙØ¬ÙÙØ¹Ù "
        "ÙÙØ§ÙÙØ¯ ÙÙÛØ´Ù ÙØ³Øª\n\n"
        "ð¬ Ø¨Ø±Ø§Û Ø®Ø±ÛØ¯ ÛØ§ ÙØ±Ú¯ÙÙÙ Ø³Ø¤Ø§Ù:\n"
        f"{TELEGRAM_ID}"
    )
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
async def send_or_edit(
    client,
    target,
    image,
    caption
):
    """
    ÙÙÙ:
    Ø§ÛÙ ØªØ§Ø¨Ø¹ ÙØ±Ú¯Ø² ØªØ§Ø±ÛØ®ÚÙ Ú©Ø§ÙØ§Ù Ø±Ø§ Ø¨Ø§ bot_client
    ÙÙÛâØ®ÙØ§ÙØ¯.
    ÙÙØ· message_id Ø°Ø®ÛØ±ÙâØ´Ø¯Ù Ø¯Ø± state.json Ø±Ø§
    ÙÛØ±Ø§ÛØ´ ÙÛâÚ©ÙØ¯.
    Ø§Ú¯Ø± message_id ÙØ¬ÙØ¯ ÙØ¯Ø§Ø´ØªÙ Ø¨Ø§Ø´Ø¯Ø ÛÚ© Ù¾Ø³Øª Ø¬Ø¯ÛØ¯
    Ø§Ø±Ø³Ø§Ù ÙÛâÚ©ÙØ¯.
    """
    state = load_state()
    message_id = state.get(
        "message_id"
    )
    if message_id:
        try:
            await client.edit_message(
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
                "Saved message edit failed: %s",
                error
            )
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
UPDATE_LOCK = asyncio.Lock()
async def process_rate_message(
    message,
    bot_client,
    target
):
    rate = parse_rate_message(
        message.raw_text or ""
    )
    if not rate:
        log.info(
            "Message %s is not a rate message.",
            getattr(
                message,
                "id",
                "?"
            )
        )
        return
    async with UPDATE_LOCK:
        log.info(
            "===================================="
        )
        log.info(
            "RATE FOUND"
        )
        log.info(
            "OUNCE = %s",
            rate["ounce"]
        )
        log.info(
            "TEHRAN USD = %s",
            rate["tehran"]
        )
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
        if (
            state.get("signature")
            == signature
        ):
            log.info(
                "NO PRICE CHANGE - NOTHING TO POST"
            )
            return
        image = create_board(
            rate,
            products
        )
        caption = make_caption()
        message_id = await send_or_edit(
            bot_client,
            target,
            image,
            caption
        )
        save_state(
            {
                "signature":
                    signature,
                "message_id":
                    message_id,
                "source_message_id":
                    int(
                        message.id
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
            "YAZDANDOUST BOARD UPDATED"
        )
        log.info(
            "===================================="
        )
async def find_latest_rate_source_message(
    source_client,
    source_entity
):
    """
    ÙÙØ· source_client Ú©Ù Ø­Ø³Ø§Ø¨ Ú©Ø§Ø±Ø¨Ø±Û Telethon Ø§Ø³Øª
    Ø§Ø¬Ø§Ø²Ù Ø®ÙØ§ÙØ¯Ù ØªØ§Ø±ÛØ®ÚÙ ÙÙØ¨Ø¹ Ø±Ø§ Ø¯Ø§Ø±Ø¯.
    bot_client Ø§ÛÙ Ú©Ø§Ø± Ø±Ø§ Ø§ÙØ¬Ø§Ù ÙÙÛâØ¯ÙØ¯.
    """
    async for message in source_client.iter_messages(
        source_entity,
        limit=100
    ):
        if parse_rate_message(
            message.raw_text or ""
        ):
            return message
    return None
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
            "Ø§ÛÙ ÙØªØºÛØ±ÙØ§ ØªÙØ¸ÛÙ ÙØ´Ø¯ÙâØ§ÙØ¯: "
            + ", ".join(missing)
        )
    if not TEMPLATE.exists():
        raise RuntimeError(
            "ÙØ§ÛÙ board_only_preview.png "
            "Ø¨Ø§ÛØ¯ Ú©ÙØ§Ø± bot.py Ø¨Ø§Ø´Ø¯."
        )
    try:
        api_id = int(
            API_ID
        )
    except ValueError:
        raise RuntimeError(
            "API_ID Ø¨Ø§ÛØ¯ ÙÙØ· Ø¹Ø¯Ø¯ Ø¨Ø§Ø´Ø¯."
        )
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
            retry_delay=5,
            flood_sleep_threshold=60
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
            retry_delay=5,
            flood_sleep_threshold=60
        )
    bot_client = TelegramClient(
        str(
            BASE / "bot"
        ),
        api_id,
        API_HASH,
        sequential_updates=True,
        auto_reconnect=True,
        connection_retries=10,
        retry_delay=5,
        flood_sleep_threshold=60
    )
    log.info(
        "Connecting source account..."
    )
    await source_client.start()
    log.info(
        "Connecting bot..."
    )
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
        "SOURCE CONNECTED: %s",
        SOURCE_CHANNEL
    )
    log.info(
        "TARGET CONNECTED: %s",
        TARGET_CHANNEL
    )
    latest = await find_latest_rate_source_message(
        source_client,
        source_entity
    )
    if latest:
        try:
            await process_rate_message(
                latest,
                bot_client,
                target_entity
            )
        except Exception:
            log.exception(
                "INITIAL UPDATE FAILED"
            )
    else:
        log.warning(
            "No valid rate message found in source."
        )
    @source_client.on(
        events.NewMessage(
            chats=source_entity
        )
    )
    async def new_rate(event):
        try:
            log.info(
                "NEW SOURCE MESSAGE | id=%s",
                event.message.id
            )
            await process_rate_message(
                event.message,
                bot_client,
                target_entity
            )
        except Exception:
            log.exception(
                "NEW MESSAGE ERROR"
            )
    @source_client.on(
        events.MessageEdited(
            chats=source_entity
        )
    )
    async def edited_rate(event):
        try:
            log.info(
                "EDITED SOURCE MESSAGE | id=%s",
                event.message.id
            )
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
        "SOURCE = %s",
        SOURCE_CHANNEL
    )
    log.info(
        "TARGET = %s",
        TARGET_CHANNEL
    )
    log.info(
        "DOLLAR = TEHRAN ONLY"
    )
    log.info(
        "TIMEZONE = Asia/Tehran"
    )
    log.info(
        "WEBSITE = %s",
        WEBSITE_URL
    )
    log.info(
        "NO BOT HISTORY REQUESTS"
    )
    log.info(
        "===================================="
    )
    await source_client.run_until_disconnected()
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
