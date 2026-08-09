# -*- coding: utf-8 -*-

import os
import re
import time
import json
import logging
from pathlib import Path
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont


# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]

CHECK_SECONDS = int(os.getenv("CHECK_SECONDS", "60"))

TGH_URL = "https://t.me/s/tghsilver"
SITE_URL = "https://taghizadegan.com/"

TEMPLATE_PATH = os.getenv("TEMPLATE_PATH", "template.png")
STATE_PATH = os.getenv("STATE_PATH", "state.json")

TROY_OUNCE_GRAMS = 31.1034768
SILVER_PURITY = 0.995


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

log = logging.getLogger("yazdandoust")


# =========================
# NUMBER HELPERS
# =========================

FA_DIGITS = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹",
    "0123456789"
)

AR_DIGITS = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩",
    "0123456789"
)


def normalize_text(text):

    if not text:
        return ""

    text = text.translate(FA_DIGITS)
    text = text.translate(AR_DIGITS)

    return text.replace("٬", ",").replace("،", ",")


def money(text):

    text = normalize_text(text)

    text = text.replace(",", "")
    text = text.replace(" ", "")

    match = re.search(r"\d+", text)

    if not match:
        return None

    return int(match.group())


def decimal_number(text):

    text = normalize_text(text)

    text = text.replace(",", "")

    match = re.search(
        r"\d+(?:\.\d+)?",
        text
    )

    if not match:
        return None

    return float(match.group())


def fmt(number):

    if number is None:
        return "—"

    return f"{int(round(number)):,}"


def fmt_decimal(number):

    return f"{number:.2f}"


# =========================
# WEB REQUEST
# =========================

def fetch(url):

    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent":
            "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)"
        }
    )

    response.raise_for_status()

    return response.text


# =========================
# TGH TELEGRAM
# =========================

def parse_tgh():

    log.info("Reading TGH channel...")

    html = fetch(TGH_URL)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = normalize_text(
        soup.get_text(
            "\n",
            strip=True
        )
    )

    ounce = None
    usd_tehran = None
    usd_mashhad = None


    # انس نقره

    patterns = [

        r"انس\s*نقره\s*[:：]?\s*(\d+(?:\.\d+)?)",

        r"انس\s*[:：]?\s*(\d+(?:\.\d+)?)",

        r"نقره\s*[:：]?\s*(\d+(?:\.\d+)?)"

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            ounce = decimal_number(
                match.group(1)
            )

            break


    # دلار تهران

    patterns = [

        r"دلار\s*تهران\s*(?:حدود|:)?\s*([\d,]+)",

        r"تهران\s*([\d,]+)"

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            usd_tehran = money(
                match.group(1)
            )

            break


    # دلار مشهد

    patterns = [

        r"دلار\s*مشهد\s*(?:حدود|:)?\s*([\d,]+)",

        r"مشهد\s*([\d,]+)"

    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I
        )

        if match:

            usd_mashhad = money(
                match.group(1)
            )

            break


    if ounce is None:

        raise RuntimeError(
            "انس نقره از کانال تقی‌زادگان پیدا نشد"
        )


    if usd_mashhad is None:

        raise RuntimeError(
            "دلار مشهد از کانال تقی‌زادگان پیدا نشد"
        )


    log.info(
        "TGH: ounce=%s Tehran=%s Mashhad=%s",
        ounce,
        usd_tehran,
        usd_mashhad
    )


    return {

        "ounce": ounce,

        "usd_tehran":
        usd_tehran,

        "usd_mashhad":
        usd_mashhad

    }


# =========================
# TAGHIZADEGAN WEBSITE
# =========================

def parse_site():

    log.info(
        "Reading Taghizadegan website..."
    )

    html = fetch(SITE_URL)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = normalize_text(
        soup.get_text(
            "\n",
            strip=True
        )
    )


    shot_995 = None

    nadir = None


    # ساچمه 995

    patterns_995 = [

        r"ساچمه.*?995.*?([\d,]+)\s*تومان",

        r"995.*?ساچمه.*?([\d,]+)\s*تومان",

        r"نقره.*?995.*?([\d,]+)\s*تومان"

    ]


    for pattern in patterns_995:

        matches = re.findall(
            pattern,
            text,
            re.I | re.S
        )

        if matches:

            values = [
                money(x)
                for x in matches
                if money(x)
            ]

            if values:

                shot_995 = values[0]

                break


    # شمش Nadir

    patterns_nadir = [

        r"Nadir.*?1\s*kg.*?([\d,]+)\s*تومان",

        r"Nadir.*?1000.*?گرم.*?([\d,]+)\s*تومان",

        r"نادیر.*?1000.*?([\d,]+)\s*تومان",

        r"نادیر.*?1\s*کیلو.*?([\d,]+)\s*تومان"

    ]


    for pattern in patterns_nadir:

        matches = re.findall(
            pattern,
            text,
            re.I | re.S
        )

        if matches:

            values = [
                money(x)
                for x in matches
                if money(x)
            ]

            if values:

                nadir = values[0]

                break


    if shot_995 is None:

        raise RuntimeError(
            "قیمت ساچمه 995 در سایت پیدا نشد"
        )


    if nadir is None:

        raise RuntimeError(
            "قیمت Nadir در سایت پیدا نشد"
        )


    log.info(
        "SITE: shot995=%s Nadir=%s",
        shot_995,
        nadir
    )


    return {

        "shot_995_kg":
        shot_995,

        "nadir_kg":
        nadir

    }


# =========================
# CALCULATIONS
# =========================

def get_rates():

    tgh = parse_tgh()

    site = parse_site()


    # قیمت خام نقره 999.9 هر گرم

    spot_9999 = (

        tgh["ounce"]

        *

        tgh["usd_mashhad"]

        /

        TROY_OUNCE_GRAMS

    )


    # قیمت بدون حباب 995

    no_bubble_995 = (

        spot_9999

        *

        SILVER_PURITY

    )


    # قیمت بازار هر گرم ساچمه

    market_995 = (

        site["shot_995_kg"]

        /

        1000

    )


    # درصد حباب

    bubble_pct = (

        (
            market_995
            /
            no_bubble_995
        )
        -
        1
    ) * 100


    return {

        **tgh,

        **site,

        "no_bubble_995":
        round(no_bubble_995),

        "market_995":
        round(market_995),

        "bubble_pct":
        round(bubble_pct, 2)

    }


# =========================
# FONT
# =========================

def load_font(
    size,
    bold=False
):

    if bold:

        names = [

            "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf",

            "/usr/share/fonts/opentype/noto/NotoSansArabic-Bold.ttf",

            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

        ]

    else:

        names = [

            "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",

            "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf",

            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

        ]


    for path in names:

        if Path(path).exists():

            return ImageFont.truetype(
                path,
                size
            )


    return ImageFont.load_default()


# =========================
# IMAGE BOARD
# =========================

def cover(
    draw,
    box,
    fill=(1, 18, 10)
):

    draw.rectangle(
        box,
        fill=fill
    )


def centered(
    draw,
    text,
    box,
    font,
    fill=(239, 213, 166)
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
        +
        x2
        -
        width
    ) / 2

    y = (
        y1
        +
        y2
        -
        height
    ) / 2

    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill
    )


def make_board(r):

    img = Image.open(
        TEMPLATE_PATH
    ).convert("RGB")

    draw = ImageDraw.Draw(img)

    gold = (
        239,
        213,
        166
    )


    # اعداد متغیر

    boxes = [

        # انس
        (610, 307, 910, 355),

        # دلار
        (595, 387, 910, 435),

        # بدون حباب
        (610, 575, 900, 625),

        # بازار
        (610, 635, 900, 685),

        # حباب
        (620, 694, 900, 748),

        # Nadir
        (555, 785, 920, 850),

        # تاریخ
        (635, 885, 845, 930),

        # ساعت
        (900, 885, 1025, 930)

    ]


    for box in boxes:

        cover(
            draw,
            box
        )


    f_ounce = load_font(42)

    f_big = load_font(42)

    f_money = load_font(38)

    f_bubble = load_font(38)

    f_date = load_font(25)


    centered(
        draw,
        fmt_decimal(
            r["ounce"]
        ),
        (610,307,910,355),
        f_ounce,
        gold
    )


    centered(
        draw,
        fmt(
            r["usd_mashhad"]
        ),
        (595,387,910,435),
        f_big,
        gold
    )


    centered(
        draw,
        fmt(
            r["no_bubble_995"]
        ),
        (610,575,900,625),
        f_money,
        gold
    )


    centered(
        draw,
        fmt(
            r["market_995"]
        ),
        (610,635,900,685),
        f_money,
        gold
    )


    centered(
        draw,
        f"{r['bubble_pct']:+.2f}",
        (620,694,900,748),
        f_bubble,
        gold
    )


    centered(
        draw,
        fmt(
            r["nadir_kg"]
        ),
        (555,785,920,850),
        f_money,
        gold
    )


    now = datetime.now(
        ZoneInfo(
            "Asia/Tehran"
        )
    )


    date_txt = now.strftime(
        "%Y/%m/%d"
    )

    time_txt = now.strftime(
        "%H:%M"
    )


    centered(
        draw,
        date_txt,
        (635,885,845,930),
        f_date,
        gold
    )


    centered(
        draw,
        time_txt,
        (900,885,1025,930),
        f_date,
        gold
    )


    output = BytesIO()

    img.save(
        output,
        format="PNG",
        optimize=True
    )

    output.seek(0)

    return output


# =========================
# TELEGRAM CAPTION
# =========================

def make_caption(
    usd_mashhad
):

    return f"""نرخ خرید فروش #ساچمه و #شمش
💵دلارمشهد حدود {fmt(usd_mashhad)}
✅خریدبالای۲ کیلو تماس تلفنی
خرید و فروش انواع شمش های نقره و مستعمل

نرخ خرید فاکتورهای مجموعه همانند همیشه هست"""


# =========================
# TELEGRAM
# =========================

def send_photo(
    photo,
    caption
):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/sendPhoto"
    )


    response = requests.post(

        url,

        data={
            "chat_id":
            CHANNEL_ID,

            "caption":
            caption
        },

        files={
            "photo":
            (
                "yazdandoust-rate.png",
                photo,
                "image/png"
            )
        },

        timeout=30

    )


    if not response.ok:

        raise RuntimeError(
            response.text
        )


    return response.json()


# =========================
# STATE
# =========================

def load_state():

    try:

        return json.loads(
            Path(
                STATE_PATH
            ).read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return None


def save_state(data):

    Path(
        STATE_PATH
    ).write_text(

        json.dumps(
            data,
            ensure_ascii=False
        ),

        encoding="utf-8"
    )


def comparable(r):

    return {

        "ounce":
        r["ounce"],

        "usd_tehran":
        r["usd_tehran"],

        "usd_mashhad":
        r["usd_mashhad"],

        "shot_995_kg":
        r["shot_995_kg"],

        "nadir_kg":
        r["nadir_kg"],

        "no_bubble_995":
        r["no_bubble_995"],

        "market_995":
        r["market_995"],

        "bubble_pct":
        r["bubble_pct"]

    }


# =========================
# MAIN LOOP
# =========================

def main():

    log.info(
        "Yazdandoust Silver Bot started"
    )

    previous = load_state()


    while True:

        try:

            rates = get_rates()

            current = comparable(
                rates
            )


            if previous != current:

                log.info(
                    "PRICE CHANGED"
                )


                photo = make_board(
                    rates
                )


                caption = make_caption(
                    rates["usd_mashhad"]
                )


                send_photo(
                    photo,
                    caption
                )


                save_state(
                    current
                )


                previous = current


                log.info(
                    "New board sent successfully"
                )


            else:

                log.info(
                    "No price change"
                )


        except Exception as error:

            log.exception(
                "Update failed: %s",
                error
            )


        time.sleep(
            CHECK_SECONDS
        )


if __name__ == "__main__":

    main()
