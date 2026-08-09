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

CHECK_SECONDS = 60

TGH_URL = "https://t.me/s/tghsilver"
SITE_URL = "https://taghizadegan.com/"

TEMPLATE = "template.png"
STATE_FILE = "state.json"

OUNCE_GRAMS = 31.1034768
PURITY_995 = 0.995


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("Yazdandoust")


# =========================
# NUMBER
# =========================

def normalize(text):

    if not text:
        return ""

    table = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789"
    )

    return (
        text.translate(table)
        .replace("٬", ",")
        .replace("،", ",")
    )


def number(text):

    text = normalize(text)
    text = text.replace(",", "")
    text = text.replace(".", "")

    m = re.search(r"\d+", text)

    if not m:
        return None

    return int(m.group())


def money(value):

    if value is None:
        return "—"

    return f"{int(round(value)):,}"


# =========================
# GET WEB
# =========================

def get_page(url):

    r = requests.get(
        url,
        headers={
            "User-Agent":
            "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)"
        },
        timeout=30
    )

    r.raise_for_status()

    return r.text


# =========================
# TGH CHANNEL
# =========================

def read_tgh():

    log.info("Reading TGH channel...")

    html = get_page(TGH_URL)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = normalize(
        soup.get_text(
            "\n",
            strip=True
        )
    )


    # انس نقره

    ounce = None

    m = re.search(
        r"انس\s*[:：]?\s*(\d+(?:\.\d+)?)",
        text
    )

    if m:
        ounce = float(
            m.group(1)
        )


    # دلار تهران

    tehran = None

    m = re.search(
        r"دلار\s*تهران\s*(?:حدود)?\s*([\d,]+)",
        text
    )

    if m:
        tehran = number(
            m.group(1)
        )


    # دلار مشهد

    mashhad = None

    m = re.search(
        r"دلار\s*مشهد\s*(?:حدود)?\s*([\d,]+)",
        text
    )

    if m:
        mashhad = number(
            m.group(1)
        )


    if ounce is None:
        raise Exception(
            "انس نقره از کانال پیدا نشد"
        )

    if mashhad is None:
        raise Exception(
            "دلار مشهد از کانال پیدا نشد"
        )


    log.info(
        "Ounce=%s | Tehran=%s | Mashhad=%s",
        ounce,
        tehran,
        mashhad
    )


    return {
        "ounce": ounce,
        "usd_tehran": tehran,
        "usd_mashhad": mashhad
    }


# =========================
# TAGHIZADEGAN WEBSITE
# =========================

def read_site():

    log.info("Reading Taghizadegan website...")

    html = get_page(SITE_URL)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    page_text = normalize(
        soup.get_text(
            "\n",
            strip=True
        )
    )


    def find_price(
        keyword,
        weight=None
    ):

        # جستجوی مستقیم در متن صفحه

        pattern = (
            rf"{keyword}"
            rf".{{0,500}}?"
            rf"([\d.,]+)\s*تومان"
        )

        matches = re.findall(
            pattern,
            page_text,
            re.I | re.S
        )

        if matches:

            values = []

            for x in matches:

                v = number(x)

                if v:
                    values.append(v)

            if values:

                # قیمت‌های خیلی کوچک مثل 1000 را حذف می‌کنیم

                values = [
                    v for v in values
                    if v > 1_000_000
                ]

                if values:

                    return values[0]


        # جستجوی بر اساس عنوان محصول

        for tag in soup.find_all(
            string=re.compile(
                keyword,
                re.I
            )
        ):

            parent = tag.parent

            for _ in range(6):

                if parent is None:
                    break

                block = normalize(
                    parent.get_text(
                        " ",
                        strip=True
                    )
                )

                prices = re.findall(
                    r"([\d.,]+)\s*تومان",
                    block
                )

                values = []

                for p in prices:

                    v = number(p)

                    if v and v > 1_000_000:

                        values.append(v)

                if values:

                    return values[-1]

                parent = parent.parent


        return None


    # =========================
    # SAچمه 995 - یک کیلو
    # =========================

    shot_995 = find_price(
        r"نقره\s+ساچمه\s+1000\s+گرمی\s+با\s+عیار\s+995"
    )


    if shot_995 is None:

        shot_995 = find_price(
            r"ساچمه\s+1000\s+گرمی\s+با\s+عیار\s+995"
        )


    # =========================
    # NADIR - یک کیلو
    # =========================

    nadir = find_price(
        r"شمش\s+1000\s+گرمی\s+999\.9\s+نادیر"
    )


    if nadir is None:

        nadir = find_price(
            r"1000\s+گرمی\s+999\.9\s+نادیر"
        )


    # روش پشتیبان برای Nadir

    if nadir is None:

        nadir = find_price(
            r"نادیر"
        )


    if shot_995 is None:

        raise Exception(
            "قیمت ساچمه 995 پیدا نشد"
        )


    if nadir is None:

        raise Exception(
            "قیمت Nadir پیدا نشد"
        )


    log.info(
        "Shot995=%s | Nadir=%s",
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
# CALCULATE
# =========================

def calculate():

    tgh = read_tgh()

    site = read_site()


    # قیمت تئوریک نقره 999.9 هر گرم

    silver_9999 = (
        tgh["ounce"]
        *
        tgh["usd_mashhad"]
        /
        OUNCE_GRAMS
    )


    # ساچمه 995 بدون حباب

    no_bubble = (
        silver_9999
        *
        PURITY_995
    )


    # قیمت بازار ساچمه 995 هر گرم

    market = (
        site["shot_995_kg"]
        /
        1000
    )


    # حباب

    bubble = (
        (market / no_bubble) - 1
    ) * 100


    return {

        **tgh,
        **site,

        "no_bubble":
        round(no_bubble),

        "market":
        round(market),

        "bubble":
        round(bubble, 2)

    }


# =========================
# FONT
# =========================

def font(size):

    paths = [

        "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",

        "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf",

        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    ]

    for p in paths:

        if Path(p).exists():

            return ImageFont.truetype(
                p,
                size
            )

    return ImageFont.load_default()


# =========================
# DRAW NUMBER
# =========================

def draw_center(
    draw,
    text,
    box,
    f,
    fill=(239, 213, 166)
):

    x1, y1, x2, y2 = box

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=f
    )

    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]

    x = x1 + ((x2 - x1 - w) / 2)
    y = y1 + ((y2 - y1 - h) / 2)

    draw.text(
        (x, y),
        text,
        font=f,
        fill=fill
    )


# =========================
# CREATE BOARD
# =========================

def make_board(data):

    img = Image.open(
        TEMPLATE
    ).convert("RGB")

    draw = ImageDraw.Draw(img)

    # رنگ پس‌زمینه داخل کادرهای عدد

    bg = (
        1,
        18,
        10
    )

    gold = (
        239,
        213,
        166
    )


    # محل اعداد روی قالب
    # قالب همان template.png است

    areas = {
    "ounce": (610, 305, 915, 360),
    "dollar": (600, 382, 915, 440),

    "no_bubble": (600, 565, 905, 625),
    "market": (600, 625, 905, 690),
    "bubble": (600, 690, 900, 750),

    "nadir": (545, 785, 925, 850),

    "date": (625, 885, 850, 930),
    "time": (890, 885, 1025, 930),
}


    # پاک کردن فقط محل اعداد

    for box in areas.values():

        draw.rectangle(
            box,
            fill=bg
        )


f_big = font(48)
f_money = font(44)
f_small = font(28)
f_tiny = font(24)

# انس

draw_center(
    draw,
    f"{data['ounce']:.2f}",
    areas["ounce"],
    f_big,
    gold
)


    # دلار مشهد

    draw_center(
        draw,
        money(
            data["usd_mashhad"]
        ),
        areas["dollar"],
        f_big,
        gold
    )


    # بدون حباب

    draw_center(
        draw,
        money(
            data["no_bubble"]
        ),
        areas["no_bubble"],
        f_money,
        gold
    )


    # بازار

    draw_center(
        draw,
        money(
            data["market"]
        ),
        areas["market"],
        f_money,
        gold
    )


    # حباب

    draw_center(
        draw,
        f"{data['bubble']:+.2f}",
        areas["bubble"],
        f_money,
        gold
    )


    # Nadir

    draw_center(
        draw,
        money(
            data["nadir_kg"]
        ),
        areas["nadir"],
        f_money,
        gold
    )


    now = datetime.now(
        ZoneInfo(
            "Asia/Tehran"
        )
    )


    # تاریخ شمسی فعلاً از تاریخ سیستم
    # ساعت دقیق تهران

    date_text = now.strftime(
        "%Y/%m/%d"
    )

    time_text = now.strftime(
        "%H:%M"
    )


    draw_center(
        draw,
        date_text,
        areas["date"],
        f_small,
        gold
    )


    draw_center(
        draw,
        time_text,
        areas["time"],
        f_small,
        gold
    )


    output = BytesIO()

    img.save(
        output,
        "PNG"
    )

    output.seek(0)

    return output


# =========================
# CAPTION
# =========================

def caption(
    dollar
):

    return f"""نرخ خرید فروش #ساچمه و #شمش
💵دلارمشهد حدود {money(dollar)}
✅خریدبالای۲ کیلو تماس تلفنی
خرید و فروش انواع شمش های نقره و مستعمل

نرخ خرید فاکتورهای مجموعه همانند همیشه هست"""


# =========================
# SEND TELEGRAM
# =========================

def send_to_channel(
    image,
    text
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
            text
        },

        files={
            "photo":
            (
                "rate.png",
                image,
                "image/png"
            )
        },

        timeout=30

    )


    if not response.ok:

        raise Exception(
            response.text
        )


    log.info(
        "Telegram post sent."
    )


# =========================
# STATE
# =========================

def load_state():

    try:

        return json.loads(
            Path(
                STATE_FILE
            ).read_text(
                encoding="utf-8"
            )
        )

    except Exception:

        return None


def save_state(
    state
):

    Path(
        STATE_FILE
    ).write_text(

        json.dumps(
            state,
            ensure_ascii=False
        ),

        encoding="utf-8"
    )


def comparable(
    data
):

    return {

        "ounce":
        data["ounce"],

        "usd_tehran":
        data["usd_tehran"],

        "usd_mashhad":
        data["usd_mashhad"],

        "shot_995_kg":
        data["shot_995_kg"],

        "nadir_kg":
        data["nadir_kg"],

        "no_bubble":
        data["no_bubble"],

        "market":
        data["market"],

        "bubble":
        data["bubble"]

    }


# =========================
# MAIN
# =========================

def main():

    log.info(
        "YAZDANDOUST SILVER BOT STARTED"
    )


    previous = load_state()


    while True:

        try:

            data = calculate()

            current = comparable(
                data
            )


            if current != previous:

                log.info(
                    "PRICE CHANGED"
                )


                image = make_board(
                    data
                )


                text = caption(
                    data["usd_mashhad"]
                )


                send_to_channel(
                    image,
                    text
                )


                save_state(
                    current
                )


                previous = current


            else:

                log.info(
                    "No price change."
                )


        except Exception as e:

            log.exception(
                "ERROR: %s",
                e
            )


        time.sleep(
            CHECK_SECONDS
        )


if __name__ == "__main__":

    main()
