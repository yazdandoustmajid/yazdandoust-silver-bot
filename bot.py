# -*- coding: utf-8 -*-
import asyncio
import inspect
import io
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import random
import re
import time
import warnings
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from PIL import Image, ImageDraw, ImageFont
from PIL import ImageOps
from telethon import TelegramClient
from telethon.tl.functions.messages import SendMediaRequest
from telethon.tl.types import (
    InputMediaPoll,
    Poll,
    PollAnswer,
)
from openai import OpenAI

# قسمتی از فیدهای خبری (RSS/XML) با همان پارسر html.parser خوانده می‌شوند
# (parse_news_rss / parse_news_index). این کاملاً عمدی است و منطق پارس
# تغییر نمی‌کند؛ فقط هشدار بی‌ضرر bs4 در این حالت خاموش می‌شود.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    from rubka import Robot as RubikaRobot
except ImportError:
    RubikaRobot = None


# =========================================================
# PATHS
# =========================================================

BASE = Path(__file__).resolve().parent

TEMPLATE = BASE / "board_only_preview.png"
OUTPUT = BASE / "latest_price.jpg"
STATE = BASE / "state.json"

# Start/End trading banners are ordinary Telegram images, NOT stickers.
# Keep them in the same repository folder as bot.py.
START_TRADES_IMAGE = BASE / "start_trades.png"
END_TRADES_IMAGE = BASE / "end_trades.png"

START_TRADES_CAPTION = """🟢 **شروع معاملات بازار**

بازار وارد فاز معاملات شد.
از این لحظه، آخرین تغییرات **طلا، نقره، دلار و انس جهانی** در کانال یزدان‌دوست رصد و منتشر خواهد شد.

🕐 شروع معاملات: **۱۰:۳۰**

📊 برای اطلاع از آخرین قیمت‌ها و تغییرات بازار، همراه ما باشید.

**YAZDANDOUST SILVER**
شفافیت • دقت • اعتماد"""

END_TRADES_CAPTION = """🔴 **پایان معاملات بازار**

معاملات امروز به پایان رسید.
آخرین تغییرات **طلا، نقره، دلار و انس جهانی** تا پایان معاملات در کانال یزدان‌دوست رصد و منتشر شد.

🕐 پایان معاملات: **۲۱:۰۰**

📊 برای اطلاع از آخرین قیمت‌ها و تحلیل‌های بازار، فردا دوباره همراه ما باشید.

**YAZDANDOUST SILVER**
شفافیت • دقت • اعتماد"""


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

ADMIN_TELEGRAM_ID = os.getenv(
    "ADMIN_TELEGRAM_ID",
    ""
).strip()

# Optional username fallback for diagnosing/configuring the admin account.
# Numeric Telegram ID remains the primary and preferred authentication key.
ADMIN_TELEGRAM_USERNAME = os.getenv(
    "ADMIN_TELEGRAM_USERNAME",
    ""
).strip().lstrip("@").lower()

# Bot API polling is intentionally used by the GitHub Actions workflow.
# If an old webhook exists, getUpdates will fail with a conflict until the
# webhook is removed. Never drop pending updates while doing so.
_BOT_API_POLLING_PREPARED = False

# =========================================================
# PROFESSIONAL SALES CONFIGURATION
# =========================================================
SALES_PRICE_LOCK_MINUTES = int(os.getenv("ORDER_PRICE_LOCK_MINUTES", "10") or 10)
SALES_DAILY_LIMIT_GRAMS = int(os.getenv("DAILY_ORDER_LIMIT_GRAMS", "1000") or 1000)
PAYMENT_CARD_NUMBER = os.getenv("PAYMENT_CARD_NUMBER", "").strip()
PAYMENT_CARD_NAME = os.getenv("PAYMENT_CARD_NAME", "").strip()
PAYMENT_IBAN = os.getenv("PAYMENT_IBAN", "").strip()
PAYMENT_IBAN_NAME = os.getenv("PAYMENT_IBAN_NAME", "").strip()
PAYMENT_URL = os.getenv("PAYMENT_URL", "").strip()
SHIPPING_CARRIER = os.getenv("SHIPPING_CARRIER", "پست").strip() or "پست"

SOURCE_CHANNEL = os.getenv(
    "SOURCE_CHANNEL",
    "tghsilver"
).strip().lstrip("@")

WEBSITE_URL = os.getenv(
    "WEBSITE_URL",
    "https://taghizadegan.com"
).strip()

MASHHAD_UNION_URL = os.getenv(
    "MASHHAD_UNION_URL",
    "https://etjmir.ir"
).strip()

# TGJU LIVE GOLD / COIN FALLBACK
# TGJU publishes the current domestic 18K gold and Emami coin rates
# in Iranian rial. Values are converted to toman before entering the
# existing Mashhad-report structure.
TGJU_GOLD_URL = os.getenv(
    "TGJU_GOLD_URL",
    "https://www.tgju.org/profile/geram18"
).strip()

TGJU_COIN_URL = os.getenv(
    "TGJU_COIN_URL",
    "https://www.tgju.org/profile/sekee"
).strip()


# =========================================================
# ECONOMIC CALENDAR SOURCE
# =========================================================
# Public, unauthenticated weekly economic calendar feed (no API key
# needed). Widely used by trading tools; rate-limited by the
# provider to a couple of requests per 5 minutes, which is irrelevant
# since this bot only fetches it once a week.

ECONOMIC_CALENDAR_URL = os.getenv(
    "ECONOMIC_CALENDAR_URL",
    "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
).strip()

# Feed times are published in US Eastern Time.
ECONOMIC_CALENDAR_SOURCE_TZ = ZoneInfo(
    "America/New_York"
)

ECONOMIC_CALENDAR_HOUR = 8
ECONOMIC_CALENDAR_MINUTE = 15


# =========================================================
# GOLD OUNCE SOURCE
# =========================================================

GOLD_OUNCE_URL = os.getenv(
    "GOLD_OUNCE_URL",
    "https://www.tgju.org/profile/ons"
).strip()


# =========================================================
# RUBIKA
# =========================================================

RUBIKA_TOKEN = os.getenv(
    "RUBIKA_TOKEN",
    ""
).strip()

RUBIKA_CHAT_ID = os.getenv(
    "RUBIKA_CHAT_ID",
    ""
).strip()

RUBIKA_MANUAL_SCAN_STATE_KEY = (
    "rubika_manual_scan_message_id"
)

RUBIKA_AUTO_MESSAGE_IDS_KEY = (
    "rubika_auto_telegram_message_ids"
)

RUBIKA_AUTO_MESSAGE_IDS_LIMIT = 1000

RUBIKA_CURRENT_AUTO_MESSAGE_IDS = []

# Prevent overlapping Workflow/Cron executions.
PROCESS_LOCK = BASE / "bot.lock"
PROCESS_LOCK_STALE_SECONDS = 3600

# Price publication is treated as a small transaction so a crash between
# Telegram and Rubika does not cause the Telegram price post to be sent again.
PRICE_PENDING_POST_KEY = "pending_price_post"

# Maximum accepted jump versus the last committed price. These checks are
# intentionally generous and are only a safety net against broken parsers.
MAX_OUNCE_CHANGE = 0.20
MAX_TEHRAN_CHANGE = 0.20
MAX_PRODUCT_CHANGE = 0.35


# =========================================================
# OPENAI AI
# =========================================================

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY",
    ""
).strip()

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5-mini"
).strip()

AI_NEWS_ENABLED = True

AI_NEWS_MAX_WORDS = 140

AI_NEWS_MAX_BODY_WORDS = 90

AI_NEWS_RETRIES = 3

AI_NEWS_SIMILARITY_LIMIT = 0.62


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

GOLD_18_FINENESS = 0.750

OUNCE_GRAMS = 31.1034768


# =========================================================
# BRAND VISUAL IDENTITY
# =========================================================
# Single source of truth for the up/down accent colors used across
# every generated chart/image. Previously each chart hardcoded its
# own slightly different green/red (e.g. (105,215,145) vs
# (100,205,140), and (235,105,105) vs (240,120,120) vs (235,110,110)),
# so the same "up" or "down" concept looked like a different shade
# depending on which post it came from. All chart code should now
# reference these two constants instead of a literal RGB tuple.

BRAND_UP_COLOR = (105, 215, 145)
BRAND_DOWN_COLOR = (235, 110, 110)


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
# NEW CONTENT TIMES
# =========================================================

MARKET_PULSE_HOUR = 12
MARKET_PULSE_MINUTE = 0

MARKET_PULSE_EVENING_HOUR = 20
MARKET_PULSE_EVENING_MINUTE = 30


# =========================================================
# DAILY SILVER VISUAL ANALYSIS
# =========================================================

def daily_market_history(
    state,
    key
):
    """
    تاریخچه واقعی امروز را برای نمودار تحلیل روزانه برمی‌گرداند.
    داده‌ها از market_history خود ربات گرفته می‌شوند.
    """
    history = state.get(
        "market_history",
        []
    )

    if not isinstance(history, list):
        return []

    today = iran_now().date()
    rows = []

    for item in history:
        value = item.get(key)
        timestamp = item.get("timestamp")

        if value is None or not timestamp:
            continue

        try:
            dt = datetime.fromisoformat(
                timestamp
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=IRAN_TZ
                )

            dt = dt.astimezone(
                IRAN_TZ
            )

            if dt.date() != today:
                continue

            rows.append({
                "datetime": dt,
                "value": float(value)
            })

        except (
            TypeError,
            ValueError
        ):
            continue

    return rows


def daily_stats(
    rows
):
    if not rows:
        return {
            "start": None,
            "end": None,
            "high": None,
            "low": None,
            "change_percent": None,
            "change_value": None
        }

    values = [
        row["value"]
        for row in rows
        if row.get("value") is not None
    ]

    if not values:
        return {
            "start": None,
            "end": None,
            "high": None,
            "low": None,
            "change_percent": None,
            "change_value": None
        }

    start = values[0]
    end = values[-1]

    return {
        "start": start,
        "end": end,
        "high": max(values),
        "low": min(values),
        "change_percent": percent_change(
            end,
            start
        ),
        "change_value": (
            end - start
        )
    }


def daily_change_from_history(
    state,
    key,
    current
):
    rows = daily_market_history(
        state,
        key
    )

    stats = daily_stats(rows)

    if (
        stats["start"] is not None
        and current is not None
    ):
        return percent_change(
            current,
            stats["start"]
        )

    return None


def create_daily_silver_image(
    snapshot
):
    """
    کارت گرافیکی تحلیل روزانه نقره ۹۹۵.
    نمودار مستقیماً از market_history همان روز ساخته می‌شود.
    """
    raw_rows = snapshot.get(
        "chart_rows",
        []
    )

    if len(raw_rows) < 2:
        raise RuntimeError(
            "داده کافی برای نمودار روزانه نقره وجود ندارد."
        )

    width = 1400
    height = 1750

    image = Image.new(
        "RGB",
        (width, height),
        (5, 16, 15)
    )

    draw = ImageDraw.Draw(
        image
    )

    # قاب اصلی
    draw.rounded_rectangle(
        (25, 25, width - 25, height - 25),
        radius=28,
        outline=(87, 115, 98),
        width=2
    )

    title_font = get_font(55)
    subtitle_font = get_font(29)
    label_font = get_font(27)
    value_font = get_font(48)
    small_font = get_font(24)
    tiny_font = get_font(20)

    # سربرگ
    draw_rtl(
        draw,
        (width - 65, 62),
        "تحلیل روزانه نقره ۹۹۵",
        title_font,
        (235, 240, 237)
    )

    draw_rtl(
        draw,
        (width - 70, 125),
        "یزدان‌دوست سیلور | گزارش پایان روز",
        subtitle_font,
        (160, 180, 171)
    )

    current = snapshot.get(
        "shot_995",
        {}
    ).get("current")

    change = snapshot.get(
        "shot_995",
        {}
    ).get("daily_change_percent")

    if change is None:
        change = daily_stats(
            raw_rows
        ).get(
            "change_percent"
        )

    current_text = (
        format_level(
            current,
            decimals=0
        )
        if current is not None
        else "نامشخص"
    )

    change_text = (
        "بدون تغییر"
        if change is None
        else (
            f"+{change:.2f}٪"
            if change >= 0
            else f"{change:.2f}٪"
        )
    )

    change_fill = (
        (90, 205, 130)
        if change is None or change >= 0
        else (235, 105, 105)
    )

    # کارت قیمت
    draw.rounded_rectangle(
        (60, 180, width - 60, 355),
        radius=24,
        fill=(10, 27, 25),
        outline=(61, 91, 80),
        width=2
    )

    draw_rtl(
        draw,
        (width - 95, 215),
        "قیمت فعلی ساچمه ۹۹۵",
        label_font,
        (165, 185, 176)
    )

    draw_rtl(
        draw,
        (width - 95, 285),
        f"{current_text} تومان",
        value_font,
        (245, 245, 242)
    )

    draw.text(
        (85, 275),
        change_text,
        font=value_font,
        fill=change_fill
    )

    # نمودار
    chart_left = 95
    chart_top = 420
    chart_right = width - 95
    chart_bottom = 935

    draw_rtl(
        draw,
        (chart_right, chart_top - 35),
        "حرکت قیمت نقره ۹۹۵ در طول امروز",
        label_font,
        (220, 230, 224)
    )

    values = [
        row["value"]
        for row in raw_rows
        if row.get("value") is not None
    ]

    low = min(values)
    high = max(values)

    if high == low:
        high += 1
        low -= 1

    pad = max(
        (high - low) * 0.12,
        1
    )

    plot_low = low - pad
    plot_high = high + pad

    # خطوط راهنما
    for i in range(5):
        y = (
            chart_top
            +
            (chart_bottom - chart_top)
            * i
            / 4
        )

        draw.line(
            (chart_left, y, chart_right, y),
            fill=(36, 61, 54),
            width=1
        )

        tick_value = (
            plot_high
            -
            (plot_high - plot_low)
            * i
            / 4
        )

        draw.text(
            (chart_left - 8, y - 10),
            format_level(
                tick_value,
                decimals=0
            ),
            font=tiny_font,
            fill=(130, 150, 142),
            anchor="ra"
        )

    points = []

    for index, row in enumerate(raw_rows):
        x = (
            chart_left
            +
            (chart_right - chart_left)
            * index
            /
            max(
                len(raw_rows) - 1,
                1
            )
        )

        y = (
            chart_bottom
            -
            (
                row["value"]
                -
                plot_low
            )
            /
            (
                plot_high
                -
                plot_low
            )
            *
            (
                chart_bottom
                -
                chart_top
            )
        )

        points.append(
            (int(x), int(y))
        )

    # خط اصلی نمودار
    for p1, p2 in zip(
        points,
        points[1:]
    ):
        draw.line(
            (
                p1[0],
                p1[1],
                p2[0],
                p2[1]
            ),
            fill=(185, 205, 194),
            width=6
        )

    # نقاط ابتدا و انتها
    for idx in (
        0,
        len(points) - 1
    ):
        x, y = points[idx]

        draw.ellipse(
            (
                x - 9,
                y - 9,
                x + 9,
                y + 9
            ),
            fill=(235, 240, 237)
        )

    # سقف و کف
    high_index = values.index(high)
    low_index = values.index(low)

    high_x, high_y = points[high_index]
    low_x, low_y = points[low_index]

    draw.ellipse(
        (
            high_x - 11,
            high_y - 11,
            high_x + 11,
            high_y + 11
        ),
        outline=(95, 210, 140),
        width=4
    )

    draw.ellipse(
        (
            low_x - 11,
            low_y - 11,
            low_x + 11,
            low_y + 11
        ),
        outline=BRAND_DOWN_COLOR,
        width=4
    )

    draw.text(
        (
            max(
                chart_left,
                high_x - 60
            ),
            max(
                chart_top,
                high_y - 42
            )
        ),
        f"سقف {format_level(high, 0)}",
        font=tiny_font,
        fill=BRAND_UP_COLOR
    )

    draw.text(
        (
            max(
                chart_left,
                low_x - 60
            ),
            min(
                chart_bottom - 25,
                low_y + 16
            )
        ),
        f"کف {format_level(low, 0)}",
        font=tiny_font,
        fill=BRAND_DOWN_COLOR
    )

    # واترمارک واقعی لوگو
    if YAZDANDOUST_LOGO.exists():
        try:
            logo = Image.open(
                YAZDANDOUST_LOGO
            ).convert("RGBA")

            max_logo_w = 390
            max_logo_h = 190

            ratio = min(
                max_logo_w / logo.width,
                max_logo_h / logo.height
            )

            logo = logo.resize(
                (
                    max(
                        1,
                        int(logo.width * ratio)
                    ),
                    max(
                        1,
                        int(logo.height * ratio)
                    )
                ),
                Image.Resampling.LANCZOS
            )

            alpha = logo.getchannel(
                "A"
            ).point(
                lambda a: int(a * 0.12)
            )

            logo.putalpha(
                alpha
            )

            image.paste(
                logo,
                (
                    (
                        width
                        -
                        logo.width
                    ) // 2,
                    chart_top
                    +
                    120
                ),
                logo
            )

        except Exception as error:
            log.warning(
                "DAILY LOGO WATERMARK FAILED: %s",
                error
            )

    # آمار روز
    stats = daily_stats(
        raw_rows
    )

    stat_y = 985

    stat_items = [
        (
            "شروع روز",
            stats.get("start")
        ),
        (
            "کف روز",
            stats.get("low")
        ),
        (
            "سقف روز",
            stats.get("high")
        ),
        (
            "پایان روز",
            stats.get("end")
        ),
    ]

    box_w = 285
    gap = 18
    start_x = 75

    for index, (
        label,
        value
    ) in enumerate(stat_items):

        x1 = (
            start_x
            +
            index
            *
            (
                box_w
                +
                gap
            )
        )

        x2 = x1 + box_w

        draw.rounded_rectangle(
            (
                x1,
                stat_y,
                x2,
                stat_y + 125
            ),
            radius=18,
            fill=(10, 27, 25),
            outline=(49, 75, 67),
            width=2
        )

        draw_rtl(
            draw,
            (
                x2 - 18,
                stat_y + 20
            ),
            label,
            tiny_font,
            (145, 166, 157)
        )

        draw_rtl(
            draw,
            (
                x2 - 18,
                stat_y + 68
            ),
            (
                format_level(
                    value,
                    decimals=0
                )
                if value is not None
                else "—"
            ),
            label_font,
            (230, 236, 232)
        )

    # حمایت و مقاومت
    levels = snapshot.get(
        "shot_995",
        {}
    ).get(
        "levels",
        {}
    )

    support = levels.get(
        "support"
    )

    resistance = levels.get(
        "resistance"
    )

    draw.rounded_rectangle(
        (
            75,
            1150,
            width - 75,
            1310
        ),
        radius=22,
        fill=(10, 27, 25),
        outline=(49, 75, 67),
        width=2
    )

    draw_rtl(
        draw,
        (
            width - 105,
            1180
        ),
        "سطوح مهم امروز",
        label_font,
        (225, 233, 228)
    )

    draw_rtl(
        draw,
        (
            width - 105,
            1240
        ),
        f"حمایت: {format_level(support, 0)} تومان",
        small_font,
        BRAND_UP_COLOR
    )

    draw.text(
        (
            105,
            1240
        ),
        f"مقاومت: {format_level(resistance, 0)} تومان",
        font=small_font,
        fill=BRAND_DOWN_COLOR
    )

    # عوامل مؤثر
    drivers = [
        (
            "انس نقره",
            snapshot.get("silver", {}).get("current"),
            "دلار"
        ),
        (
            "دلار تهران",
            snapshot.get("tehran_dollar", {}).get("current"),
            "تومان"
        ),
    ]

    draw_rtl(
        draw,
        (
            width - 105,
            1360
        ),
        "عوامل اصلی مؤثر بر بازار",
        label_font,
        (225, 233, 228)
    )

    driver_y = 1415

    for title, value, unit in drivers:
        draw_rtl(
            draw,
            (
                width - 105,
                driver_y
            ),
            f"{title}: "
            f"{format_level(value, 2 if unit == 'دلار' else 0)} "
            f"{unit}",
            small_font,
            (175, 192, 183)
        )

        driver_y += 42

    draw.text(
        (
            80,
            1600
        ),
        "@yazdandoustsilver",
        font=small_font,
        fill=(205, 215, 210)
    )

    draw_rtl(
        draw,
        (
            width - 80,
            1600
        ),
        "این گزارش صرفاً تحلیل بازار است و توصیه خرید یا فروش نیست.",
        tiny_font,
        (130, 150, 142)
    )

    image.save(
        DAILY_ANALYSIS_IMAGE,
        "JPEG",
        quality=96,
        optimize=True
    )

    return DAILY_ANALYSIS_IMAGE


async def send_daily_silver_analysis(
    client,
    target,
    state,
    rate,
    products
):
    if not rate or not products:
        return None

    tradingview_data = await get_tradingview_market_data()

    snapshot = build_market_analysis_snapshot(
        state,
        rate,
        products,
        get_saved_gold_ounce(state),
        tradingview_data
    )

    # مقدارهای تحلیل نموداری را با آخرین قیمت معتبر ساچمه ۹۹۵ هماهنگ می‌کنیم.
    # ممکن است سایت در یک اجرای موقت کلید shot_995 را برنگرداند؛ در این حالت
    # ابتدا state و سپس قیمت بسته‌ی ۱۰۰۰ گرمی ساچمه را به‌عنوان fallback می‌گیریم.
    shot_raw = (
        products.get("shot_995")
        if isinstance(products, dict)
        else None
    )

    if shot_raw is None:
        shot_raw = state.get("shot_995")

    if shot_raw is None and isinstance(products, dict):
        shot_package = products.get("shot_package")

        if shot_package is not None:
            try:
                shot_raw = float(shot_package) / 1000.0
            except (TypeError, ValueError):
                shot_raw = None

    if shot_raw is None:
        log.error(
            "DAILY SILVER ANALYSIS SKIPPED | "
            "shot_995 unavailable in products/state"
        )
        return None

    try:
        shot_current = float(shot_raw)
    except (TypeError, ValueError):
        log.error(
            "DAILY SILVER ANALYSIS SKIPPED | invalid shot_995=%r",
            shot_raw
        )
        return None

    snapshot.setdefault(
        "shot_995",
        {}
    )

    snapshot[
        "shot_995"
    ]["current"] = shot_current

    snapshot[
        "shot_995"
    ]["daily_change_percent"] = (
        daily_change_from_history(
            state,
            "shot_995",
            shot_current
        )
    )

    snapshot[
        "shot_995"
    ]["levels"] = local_levels_from_history(
        state,
        "shot_995",
        shot_current
    )

    chart_rows = daily_market_history(
        state,
        "shot_995"
    )

    if len(chart_rows) < 2:
        log.warning(
            "DAILY SILVER ANALYSIS SKIPPED | "
            "NOT ENOUGH LOCAL HISTORY | rows=%s",
            len(chart_rows)
        )
        return None

    snapshot[
        "chart_rows"
    ] = chart_rows

    analysis = await ai_market_analysis(
        snapshot
    )

    image = create_daily_silver_image(
        snapshot
    )

    stats = daily_stats(
        chart_rows
    )

    teaser = (
        "📊 تحلیل روزانه نقره | یزدان‌دوست\n"
        "━━━━━━━━━━━━━━\n\n"
        "🥈 نمودار واقعی حرکت ساچمه ۹۹۵ امروز، "
        "سقف، کف، شروع و پایان روز داخل تصویر مشخص شده است.\n\n"
        "🎯 حمایت و مقاومت + بررسی انس نقره و دلار تهران "
        "را در تحلیل زیر بخوانید."
    )

    caption = (
        teaser
        + "\n\n"
        + analysis
        + "\n\n"
        "📌 تحلیل شاخص‌های بازار بر اساس داده‌های به‌روز TradingView تهیه شده است."
        "\n\n"
        "📲 @yazdandoustsilver"
    )

    if len(caption) >= 4000:
        caption = (
            caption[:3950]
            + "\n\n📲 @yazdandoustsilver"
        )

    # کپشن روی خود عکس تلگرام حداکثر ۱۰۲۴ کاراکتر می‌پذیرد (برخلاف
    # پیام متنی که تا ۴۰۹۶ کاراکتر جواب می‌دهد؛ همان NEWS_MEDIA_CAPTION_LIMIT
    # که برای پست‌های خبری هم استفاده می‌شود). تحلیل هوش مصنوعی معمولاً
    # بلندتر از این حد است، پس اگر caption طولانی باشد عکس را با یک
    # کپشن کوتاه می‌فرستیم و متن کامل تحلیل را در پیام جداگانه‌ی بعدی
    # ارسال می‌کنیم تا با خطای MediaCaptionTooLongError مواجه نشویم.
    if len(caption) <= NEWS_MEDIA_CAPTION_LIMIT:

        message_id = await send_rate_post(
            client,
            target,
            image,
            caption
        )

    else:

        message_id = await send_rate_post(
            client,
            target,
            image,
            teaser[:NEWS_MEDIA_CAPTION_LIMIT]
        )

        await send_text_post(
            client,
            target,
            caption
        )

    try:
        daily_message = await client.get_messages(
            target,
            ids=message_id
        )

        if daily_message:
            await send_rubika_media(
                daily_message
            )

    except Exception as error:
        log.warning(
            "DAILY RUBIKA MEDIA SYNC FAILED: %s",
            error
        )

    mark_daily_sent(
        state,
        "daily_silver_visual_analysis"
    )

    save_state(
        state
    )

    log.info(
        "DAILY SILVER VISUAL ANALYSIS SENT | %s | rows=%s",
        message_id,
        len(chart_rows)
    )

    return message_id


def should_send_daily_silver_analysis(
    state
):
    now_minutes = current_minutes()

    start = (
        DAILY_SILVER_ANALYSIS_HOUR
        * 60
        +
        DAILY_SILVER_ANALYSIS_MINUTE
    )

    # قبل از ۲۱:۴۵ صبر می‌کنیم. بعد از آن دیگر سقف زمانی نداریم: هر
    # اجرای GitHub Actions که اولین اجرا بعد از ۲۱:۴۵ همان روز باشد
    # (چه ۲۲:۰۵ چه ۲۲:۳۰ چه ۲۳:۰۰) تحلیل را می‌فرستد. جلوگیری از تکرار
    # در همان روز و باز شدن دوباره در روز بعد کاملاً بر عهده‌ی
    # should_send_daily است، چون daily_key بر اساس تاریخ امروز کلید
    # می‌سازد و هر روز خودش ریست می‌شود.
    if now_minutes < start:
        return False

    return should_send_daily(
        state,
        "daily_silver_visual_analysis"
    )


# =========================================================
# WEEKLY SILVER ANALYSIS
# =========================================================

WEEKLY_SILVER_ANALYSIS_HOUR = 20
WEEKLY_SILVER_ANALYSIS_MINUTE = 0

WEEKLY_HISTORY_DAYS = 7

WEEKLY_ANALYSIS_IMAGE = BASE / "weekly_silver_analysis.jpg"
DAILY_SILVER_ANALYSIS_HOUR = 21
DAILY_SILVER_ANALYSIS_MINUTE = 45
DAILY_ANALYSIS_IMAGE = BASE / "daily_silver_analysis.jpg"
YAZDANDOUST_LOGO = BASE / "yazdandoust_logo.png"

ECONOMY_MINUTE_HOUR = 14
ECONOMY_MINUTE_MINUTE = 0

MARKET_RECAP_HOUR = 19
MARKET_RECAP_MINUTE = 45

TOMORROW_LOOK_HOUR = 20
TOMORROW_LOOK_MINUTE = 15


# =========================================================
# MARKET ANALYSIS / ALERT SETTINGS
# =========================================================

# هشدارهای تغییر قیمت فقط وقتی صادر می‌شوند که
# تغییر تجمعی از آخرین هشدار به این حد برسد.
SILVER_OUNCE_ALERT_STEP = 1.5
GOLD_OUNCE_ALERT_PERCENT = 5.0
DOLLAR_ALERT_PERCENT = 3.0
SHOT_ALERT_PERCENT = 5.0

MARKET_ANALYSIS_HOUR = 22
MARKET_ANALYSIS_MINUTE = 0
MARKET_ANALYSIS_INTERVAL_DAYS = 2

MARKET_HISTORY_LIMIT = 120

# نمادهای TradingView برای تحلیل روزانه بازار.
# تمام قیمت‌ها و شاخص‌های این گزارش مستقیماً از TradingView خوانده می‌شوند.
MARKET_TRADINGVIEW_SYMBOLS = {
    "silver": "OANDA:XAGUSD",
    "gold": "OANDA:XAUUSD",
    "dxy": "TVC:DXY",
    "oil": "TVC:USOIL",
    "us10y": "TVC:TNX",
    "sp500": "SP:SPX",
    "vix": "CBOE:VIX",
    "usd_irr": "FX_IDC:USDIRR",
}

# نمادهای Yahoo فقط برای بخش‌های قدیمی/هفتگی که هنوز به تاریخچه نیاز دارند.
MARKET_YAHOO_SYMBOLS = {
    "silver": "XAGUSD=X",
    "gold": "XAUUSD=X",
    "dxy": "DX-Y.NYB",
    "oil": "CL=F",
    "us10y": "^TNX",
    "sp500": "^GSPC",
    "vix": "^VIX",
}


# =========================================================
# NEWS SETTINGS
# =========================================================

NEWS_ENABLED = True

NEWS_TOTAL_MAX_PER_DAY = 10

NEWS_MIN_GAP_MINUTES = 15
NEWS_URGENT_MIN_GAP_MINUTES = 3

NEWS_HISTORY_LIMIT = 300

NEWS_MIN_IMPORTANCE = 6

NEWS_MAX_CANDIDATES_PER_SOURCE = 20

NEWS_AI_RETRY_DELAY_SECONDS = 4

NEWS_TITLE_SIMILARITY_LIMIT = 0.78

# حد تشخیص «یک خبر با نگارش متفاوت» بر پایه اشتراک کلمات امضای محتوا
# (is_duplicate_news). مقدار بین 0 و 1؛ هرچه بالاتر، سخت‌گیری کمتر.
NEWS_CONTENT_DUPLICATE_LIMIT = 0.60

# اخبار فوری/سیاسی حساس نباید فقط به‌خاطر بازنویسی از چند کانال
# به‌اشتباه حذف شوند. برای این گروه، تشخیص محتوایی سخت‌گیرانه‌تر است.
NEWS_URGENT_CONTENT_DUPLICATE_LIMIT = 0.72
NEWS_URGENT_STORY_DUPLICATE_LIMIT = 0.68
NEWS_URGENT_SHARED_WORDS = 18

URGENT_NEWS_KEYWORDS = [
    "ترامپ",
    "trump",
    "دونالد ترامپ",
    "donald trump",
    "جنگ",
    "درگیری",
    "حمله",
    "حمله هوایی",
    "موشک",
    "موشکی",
    "تنگه هرمز",
    "هرمز",
    "ایران",
    "اسرائیل",
    "آمریکا",
    "ایالات متحده",
    "تحریم",
    "آتش بس",
    "مذاکره",
    "کاخ سفید",
    "white house",
]


# =========================================================
# NEWS SOURCES
# =========================================================

ECONOMIC_SOURCES = [

    "https://www.tasnimnews.ir/fa/service/1407/",

    (
        "https://news.google.com/rss/search?"
        "q=%D8%A7%DB%8C%D8%B1%D8%A7%D9%86+%D8%A7%D9%82%D8%AA%D8%B5%D8%A7%D8%AF+%D8%AA%D8%AD%D8%B1%DB%8C%D9%85+%D8%AA%D9%88%D8%B1%D9%85+%D9%86%D8%B1%D8%AE+%D8%A8%D9%87%D8%B1%D9%87"
        "&hl=fa&gl=IR&ceid=IR:fa"
    ),

]


WORLD_SOURCES = [

    "https://www.reuters.com/world/middle-east/",

    "https://www.reuters.com/world/us/",

    "https://www.bbc.com/persian",

    (
        "https://news.google.com/rss/search?"
        "q=%D8%A7%DB%8C%D8%B1%D8%A7%D9%86+%D8%A2%D9%85%D8%B1%DB%8C%DA%A9%D8%A7+%D8%A7%D8%B3%D8%B1%D8%A7%D8%A6%DB%8C%D9%84+%D8%AC%D9%86%DA%AF"
        "&hl=fa&gl=IR&ceid=IR:fa"
    ),

]


# Public Telegram channels (scraped the same way SOURCE_CHANNEL is,
# via https://t.me/s/<channel>, no login required). Checked as a
# third-tier fallback after ECONOMIC_SOURCES and WORLD_SOURCES.
# Videos/photos in these channels' posts are picked up automatically
# when Telegram's public preview page embeds a direct file - not
# every post has one (large videos often only show a "view in app"
# link with no downloadable src), so it gracefully falls back to
# text-only when that happens.

# منابع اختصاصی اخبار ترامپ؛ این‌ها قبل از سایر منابع بررسی می‌شوند.
TRUMP_NEWS_CHANNELS = [
    "mrgold995",
    "goldonline2016",
    "iran_jahan_darlahze",
]

TRUMP_NEWS_KEYWORDS = [
    "ترامپ",
    "Trump",
    "ترامپ گفت",
    "ترامپ اعلام",
    "ترامپ خبر",
    "دونالد ترامپ",
    "Donald Trump",
    "کاخ سفید",
    "White House",
]

TELEGRAM_BREAKING_NEWS_CHANNELS = [
    "IR_Breakingnews",
]

TELEGRAM_ECONOMIC_NEWS_CHANNELS = [
    "goldonline2016",
    "iran_jahan_darlahze",
]

# Channels whose photo attachments are consistently just the
# channel's own self-promo/branding image rather than actual news
# photos, so the photo is never attached for these - text (and
# video, when the channel has real footage) still goes through
# normally.
TELEGRAM_SKIP_PHOTO_CHANNELS = {

    "IR_Breakingnews",

}


ECONOMIC_KEYWORDS = [

    "نقره",
    "بانک مرکزی",
    "مرکز مبادله",
    "تورم",
    "نرخ بهره",
    "فدرال رزرو",
    "بازار جهانی",
    "اقتصاد",
    "نفت",
    "بورس",
    "بورس کالا",
    "نقدینگی",
    "تحریم",
    "صادرات",
    "واردات",
    "سرمایه‌گذاری",
    "سرمایه گذاری",
    "فلزات گرانبها",
    "فلزات گران بها",

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
    "کاخ سفید",
    "White House",
    "روسیه",
    "Russia",
    "اوکراین",
    "Ukraine",

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
    "مذاکرات مهم",
    "تصمیم مهم",
    "تحریم جدید",
    "حمله هوایی",
    "حمله موشکی",
    "درگیری",
    "تنش",

]


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
    "قیمت امروز طلا",
    "قیمت امروز سکه",
    "قیمت امروز دلار",
    "قیمت لحظه ای طلا",
    "قیمت لحظه‌ای طلا",
    "قیمت لحظه ای دلار",
    "قیمت لحظه‌ای دلار",

]


# =========================================================
# BLOCKED RATE / GOLD / CURRENCY NEWS
# =========================================================

BLOCKED_RATE_GOLD_NEWS_KEYWORDS = [

    "دلار",
    "دلار تهران",
    "دلار آزاد",
    "دلار توافقی",
    "دلار نیمایی",
    "دلار مبادله‌ای",
    "دلار مبادله ای",
    "دلار صرافی",
    "دلار دولتی",
    "دلار آمریکا",
    "دلار امریکا",
    "قیمت دلار",
    "نرخ دلار",
    "قیمت لحظه‌ای دلار",
    "قیمت لحظه ای دلار",
    "نرخ لحظه‌ای دلار",
    "نرخ لحظه ای دلار",
    "ارزش دلار",
    "روند دلار",
    "بازار دلار",
    "دلار گران شد",
    "دلار ارزان شد",
    "دلار افزایش یافت",
    "دلار کاهش یافت",
    "دلار صعود کرد",
    "دلار سقوط کرد",

    "usd",
    "us dollar",
    "dollar",
    "dollar rate",
    "dollar price",
    "usd/irr",
    "usd/ir",

    "نرخ ارز",
    "قیمت ارز",
    "بازار ارز",
    "ارز آزاد",
    "ارز دولتی",
    "ارز مبادله‌ای",
    "ارز مبادله ای",
    "ارز توافقی",
    "ارز نیمایی",
    "ارز خارجی",
    "ارزش ارز",
    "تغییر نرخ ارز",
    "افزایش نرخ ارز",
    "کاهش نرخ ارز",
    "نوسان ارز",
    "نوسانات ارز",
    "قیمت ارزها",
    "نرخ ارزها",
    "بازار ارزها",
    "نرخ تبدیل ارز",
    "تبدیل ارز",

    "foreign exchange",
    "exchange rate",
    "exchange rates",
    "forex",
    "fx market",
    "currency rate",
    "currency rates",
    "currency exchange",

    "یورو",
    "قیمت یورو",
    "نرخ یورو",
    "یورو تهران",
    "یورو آزاد",
    "یورو مبادله‌ای",
    "یورو مبادله ای",
    "euro",
    "eur",
    "eur/irr",

    "پوند",
    "قیمت پوند",
    "نرخ پوند",
    "پوند انگلیس",
    "پوند انگلستان",
    "gbp",
    "british pound",
    "pound sterling",

    "درهم",
    "قیمت درهم",
    "نرخ درهم",
    "درهم امارات",
    "درهم مبادله‌ای",
    "درهم مبادله ای",
    "aed",
    "uae dirham",

    "لیر",
    "قیمت لیر",
    "نرخ لیر",
    "لیر ترکیه",
    "روبل",
    "قیمت روبل",
    "نرخ روبل",
    "روپیه",
    "فرانک",
    "یوان",
    "قیمت یوان",
    "نرخ یوان",
    "yuan",
    "yen",
    "ruble",
    "lira",

    "طلا",
    "طلای ۱۸",
    "طلای 18",
    "طلای ۲۴",
    "طلای 24",
    "طلای آبشده",
    "طلای آب شده",
    "گرم طلا",
    "گرم طلای ۱۸",
    "گرم طلای 18",
    "قیمت طلا",
    "نرخ طلا",
    "قیمت طلای ۱۸",
    "قیمت طلای 18",
    "قیمت طلای آبشده",
    "قیمت طلای آب شده",
    "قیمت طلای جهانی",
    "نرخ طلای جهانی",
    "بازار طلا",
    "بازار طلای ایران",
    "بازار طلای جهانی",
    "طلای جهانی",
    "اونس طلا",
    "انس طلا",
    "اونس جهانی طلا",
    "انس جهانی طلا",
    "قیمت اونس طلا",
    "نرخ اونس طلا",
    "طلای جهانی افزایش",
    "طلای جهانی کاهش",

    "gold price",
    "gold rate",
    "gold market",
    "gold ounce",
    "gold futures",
    "spot gold",
    "xau",
    "xau/usd",

    "سکه",
    "سکه امامی",
    "سکه بهار آزادی",
    "نیم سکه",
    "ربع سکه",
    "سکه گرمی",
    "قیمت سکه",
    "نرخ سکه",
    "حباب سکه",
    "بازار سکه",
    "قیمت امروز سکه",
    "قیمت لحظه‌ای سکه",
    "قیمت لحظه ای سکه",

    "coin price",
    "coin market",

]


# =========================================================
# IMAGE COORDINATES
# =========================================================

NUMBER_BOXES = [

    (505, 585, 900, 665),

    (505, 750, 900, 830),

    (505, 915, 900, 995),

    (505, 1075, 900, 1155),

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
                "application/rss+xml;q=0.9,"
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


def parse_public_messages_with_media(
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

        video_url = None

        video_node = node.select_one(
            "video.tgme_widget_message_video"
        )

        if video_node:

            video_url = video_node.get(
                "src"
            )

        photo_url = None

        photo_node = node.select_one(
            "a.tgme_widget_message_photo_wrap"
        )

        if photo_node:

            style = photo_node.get(
                "style",
                ""
            )

            match = re.search(
                r"url\(['\"]?(.*?)['\"]?\)",
                style
            )

            if match:

                photo_url = match.group(1)

        result.append({

            "message_id": message_id,
            "text": text,
            "video_url": video_url,
            "photo_url": photo_url,

        })

    result.sort(
        key=lambda item: item["message_id"],
        reverse=True
    )

    return result


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
# GOLD OUNCE
# =========================================================

def parse_gold_ounce(
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

    # -----------------------------------------
    # روش اول:
    # پیدا کردن عبارت «انس طلا» و عدد نزدیک آن
    # -----------------------------------------

    patterns = [

        r"انس\s*طلا"
        r".{0,150}?"
        r"(?:نرخ\s*فعلی|قیمت|نرخ)?"
        r"\s*:?\s*"
        r"([\d,٬.]+)",

        r"انس\s*طلا"
        r".{0,100}?"
        r"([\d,٬.]+)",

    ]

    for pattern in patterns:

        matches = re.finditer(
            pattern,
            text,
            re.IGNORECASE
        )

        for match in matches:

            candidate_text = match.group(1)

            candidate = decimal_value(
                candidate_text
            )

            if candidate is None:

                continue

            if (
                1000 <= candidate <= 10000
            ):

                log.info(
                    "GOLD OUNCE FOUND = %.2f",
                    candidate
                )

                return float(candidate)

    # -----------------------------------------
    # روش دوم:
    # بررسی متادیتا و title
    # -----------------------------------------

    meta_selectors = [

        "meta[property='og:title']",
        "meta[name='twitter:title']",
        "title"

    ]

    for selector in meta_selectors:

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

        match = re.search(
            r"([\d,٬.]{4,})",
            value
        )

        if match:

            candidate = decimal_value(
                match.group(1)
            )

            if candidate is not None:

                if (
                    1000 <= candidate <= 10000
                ):

                    log.info(
                        "GOLD OUNCE FOUND FROM META = %.2f",
                        candidate
                    )

                    return float(candidate)

    return None


def get_gold_ounce_sync():

    html = http_get(
        GOLD_OUNCE_URL,
        timeout=30
    )

    ounce = parse_gold_ounce(
        html
    )

    if ounce is None:

        raise RuntimeError(
            "قیمت انس طلا از منبع تعیین‌شده پیدا نشد."
        )

    return ounce


async def get_gold_ounce():

    last_error = None

    for attempt in range(
        1,
        4
    ):

        try:

            return await asyncio.to_thread(
                get_gold_ounce_sync
            )

        except Exception as error:

            last_error = error

            log.warning(
                "GOLD OUNCE ATTEMPT %s/3 FAILED: %s",
                attempt,
                error
            )

            if attempt < 3:

                await asyncio.sleep(
                    3
                )

    raise RuntimeError(
        f"خطا در دریافت انس طلا: {last_error}"
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
            "محصول دقیق شمش ندیر پیدا نشد."
        )

    nader_package = (
        get_current_price_from_card(
            nader_card
        )
    )

    if nader_package is None:

        raise RuntimeError(
            "قیمت شمش ندیر پیدا نشد."
        )

    # TGH Telegram is the primary source for the 995 shot price because
    # its rate table is updated more frequently than the website.
    tgh_shot_price, tgh_message_id = (
        find_latest_tgh_shot_995_price()
    )

    if tgh_shot_price is not None:
        shot_995_per_gram = (
            tgh_shot_price
        )
        shot_package = (
            tgh_shot_price * 1000
        )
        log.info(
            "SHOT 995 SOURCE = TGH TELEGRAM | per_gram=%s | message=%s",
            tgh_shot_price,
            tgh_message_id,
        )
    else:
        # Safety fallback: keep the website value if the public TGH table
        # cannot be reached or OCR cannot read it in a particular run.
        shot_995_per_gram = (
            shot_package / 1000
        )
        log.warning(
            "SHOT 995 TGH SOURCE UNAVAILABLE -> WEBSITE FALLBACK | per_gram=%s",
            shot_995_per_gram,
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

        "shot_price_source":
            "tghsilver",

        "shot_source_message_id":
            (
                int(tgh_message_id)
                if tgh_message_id is not None
                else None
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

    # Keep the existing Mashhad source as the primary source.
    # If it is unavailable, immediately fall back to TGJU live rates
    # instead of silently losing the 11:00 / 15:00 / 18:00 report.
    market = await asyncio.to_thread(
        find_latest_mashhad_market
    )

    if market is not None:

        market[
            "source_name"
        ] = "اتحادیه مشهد"

        return market

    log.warning(
        "MASHHAD UNION UNAVAILABLE | FALLING BACK TO TGJU"
    )

    tgju_market = await asyncio.to_thread(
        find_latest_tgju_market
    )

    if tgju_market is not None:

        tgju_market[
            "source_name"
        ] = "TGJU"

    return tgju_market


def parse_tgju_current_price(
    html,
    asset
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

    if asset == "gold":

        title_pattern = (
            r"طلای\s*18\s*عیار"
            r".{0,300}?"
            r"نرخ\s*فعلی\s*[:：]*\s*"
            r"([\d,٬]{7,})"
        )

    else:

        title_pattern = (
            r"سکه\s*امامی"
            r".{0,300}?"
            r"نرخ\s*فعلی\s*[:：]*\s*"
            r"([\d,٬]{8,})"
        )

    match = re.search(
        title_pattern,
        text,
        re.IGNORECASE
    )

    if match is None:

        # Fallback for the table-style TGJU pages where the first
        # occurrence is shown as a live price rather than "نرخ فعلی".
        if asset == "gold":

            fallback_pattern = (
                r"طلای\s*18\s*عیار\s*/?\s*750"
                r".{0,180}?"
                r"([\d,٬]{7,})"
            )

        else:

            fallback_pattern = (
                r"سکه\s*امامی"
                r".{0,180}?"
                r"([\d,٬]{8,})"
            )

        match = re.search(
            fallback_pattern,
            text,
            re.IGNORECASE
        )

    if match is None:

        return None

    value_rial = integer_value(
        match.group(1)
    )

    if value_rial is None:

        return None

    # TGJU reports these domestic prices in rial.
    value_toman = int(
        round(
            value_rial / 10
        )
    )

    if asset == "gold":

        if not (
            1_000_000
            <= value_toman
            <= 1_000_000_000
        ):

            return None

    else:

        if not (
            100_000_000
            <= value_toman
            <= 10_000_000_000
        ):

            return None

    return value_toman


def find_latest_tgju_market():

    try:

        gold_html = http_get(
            TGJU_GOLD_URL,
            timeout=30
        )

        coin_html = http_get(
            TGJU_COIN_URL,
            timeout=30
        )

        gold = parse_tgju_current_price(
            gold_html,
            "gold"
        )

        coin = parse_tgju_current_price(
            coin_html,
            "coin"
        )

        if gold is None:

            log.warning(
                "TGJU GOLD PRICE NOT FOUND"
            )

        if coin is None:

            log.warning(
                "TGJU COIN PRICE NOT FOUND"
            )

        if (
            gold is None
            or
            coin is None
        ):

            return None

        result = {

            "gold_18_mashhad":
                int(gold),

            "coin_imami":
                int(coin),

            "source_url":
                TGJU_GOLD_URL,

            "coin_source_url":
                TGJU_COIN_URL,

        }

        log.info(
            "TGJU LIVE | GOLD=%s TOMAN | COIN=%s TOMAN",
            gold,
            coin
        )

        return result

    except Exception as error:

        log.exception(
            "TGJU MARKET ERROR: %s",
            error
        )

    return None


# =========================================================
# ECONOMIC CALENDAR
# =========================================================

ECONOMIC_CALENDAR_EVENT_FA = {

    "cpi": "تورم مصرف‌کننده (CPI)",
    "core cpi": "تورم هسته (Core CPI)",
    "ppi": "تورم تولیدکننده (PPI)",
    "fomc": "نشست فدرال رزرو (FOMC)",
    "fed chair": "سخنرانی رئیس فدرال رزرو",
    "nonfarm payrolls": "اشتغال غیرکشاورزی آمریکا (NFP)",
    "unemployment claims": "بیمه بیکاری آمریکا",
    "unemployment rate": "نرخ بیکاری",
    "gdp": "تولید ناخالص داخلی (GDP)",
    "retail sales": "خرده‌فروشی",
    "pmi": "شاخص مدیران خرید (PMI)",
    "interest rate": "نرخ بهره",
    "ecb president": "سخنرانی رئیس بانک مرکزی اروپا",
    "employment change": "تغییرات اشتغال",

}


def economic_event_persian_hint(
    title
):

    normalized = title.lower()

    for key, fa in ECONOMIC_CALENDAR_EVENT_FA.items():

        if key in normalized:

            return fa

    return None


def parse_economic_calendar_xml(
    xml_text
):

    events = []

    # ElementTree refuses to parse a Python str that still carries an
    # XML encoding declaration (e.g. this feed ships
    # encoding="windows-1252"), even though requests already decoded
    # it to str. Strip the declaration line before parsing.
    xml_text = re.sub(
        r"^\s*<\?xml[^>]*\?>",
        "",
        xml_text,
        count=1
    )

    try:

        root = ET.fromstring(
            xml_text
        )

    except ET.ParseError as error:

        log.warning(
            "ECONOMIC CALENDAR PARSE FAILED: %s",
            error
        )

        return events

    for node in root.findall("event"):

        title = (
            node.findtext(
                "title",
                default=""
            )
            or
            ""
        ).strip()

        country = (
            node.findtext(
                "country",
                default=""
            )
            or
            ""
        ).strip()

        date_text = (
            node.findtext(
                "date",
                default=""
            )
            or
            ""
        ).strip()

        time_text = (
            node.findtext(
                "time",
                default=""
            )
            or
            ""
        ).strip()

        impact = (
            node.findtext(
                "impact",
                default=""
            )
            or
            ""
        ).strip()

        forecast = (
            node.findtext(
                "forecast",
                default=""
            )
            or
            ""
        ).strip()

        previous = (
            node.findtext(
                "previous",
                default=""
            )
            or
            ""
        ).strip()

        dt_tehran = None

        try:

            dt_source = datetime.strptime(
                f"{date_text} {time_text}",
                "%m-%d-%Y %I:%M%p"
            ).replace(
                tzinfo=ECONOMIC_CALENDAR_SOURCE_TZ
            )

            dt_tehran = dt_source.astimezone(
                IRAN_TZ
            )

        except ValueError:

            # Some rows have no clock time (e.g. "All Day", bank
            # holidays) - keep the event but without a precise time.
            dt_tehran = None

        events.append({

            "title": title,
            "country": country,
            "impact": impact,
            "forecast": forecast,
            "previous": previous,
            "datetime": dt_tehran,

        })

    return events


def find_weekly_us_calendar_events(
    xml_text
):

    events = parse_economic_calendar_xml(
        xml_text
    )

    relevant = [

        event
        for event in events

        if (

            event["country"] == "USD"

            and

            event["impact"] in (
                "High",
                "Medium"
            )

        )

    ]

    relevant.sort(
        key=lambda event: (
            event["datetime"]
            if event["datetime"] is not None
            else datetime.max.replace(
                tzinfo=IRAN_TZ
            )
        )
    )

    return relevant


async def get_weekly_economic_calendar():

    try:

        xml_text = await asyncio.to_thread(
            http_get,
            ECONOMIC_CALENDAR_URL
        )

    except Exception as error:

        log.warning(
            "ECONOMIC CALENDAR FETCH FAILED: %s",
            error
        )

        return None

    if not xml_text:

        return None

    return find_weekly_us_calendar_events(
        xml_text
    )


def make_economic_calendar_message(
    events
):

    if not events:

        return None

    lines = [

        "🗓 تقویم اقتصادی این هفته",
        "━━━━━━━━━━━━━━",
        "",
        "رویدادهای مهم آمریکا که می‌تونن روی",
        "قیمت دلار، طلا و نقره اثر بذارن:",
        "",

    ]

    for event in events:

        if event["datetime"] is not None:

            weekday = WEEKDAYS_FA[
                event["datetime"].weekday()
            ]

            time_label = (
                f"{weekday} "
                f"{event['datetime'].strftime('%H:%M')}"
            )

        else:

            time_label = "زمان نامشخص"

        impact_icon = (
            "🔴"
            if event["impact"] == "High"
            else "🟠"
        )

        hint = economic_event_persian_hint(
            event["title"]
        )

        title_line = (
            f"{event['title']} ({hint})"
            if hint
            else event["title"]
        )

        lines.append(
            f"{impact_icon} {time_label} | {title_line}"
        )

    lines.append("")
    lines.append(
        "⏰ ساعت‌ها به وقت تهران است."
    )
    lines.append(
        channel_footer()
    )

    text = "\n".join(lines)

    return text if len(text) < 4000 else None


# =========================================================
# GOLD 18 BUBBLE
# =========================================================

def calculate_gold_18_bubble(
    rate,
    gold_ounce,
    gold_18_price
):

    if not gold_ounce:
        return None

    intrinsic = (

        gold_ounce
        * rate["tehran"]
        / OUNCE_GRAMS
        * GOLD_18_FINENESS

    )

    bubble = (
        gold_18_price
        - intrinsic
    )

    bubble_percent = 0

    if intrinsic > 0:

        bubble_percent = (
            bubble
            /
            intrinsic
            *
            100
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
            ),

        "bubble_percent":
            float(
                bubble_percent
            )

    }


# =========================================================
# COIN BUBBLE
# =========================================================

def calculate_coin_bubble(
    rate,
    coin_price,
    gold_ounce
):

    if (
        gold_ounce is None
        or float(gold_ounce) <= 0
        or rate.get("tehran") is None
    ):
        return None

    intrinsic = (

        float(gold_ounce)
        * float(rate["tehran"])
        / OUNCE_GRAMS
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
# CHANNEL FOOTER
# =========================================================

def channel_footer():
    return ""


# =========================================================
# PRICE CAPTION
# =========================================================

def make_caption():

    return (

        f"📅 تاریخ: {iran_date_string()}\n"
        f"🕐 آخرین بروزرسانی: {iran_time_string()}\n\n"

        "🥈 قیمت و معاملات نقره یزدان‌دوست\n\n"

        "▫️ خرید و فروش ساچمه نقره ۹۹۵\n"
        "▫️ خرید و فروش شمش نقره ۹۹۹.۹\n"
        "▫️ خرید نقره مستعمل\n"
        "▫️ خرید شمش‌های معتبر و قانونی\n"
        "▫️ نرخ خرید فاکتورهای مجموعه طبق روال همیشگی\n\n"

        "📦 معاملات بالای ۲ کیلو\n"
        "جهت استعلام نرخ ویژه، تماس بگیرید:\n"
        f"📞 {PHONE}\n\n"

        "💬 خرید، فروش و استعلام قیمت:\n"
        f"{TELEGRAM_ID}\n\n"

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
        "کدخبر:",
        "©",
        "Copyright",

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

    return "\n\n".join(
        clean
    ).strip()


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


def parse_news_rss(
    soup,
    base_url
):

    result = []

    for item in soup.select(
        "item"
    ):

        title_node = item.select_one(
            "title"
        )

        link_node = item.select_one(
            "link"
        )

        description_node = item.select_one(
            "description"
        )

        if not title_node or not link_node:

            continue

        title = normalize_fa(
            title_node.get_text(
                " ",
                strip=True
            )
        )

        url = (
            link_node.get_text(
                " ",
                strip=True
            )
            or
            link_node.get(
                "href",
                ""
            )
        )

        url = urljoin(
            base_url,
            url.strip()
        )

        description = ""

        if description_node:

            description = normalize_fa(
                description_node.get_text(
                    " ",
                    strip=True
                )
            )

        if (
            len(title) < 10
            or
            not url
        ):

            continue

        result.append({

            "url":
                url,

            "title":
                title,

            "description":
                description

        })

    return result


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

    rss_items = parse_news_rss(
        soup,
        base_url
    )

    for item in rss_items:

        if item["url"] in seen:

            continue

        seen.add(
            item["url"]
        )

        result.append(
            item
        )

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
                "#",
                "javascript:"

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
                title,

            "description":
                ""

        })

        if len(result) >= (
            NEWS_MAX_CANDIDATES_PER_SOURCE
        ):

            break

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

        if is_valid_news_body(
            paragraphs
        ):

            body = build_news_text(
                paragraphs
            )

            if len(body) >= 150:

                return {

                    "url":
                        item["url"],

                    "title":
                        title,

                    "text":
                        body

                }

    except Exception as error:

        log.warning(

            "NEWS ARTICLE ERROR | %s | %s",

            item.get(
                "url",
                ""
            ),

            error

        )

    fallback_description = normalize_fa(

        item.get(
            "description",
            ""
        )

    )

    if len(
        fallback_description
    ) >= 150:

        return {

            "url":
                item["url"],

            "title":
                normalize_fa(
                    item.get(
                        "title",
                        ""
                    )
                ),

            "text":
                fallback_description

        }

    return None


def keyword_match(
    text,
    keywords
):

    text = normalize_fa(
        text
    ).lower()

    for keyword in keywords:

        keyword = normalize_fa(
            keyword
        ).lower().strip()

        if not keyword:
            continue

        # Prevent short keywords such as «ین» from matching inside
        # unrelated words such as «بزرگترین». Also avoid accidental
        # substring matches for Persian/Latin words while preserving
        # normal phrase matching (e.g. «قیمت دلار»).
        pattern = (
            r"(?<![\w\u0600-\u06FF])"
            + re.escape(keyword)
            + r"(?![\w\u0600-\u06FF])"
        )

        if re.search(pattern, text, flags=re.IGNORECASE):
            return True

    return False


def keyword_hits(
    text,
    keywords
):

    # Use the same boundary-aware matching as keyword_match so short
    # terms cannot create false positives inside unrelated words.
    return sum(
        1
        for keyword in keywords
        if keyword_match(text, [keyword])
    )


def normalize_news_title(
    text
):

    text = normalize_fa(
        text
    ).lower()

    text = re.sub(
        r"[^\w\sآ-ی]",
        " ",
        text,
        flags=re.UNICODE
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


def news_titles_similar(
    title_a,
    title_b
):

    a = normalize_news_title(
        title_a
    )

    b = normalize_news_title(
        title_b
    )

    if not a or not b:

        return False

    if a == b:

        return True

    ratio = SequenceMatcher(
        None,
        a,
        b
    ).ratio()

    return (
        ratio >= NEWS_TITLE_SIMILARITY_LIMIT
    )


def news_content_signature(article):
    """Create a compact normalized fingerprint for rewritten/cross-channel news."""
    if not isinstance(article, dict):
        return ""

    parts = [
        str(article.get("title", "") or ""),
        str(article.get("description", "") or ""),
        str(article.get("text", "") or ""),
    ]

    text = normalize_news_title(" ".join(parts))

    # Ignore very short tokens; they create noisy matches between unrelated news.
    words = [
        word
        for word in text.split()
        if len(word) >= 3
    ]

    return " ".join(words[:180])


def is_urgent_news(article):
    """Identify high-priority breaking/political/security news."""
    if not isinstance(article, dict):
        return False

    source_channel = str(
        article.get("source_channel", "") or ""
    ).strip().lstrip("@")

    if source_channel in TRUMP_NEWS_CHANNELS:
        return True

    combined = " ".join(
        str(article.get(key, "") or "")
        for key in (
            "title",
            "source_title",
            "text",
            "source_text",
            "description",
        )
    )

    return keyword_match(
        combined,
        URGENT_NEWS_KEYWORDS
    )


def is_duplicate_news(
    article,
    history_titles,
    history_fingerprints=None,
    history_urls=None
):

    history_titles = history_titles or []
    history_fingerprints = history_fingerprints or []
    history_urls = history_urls or []

    title = article.get("title", "")
    url = str(article.get("url", "") or "").strip()
    urgent = is_urgent_news(article)

    # Exact source URL/message identity is always a duplicate.
    # FIX: news_history stores URLs, so compare the URL with history_urls
    # rather than the title history. This prevents the same Telegram post
    # from being sent again after a manual Workflow rerun.
    if url and url in history_urls:
        log.info("DUPLICATE NEWS SKIPPED | URL | %s", url)
        return True

    # Same or very-near title is still a duplicate. This prevents
    # repeated polling of the exact same post.
    for old_title in history_titles:
        if news_titles_similar(title, old_title):
            log.info(
                "DUPLICATE NEWS SKIPPED | TITLE | %s | OLD=%s",
                title,
                old_title
            )
            return True

    # Same story with a different title/rewrite.
    current_signature = news_content_signature(article)

    if current_signature:
        current_words = set(current_signature.split())

        for old_signature in history_fingerprints:
            old_words = set(str(old_signature).split())

            if not old_words:
                continue

            similarity = len(
                current_words & old_words
            ) / max(
                1,
                len(current_words | old_words)
            )

            # For urgent news (Trump/Iran/war/Hormuz/etc.), do not
            # reject a genuinely new update merely because several
            # channels used similar wording. Exact URL/title duplicates
            # were already blocked above.
            content_limit = (
                NEWS_URGENT_CONTENT_DUPLICATE_LIMIT
                if urgent
                else NEWS_CONTENT_DUPLICATE_LIMIT
            )

            if similarity >= content_limit:
                log.info(
                    "DUPLICATE NEWS SKIPPED | CONTENT=%.3f | "
                    "URGENT=%s | %s",
                    similarity,
                    urgent,
                    title
                )
                return True

            shared = len(current_words & old_words)

            if urgent:
                # A breaking-news rewrite must be substantially closer
                # before it is treated as the same story.
                if (
                    shared >= NEWS_URGENT_SHARED_WORDS
                    and
                    similarity >= NEWS_URGENT_STORY_DUPLICATE_LIMIT
                ):
                    log.info(
                        "DUPLICATE NEWS SKIPPED | URGENT STORY=%.3f | "
                        "SHARED=%s | %s",
                        similarity,
                        shared,
                        title
                    )
                    return True
            else:
                # Existing behaviour for ordinary news.
                if shared >= 10 and similarity >= 0.50:
                    log.info(
                        "DUPLICATE NEWS SKIPPED | STORY=%.3f | "
                        "SHARED=%s | %s",
                        similarity,
                        shared,
                        title
                    )
                    return True

    return False

def is_blocked_rate_gold_news(
    article
):

    if not article:

        return False

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

    description = normalize_fa(
        article.get(
            "description",
            ""
        )
    )

    combined = (
        title
        + " "
        + description
        + " "
        + text
    )

    title_hits = keyword_hits(
        title,
        BLOCKED_RATE_GOLD_NEWS_KEYWORDS
    )

    first_part = (
        text[:1200]
    )

    body_hits = keyword_hits(
        first_part,
        BLOCKED_RATE_GOLD_NEWS_KEYWORDS
    )

    combined_hits = keyword_hits(
        combined[:3000],
        BLOCKED_RATE_GOLD_NEWS_KEYWORDS
    )

    if title_hits >= 1:

        log.info(
            "BLOCKED RATE/GOLD NEWS | TITLE MATCH=%s | %s",
            title_hits,
            title
        )

        return True

    if body_hits >= 2:

        log.info(
            "BLOCKED RATE/GOLD NEWS | BODY MATCH=%s | %s",
            body_hits,
            title
        )

        return True

    rate_terms = [

        "نرخ",
        "قیمت",
        "ارزش",
        "افزایش",
        "کاهش",
        "صعود",
        "سقوط",
        "گران",
        "ارزان",
        "بازار",

    ]

    asset_terms = [

        "دلار",
        "ارز",
        "یورو",
        "پوند",
        "درهم",
        "طلا",
        "سکه",
        "gold",
        "dollar",
        "currency",
        "euro",
        "pound",

    ]

    has_rate_term = keyword_match(
        combined[:3000],
        rate_terms
    )

    has_asset_term = keyword_match(
        combined[:3000],
        asset_terms
    )

    if (
        has_rate_term
        and
        has_asset_term
    ):

        log.info(
            "BLOCKED RATE/GOLD NEWS | RATE+ASSET | %s",
            title
        )

        return True

    if combined_hits >= 3:

        log.info(
            "BLOCKED RATE/GOLD NEWS | COMBINED MATCH=%s | %s",
            combined_hits,
            title
        )

        return True

    return False


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
        + text[:800]
    )

    title_price_only = keyword_match(
        title,
        PRICE_ONLY_NEWS_KEYWORDS
    )

    body_has_real_context = keyword_match(

        text,

        [

            "بانک مرکزی",
            "فدرال رزرو",
            "نرخ بهره",
            "تورم",
            "تحریم",
            "جنگ",
            "مذاکرات",
            "بازار جهانی",
            "تصمیم",
            "عرضه",
            "تقاضا",
            "صادرات",
            "واردات",
            "بورس",
            "اقتصاد",
            "سیاست",
            "تنش",
            "درگیری",
            "آتش بس",
            "حمله",
            "تحریم جدید",

        ]

    )

    if (
        title_price_only
        and
        not body_has_real_context
    ):

        return True

    if (
        keyword_match(
            title,
            PRICE_ONLY_NEWS_KEYWORDS
        )
        and
        len(text) < 500
        and
        not body_has_real_context
    ):

        return True

    return False


def calculate_news_importance(
    article,
    keywords
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
        + text
    )

    score = 0

    title_hits = keyword_hits(
        title,
        keywords
    )

    body_hits = keyword_hits(
        text[:2500],
        keywords
    )

    score += min(
        title_hits * 3,
        9
    )

    score += min(
        body_hits * 2,
        8
    )

    if keyword_match(
        combined,
        URGENT_KEYWORDS
    ):

        score += 4

    important_terms = [

        "بانک مرکزی",
        "فدرال رزرو",
        "نرخ بهره",
        "تورم",
        "تحریم جدید",
        "آتش بس",
        "مذاکرات",
        "حمله",
        "جنگ",
        "درگیری",
        "تنگه هرمز",
        "Trump",
        "ترامپ",
        "نقره",

    ]

    important_hits = keyword_hits(
        combined,
        important_terms
    )

    score += min(
        important_hits,
        6
    )

    if len(text) >= 700:

        score += 1

    if len(text) >= 1200:

        score += 1

    return score


def get_candidate_from_sources(
    sources,
    keywords,
    history,
    history_titles=None
):

    history = set(

        str(x)

        for x in history

    )

    if history_titles is None:

        history_titles = []

    candidates = []

    seen_urls = set()

    seen_titles = []

    for source in sources:

        items = fetch_news_index(
            source
        )

        if not items:

            continue

        log.info(
            "NEWS SOURCE FOUND %s ITEMS | %s",
            len(items),
            source
        )

        checked = 0

        for item in items:

            if checked >= NEWS_MAX_CANDIDATES_PER_SOURCE:

                break

            checked += 1

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

            if is_blocked_rate_gold_news(
                item
            ):

                log.info(
                    "BLOCKED RATE/GOLD INDEX ITEM | %s",
                    title
                )

                continue

            if is_duplicate_news(
                item,
                history_titles,
                history_urls=history
            ):

                continue

            if any(

                news_titles_similar(
                    title,
                    old_title
                )

                for old_title in seen_titles

            ):

                continue

            description = item.get(
                "description",
                ""
            )

            title_relevant = keyword_match(
                title,
                keywords
            )

            description_relevant = keyword_match(
                description,
                keywords
            )

            if not (
                title_relevant
                or
                description_relevant
            ):

                continue

            article = fetch_news_article(
                item
            )

            if not article:

                continue

            if is_blocked_rate_gold_news(
                article
            ):

                log.info(
                    "BLOCKED RATE/GOLD ARTICLE | %s",
                    article["title"]
                )

                continue

            if is_duplicate_news(
                article,
                history_titles,
                history_urls=history
            ):

                continue

            if any(

                news_titles_similar(
                    article["title"],
                    old_title
                )

                for old_title in seen_titles

            ):

                continue

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

            importance = calculate_news_importance(
                article,
                keywords
            )

            log.info(

                "NEWS CANDIDATE | score=%s | %s",

                importance,

                article["title"]

            )

            if (
                importance
                <
                NEWS_MIN_IMPORTANCE
            ):

                log.info(

                    "NEWS LOW IMPORTANCE SKIPPED | score=%s | %s",

                    importance,

                    article["title"]

                )

                continue

            article[
                "importance"
            ] = importance

            candidates.append(
                article
            )

            seen_titles.append(
                article["title"]
            )

    if not candidates:

        return None

    candidates.sort(

        key=lambda x:
            (
                int(
                    x.get(
                        "importance",
                        0
                    )
                ),

                len(
                    x.get(
                        "text",
                        ""
                    )
                )

            ),

        reverse=True

    )

    selected = candidates[0]

    log.info(

        "BEST NEWS SELECTED | score=%s | %s",

        selected.get(
            "importance",
            0
        ),

        selected.get(
            "title",
            ""
        )

    )

    return selected


async def get_economic_news(
    history,
    history_titles=None
):

    return await asyncio.to_thread(

        get_candidate_from_sources,

        ECONOMIC_SOURCES,

        ECONOMIC_KEYWORDS,

        history,

        history_titles

    )


async def get_world_news(
    history,
    history_titles=None
):

    return await asyncio.to_thread(

        get_candidate_from_sources,

        WORLD_SOURCES,

        WORLD_KEYWORDS,

        history,

        history_titles

    )


# =========================================================
# TELEGRAM CHANNEL NEWS
# =========================================================

def telegram_message_to_article(
    channel,
    item
):

    text = clean_text(
        item.get(
            "text",
            ""
        )
    )

    if not text:

        return None

    first_line = text.split(
        "\n",
        1
    )[0].strip()

    title = (
        first_line[:120]
        if first_line
        else text[:120]
    )

    photo_url = item.get("photo_url")

    if channel in TELEGRAM_SKIP_PHOTO_CHANNELS:

        photo_url = None

    return {

        "title": title,
        "text": text,
        "description": text[:200],

        "url":
            f"https://t.me/{channel}/"
            f"{item['message_id']}",

        "video_url": item.get("video_url"),
        "photo_url": photo_url,
        "source_channel": channel,
        "source_message_id": item.get("message_id"),

    }


def get_telegram_channel_candidates(
    channels,
    keywords,
    history,
    history_titles
):

    if history_titles is None:

        history_titles = []

    candidates = []
    seen_titles = []

    for channel in channels:

        try:

            html = fetch_public_page(
                channel
            )

        except Exception as error:

            log.warning(
                "TELEGRAM NEWS SOURCE FAILED | %s | %s",
                channel,
                error
            )

            continue

        messages = parse_public_messages_with_media(
            html
        )

        for item in messages[
            :NEWS_MAX_CANDIDATES_PER_SOURCE
        ]:

            article = telegram_message_to_article(
                channel,
                item
            )

            if not article:

                continue

            if (
                channel not in TRUMP_NEWS_CHANNELS
                and
                is_blocked_rate_gold_news(
                    article
                )
            ):

                continue

            if is_duplicate_news(
                article,
                history_titles,
                history_urls=history
            ):

                continue

            if any(

                news_titles_similar(
                    article["title"],
                    old_title
                )

                for old_title in seen_titles

            ):

                continue

            if is_price_only_news(
                article
            ):

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

            importance = calculate_news_importance(
                article,
                keywords
            )

            log.info(

                "TELEGRAM NEWS CANDIDATE | "
                "score=%s | %s | %s",

                importance,
                channel,
                article["title"]

            )

            if (
                importance
                <
                NEWS_MIN_IMPORTANCE
            ):

                continue

            article["importance"] = importance

            candidates.append(
                article
            )

            seen_titles.append(
                article["title"]
            )

    if not candidates:

        return None

    candidates.sort(

        key=lambda x: (

            int(
                x.get(
                    "importance",
                    0
                )
            ),

            len(
                x.get(
                    "text",
                    ""
                )
            )

        ),

        reverse=True

    )

    return candidates[0]


async def get_trump_channel_news(
    history,
    history_titles=None
):
    """Return the best fresh Trump-related item from the requested channels."""

    return await asyncio.to_thread(
        get_telegram_channel_candidates,
        TRUMP_NEWS_CHANNELS,
        TRUMP_NEWS_KEYWORDS,
        history,
        history_titles
    )


async def get_telegram_channel_news(
    history,
    history_titles=None
):

    channels = (

        TELEGRAM_BREAKING_NEWS_CHANNELS
        +
        TELEGRAM_ECONOMIC_NEWS_CHANNELS

    )

    combined_keywords = (

        WORLD_KEYWORDS
        +
        ECONOMIC_KEYWORDS

    )

    return await asyncio.to_thread(

        get_telegram_channel_candidates,

        channels,

        combined_keywords,

        history,

        history_titles

    )


# =========================================================
# AI NEWS EDITOR
# =========================================================

def clean_ai_output(
    text
):

    text = (text or "").strip()

    if not text:

        return ""

    text = re.sub(
        r"(…|\.)+$",
        "",
        text
    ).strip()

    text = re.sub(
        r"^```(?:text|markdown|plaintext)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    return text.strip()


def count_words_fa(
    text
):

    text = normalize_fa(
        text
    )

    return len(
        re.findall(
            r"\S+",
            text
        )
    )


def normalize_for_similarity(
    text
):

    text = normalize_fa(
        text
    ).lower()

    text = re.sub(
        r"[^\w\sآ-ی]",
        " ",
        text,
        flags=re.UNICODE
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


def calculate_text_similarity(
    source,
    generated
):

    source = normalize_for_similarity(
        source
    )

    generated = normalize_for_similarity(
        generated
    )

    if not source or not generated:

        return 0.0

    source_words = source.split()
    generated_words = generated.split()

    if not source_words or not generated_words:

        return 0.0

    source_sample = " ".join(
        source_words[:4000]
    )

    generated_sample = " ".join(
        generated_words[:700]
    )

    return SequenceMatcher(
        None,
        source_sample,
        generated_sample
    ).ratio()


# کلمات ربط/حرف اضافه/فعل کمکی پرتکرار فارسی. این کلمات در هر متن
# دستوری فارسی (چه رونویسی، چه بازنویسی کاملاً مستقل) به‌وفور تکرار
# می‌شوند، پس نباید در معیار «شباهت به منبع» حساب شوند؛ وگرنه هر خلاصه‌ی
# درست‌نوشته‌ای هم overlap بالایی می‌گیرد و به‌اشتباه «کپی» تشخیص داده
# می‌شود.
FA_STOPWORDS = {
    "و", "در", "به", "از", "که", "این", "آن", "را", "با", "برای",
    "تا", "هم", "بر", "یک", "شد", "شده", "کرد", "کرده", "می", "است",
    "بود", "باشد", "خواهد", "اگر", "یا", "نیز", "چون", "اما", "ولی",
    "دیگر", "هر", "همه", "چند", "کدام", "چه", "روی", "بین", "زیر",
    "پس", "سپس", "همچنین", "طی", "علیه", "درباره", "پیش", "بعد",
    "کند", "کنند", "کنیم", "دارد", "دارند", "داشت", "داشته", "او",
    "ما", "آنها", "خود", "خویش", "را", "های", "ای", "اش",
}


def calculate_word_overlap(
    source,
    generated
):

    source_words = set(
        normalize_for_similarity(
            source
        ).split()
    )

    generated_words = set(
        normalize_for_similarity(
            generated
        ).split()
    )

    # فقط کلمات محتوایی (اسم/عدد/فعل اصلی/نام خاص و ...) را می‌سنجیم،
    # نه کلمات ربط پرتکرار که در هر بازنویسی مستقلی هم تکرار می‌شوند.
    source_content_words = source_words - FA_STOPWORDS
    generated_content_words = generated_words - FA_STOPWORDS

    if not generated_content_words:

        return 0.0

    return (
        len(
            source_content_words
            &
            generated_content_words
        )
        /
        len(generated_content_words)
    )


def is_ai_copy_like(
    source,
    generated
):

    similarity = calculate_text_similarity(
        source,
        generated
    )

    overlap = calculate_word_overlap(
        source,
        generated
    )

    log.info(
        "AI NEWS SIMILARITY = %.3f | WORD OVERLAP = %.3f",
        similarity,
        overlap
    )

    if similarity >= AI_NEWS_SIMILARITY_LIMIT:

        return True

    # اخبار واقعی به‌ناچار اسم خاص/عدد/تاریخ مشترک با منبع دارند (چون
    # AI اجازه ندارد واقعیت جدید اضافه کند)، پس آستانه‌ی کلمات محتوایی
    # مشترک باید بالاتر از یک بازنویسی معمولی باشد تا فقط کپی واقعی
    # (نه بازنویسی درست) رد شود.
    if overlap >= 0.88:

        return True

    return False


def parse_ai_news_result(
    result,
    original_title,
    original_text
):

    result = clean_ai_output(
        result
    )

    if not result:

        return None

    lines = [

        line.strip()

        for line in result.splitlines()

        if line.strip()

    ]

    if len(lines) < 3:

        return None

    sections = {

        "title": "",
        "text": "",
        "why": "",
        "silver": ""

    }

    current = "text"

    text_lines = []

    for line in lines:

        normalized = line.strip()

        if re.match(
            r"^(عنوان|تیتر)\s*[:：]",
            normalized,
            re.IGNORECASE
        ):

            sections["title"] = re.sub(
                r"^(عنوان|تیتر)\s*[:：]\s*",
                "",
                normalized,
                flags=re.IGNORECASE
            ).strip()

            continue

        if re.match(
            r"^متن\s*[:：]",
            normalized,
            re.IGNORECASE
        ):

            current = "text"

            remainder = re.sub(
                r"^متن\s*[:：]\s*",
                "",
                normalized,
                flags=re.IGNORECASE
            ).strip()

            if remainder:

                text_lines.append(
                    remainder
                )

            continue

        if (
            "چرا مهم است" in normalized
            or
            "اهمیت خبر" in normalized
        ):

            current = "why"

            remainder = re.sub(
                r"^(?:📌\s*)?(?:چرا مهم است|اهمیت خبر)\s*[:：]?\s*",
                "",
                normalized,
                flags=re.IGNORECASE
            ).strip()

            if remainder:

                sections["why"] += (
                    remainder
                    + " "
                )

            continue

        if re.match(
            r"^(?:🥈\s*)?(?:ارتباط با بازار نقره|اثر بر نقره|بازار نقره)\s*[:：]",
            normalized,
            re.IGNORECASE
        ):

            current = "silver"

            remainder = re.sub(
                r"^(?:🥈\s*)?(?:ارتباط با بازار نقره|اثر بر نقره|بازار نقره)\s*[:：]\s*",
                "",
                normalized,
                flags=re.IGNORECASE
            ).strip()

            if remainder:

                sections["silver"] += (
                    remainder
                    + " "
                )

            continue

        if current == "text":

            text_lines.append(
                normalized
            )

        elif current in [
            "why",
            "silver"
        ]:

            sections[current] += (
                normalized
                + " "
            )

    if not sections["title"]:

        sections["title"] = original_title

    sections["text"] = "\n\n".join(
        text_lines
    ).strip()

    for key in [
        "why",
        "silver"
    ]:

        sections[key] = clean_ai_output(
            sections[key]
        )

    sections["title"] = clean_ai_output(
        sections["title"]
    )

    sections["text"] = clean_ai_output(
        sections["text"]
    )

    if len(sections["title"]) > 180:

        sections["title"] = (
            sections["title"][:180]
            .rsplit(" ", 1)[0]
            .strip()
        )

    if len(sections["text"]) < 30:

        return None

    if count_words_fa(
        sections["text"]
    ) > AI_NEWS_MAX_BODY_WORDS:

        log.warning(
            "AI NEWS REJECTED | BODY OVER %s WORDS",
            AI_NEWS_MAX_BODY_WORDS
        )

        return None

    # «چرا مهم است» عمداً در خروجی عمومی استفاده نمی‌شود.
    # تحلیل نقره فقط در صورتی منتشر می‌شود که AI تشخیص دهد خبر
    # اثر واقعی و قابل‌دفاعی بر بازار نقره دارد.
    silver_normalized = normalize_fa(
        sections["silver"]
    )

    no_silver_values = {
        "",
        "ندارد",
        "هیچ ارتباطی ندارد",
        "ارتباطی ندارد",
        "بدون ارتباط",
        "ارتباطی با بازار نقره ندارد",
        "این خبر ارتباط مستقیمی با بازار نقره ندارد",
        "ارتباط مستقیم ندارد",
    }

    if silver_normalized in {
        normalize_fa(value)
        for value in no_silver_values
    }:
        sections["silver"] = ""

    for key in [
        "title",
        "text",
        "why",
        "silver"
    ]:

        sections[key] = re.sub(
            r"🟢\s*مثبت\s*[🟡🔴]*",
            "",
            sections[key]
        )

        sections[key] = re.sub(
            r"🟡\s*خنثی\s*[🟢🔴]*",
            "",
            sections[key]
        )

        sections[key] = re.sub(
            r"🔴\s*منفی\s*[🟢🟡]*",
            "",
            sections[key]
        )

        sections[key] = re.sub(
            r"\s+",
            " ",
            sections[key]
        ).strip()

    why_words = sections["why"].split()

    if len(why_words) > 18:

        sections["why"] = (
            " ".join(
                why_words[:18]
            )
            .rstrip("،؛.")
            + "."
        )

    silver_words = sections["silver"].split()

    if len(silver_words) > 18:

        sections["silver"] = (
            " ".join(
                silver_words[:18]
            )
            .rstrip("،؛.")
            + "."
        )

    generated_content = "\n".join(
        part
        for part in [
            sections["title"],
            sections["text"],
            sections["silver"],
        ]
        if part
    )

    word_count = count_words_fa(
        generated_content
    )

    log.info(
        "AI NEWS WORD COUNT = %s/%s",
        word_count,
        AI_NEWS_MAX_WORDS
    )

    if word_count > AI_NEWS_MAX_WORDS:

        log.warning(
            "AI NEWS REJECTED | OVER %s WORDS",
            AI_NEWS_MAX_WORDS
        )

        return None

    # فیلتر موضوعات نرخ/دلار/طلا باید فقط خود خبر را بررسی کند،
    # نه تحلیل اختیاری نقره؛ وگرنه ممکن است کلمات اقتصادی داخل
    # تحلیل نقره باعث رد شدن یک خبر سیاسی/ژئوپلیتیکی معتبر شوند.
    ai_article_for_filter = {
        "title": sections["title"],
        "text": sections["text"],
    }

    if is_blocked_rate_gold_news(
        ai_article_for_filter
    ):

        log.warning(
            "AI NEWS REJECTED | RATE/GOLD/CURRENCY TOPIC"
        )

        return None

    if is_ai_copy_like(
        original_text,
        generated_content
    ):

        log.warning(
            "AI NEWS REJECTED | TOO SIMILAR TO SOURCE"
        )

        return None

    return sections


def ai_summarize_news_sync(
    title,
    text
):

    if not AI_NEWS_ENABLED:

        return {

            "title":
                title,

            "text":
                text,

            "why":
                "این خبر برای بازار اهمیت دارد.",

            "silver":
                "این خبر می‌تواند برای بازار نقره مهم باشد."

        }

    if not OPENAI_API_KEY:

        raise RuntimeError(
            "OPENAI_API_KEY تنظیم نشده است."
        )

    if not text:

        return None

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url="https://1xai.ir/v1"
    )

    prompt = f"""
تو سردبیر حرفه‌ای و مستقل کانال تلگرامی «یزدان‌دوست» هستی.

من یک خبر واقعی و کامل در اختیار تو قرار می‌دهم.
وظیفه تو این است که از آن یک خلاصه حرفه‌ای،
خوانا و مستقل برای کانال تلگرام تولید کنی.

هدف این نیست که متن منبع را بازنویسی کنی.
ابتدا مفهوم خبر را درک کن و سپس با جمله‌بندی کاملاً مستقل،
فقط مهم‌ترین اطلاعات را منتقل کن.

قوانین بسیار مهم:

1. فقط اطلاعات موجود در متن منبع را استفاده کن.
2. هیچ عدد، قیمت، درصد، تاریخ، نام یا واقعیت جدیدی اضافه نکن.
3. هیچ پیش‌بینی قطعی درباره آینده قیمت نده.
4. متن خام منبع را کپی نکن.
5. جمله‌بندی منبع را تکرار نکن.
6. اطلاعات حاشیه‌ای و تکراری را حذف کن.
7. مهم‌ترین اتفاق خبر را در ابتدای متن بیاور.
8. متن اصلی خبر حداکثر 90 کلمه باشد.
9. کل خروجی حداکثر 140 کلمه باشد.
10. خروجی باید تا حد امکان کوتاه و مفید باشد.
11. هیچ بخش «چرا مهم است» یا «اهمیت خبر» تولید نکن.
12. از تکرار یک مفهوم در بخش‌های مختلف خودداری کن.
13. متن خبر باید طبیعی، روان، حرفه‌ای و خواندنی باشد؛ از لحن خشک و ماشینی پرهیز کن.
14. مهم‌ترین بخش خبر را با یک شروع قوی و روشن بیان کن، اما از تیترهای زرد و اغراق‌آمیز استفاده نکن.
15. هیچ Markdown و هشتگ استفاده نکن.
16. از ایموجی‌های 🟢، 🟡 و 🔴 برای تحلیل بازار استفاده نکن.
17. سؤال پایانی تولید نکن.
18. ساعت یا زمان انتشار خبر را در خروجی نیاور.
19. عنوان باید کوتاه، خبری و جذاب باشد؛ نه صرفاً تکرار عنوان منبع.
20. متن باید خلاصه واقعی و مستقل باشد، نه بازنویسی خط‌به‌خط.
21. اگر موضوع اصلی خبر قیمت یا نرخ دلار، هر نوع ارز،
    طلا، طلای جهانی، سکه یا نرخ تبدیل ارزهاست،
    این خبر نباید برای انتشار انتخاب شود.
22. اگر خبر صرفاً درباره تغییر قیمت یا نرخ دلار،
    ارز، طلا یا سکه است، آن را منتشر نکن.
23. حتی اگر خبر درباره یک رویداد اقتصادی باشد،
    نباید موضوع اصلی آن نرخ دلار، نرخ ارز،
    قیمت طلا یا قیمت سکه باشد.
24. «ارتباط با بازار نقره» را فقط زمانی تولید کن که خود این خبر
    واقعاً بتواند از یک مسیر مشخص و قابل توضیح بر بازار نقره اثر بگذارد؛
    مثل تغییر مهم در سیاست پولی آمریکا، تحریم یا تنش ژئوپلیتیکی مهم،
    اختلال در عرضه/تقاضای فلزات، یا رویدادی که مستقیماً بر دلار،
    بازده اوراق یا چشم‌انداز اقتصاد جهانی اثر بگذارد.
25. صرفاً اینکه یک خبر اقتصادی یا سیاسی است، دلیل کافی برای ارتباط
    با نقره نیست. اگر اثر معنادار و مشخصی وجود ندارد، بنویس:
    «ارتباط با بازار نقره: ندارد».
26. اگر ارتباط با نقره وجود دارد، تحلیل باید اختصاصی همین خبر باشد
    و دقیقاً توضیح دهد این رویداد از چه مسیری می‌تواند بر نقره اثر بگذارد.
    از جمله‌های کلی و تکراری مثل «می‌تواند بر بازار نقره تأثیر بگذارد»
    استفاده نکن.
27. در تحلیل نقره پیش‌بینی قطعی قیمت، عددسازی یا ادعای بدون پشتوانه نکن.
28. خروجی دقیقاً با این ساختار باشد:

عنوان: ...

متن:
...

ارتباط با بازار نقره: ...

عنوان اصلی خبر:
{title}

متن کامل منبع:
{text}
"""

    last_error = None

    for attempt in range(
        1,
        AI_NEWS_RETRIES + 1
    ):

        try:

            response = client.responses.create(

                model=OPENAI_MODEL,

                instructions=(
                    "تو سردبیر دقیق و بی‌طرف اخبار فارسی هستی. "
                    "خبر را حرفه‌ای و خلاصه کن. "
                    "متن منبع را کپی یا خط‌به‌خط بازنویسی نکن. "
                    "کل خروجی حداکثر ۱۴۰ کلمه باشد. "
                    "خبرهای مربوط به نرخ و قیمت دلار، ارزها، طلا و سکه را تولید نکن. "
                    "بخش ارتباط با نقره فقط در صورت اثر واقعی و مشخص نوشته شود؛ "
                    "در غیر این صورت مقدار آن «ندارد» باشد. "
                    "از جمله‌های کلی و تکراری برای ارتباط با نقره استفاده نکن."
                ),

                input=prompt

            )

            result = response.output_text.strip()

            parsed = parse_ai_news_result(
                result,
                title,
                text
            )

            if parsed:

                return parsed

            raise RuntimeError(
                "خروجی AI یا بیش از حد طولانی بود "
                "یا بیش از حد به متن منبع شباهت داشت "
                "یا موضوع آن مربوط به نرخ ارز/دلار/طلا/سکه بود."
            )

        except Exception as error:

            last_error = error

            log.warning(

                "AI NEWS ATTEMPT %s/%s FAILED: %s",

                attempt,
                AI_NEWS_RETRIES,

                error

            )

            if attempt < AI_NEWS_RETRIES:

                time.sleep(
                    NEWS_AI_RETRY_DELAY_SECONDS
                    * attempt
                )

    raise RuntimeError(
        f"AI NEWS FAILED AFTER RETRIES: {last_error}"
    )


async def ai_summarize_news(
    article
):

    if not article:

        return None

    return await asyncio.to_thread(

        ai_summarize_news_sync,

        article.get(
            "title",
            ""
        ),

        article.get(
            "text",
            ""
        )

    )


# =========================================================
# URGENT NEWS
# =========================================================

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


# =========================================================
# NEWS CAPTION
# =========================================================

def sanitize_public_news_text(
    text
):

    text = clean_ai_output(
        text
    )

    # Remove the entire forbidden "why this matters" section.
    text = re.split(
        r"(?:📌\s*)?(?:چرا مهم است|اهمیت خبر)\s*[:：]?\s*",
        text,
        maxsplit=1,
        flags=re.IGNORECASE
    )[0].strip()

    # Remove old separators and leaked source formatting.
    text = re.sub(
        r"(?m)^\s*[━─═—_]{5,}\s*$",
        "",
        text
    )

    text = re.sub(
        r"(?m)^\s*🚨\s*خبر فوری بازار\s*$",
        "",
        text
    )

    text = re.sub(
        r"(?m)^\s*📰\s*خبر مهم بازار\s*$",
        "",
        text
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


def make_news_caption(
    article
):

    urgent = is_urgent_news(
        article
    )

    title = sanitize_public_news_text(
        article.get("title", "")
    )

    body = sanitize_public_news_text(
        article.get("text", "")
    )

    silver = sanitize_public_news_text(
        article.get("silver", "")
    )

    # هیچ بخش «چرا مهم است» نباید به کانال عمومی نشت کند.
    body = re.split(
        r"(?:📌\s*)?(?:چرا مهم است|اهمیت خبر)\s*[:：]?\s*",
        body,
        maxsplit=1,
        flags=re.IGNORECASE
    )[0].strip()

    # اگر مدل به‌اشتباه بخش «چرا مهم است» را داخل تحلیل نقره آورده باشد،
    # آن را حذف می‌کنیم.
    silver = re.split(
        r"(?:📌\s*)?(?:چرا مهم است|اهمیت خبر)\s*[:：]?\s*",
        silver,
        maxsplit=1,
        flags=re.IGNORECASE
    )[0].strip()

    # «ندارد» یا عبارت‌های معادل آن هرگز منتشر نمی‌شوند.
    silver_normalized = normalize_fa(
        silver
    )

    no_silver_values = {
        "",
        "ندارد",
        "هیچ ارتباطی ندارد",
        "ارتباطی ندارد",
        "بدون ارتباط",
        "ارتباطی با بازار نقره ندارد",
        "این خبر ارتباط مستقیمی با بازار نقره ندارد",
        "ارتباط مستقیم ندارد",
    }

    if silver_normalized in {
        normalize_fa(value)
        for value in no_silver_values
    }:
        silver = ""

    # عنوان تکراری احتمالی داخل متن را حذف کن.
    body = re.sub(
        r"(?m)^\s*(?:🔴|🔵|🟠|🟢|⚪️|⚫️)?\s*"
        + re.escape(title)
        + r"\s*$",
        "",
        body,
        count=1
    ).strip()

    body_lines = [
        line.strip()
        for line in body.splitlines()
        if line.strip()
    ]

    if body_lines and title:
        normalize = lambda s: re.sub(
            r"[^آ-یA-Za-z0-9]+",
            "",
            s
        ).lower()

        nt = normalize(title)
        nf = normalize(body_lines[0])

        if (
            nt
            and nf
            and (
                nt == nf
                or nt in nf
                or nf in nt
            )
            and len(nf) >= 12
        ):
            body_lines = body_lines[1:]
            body = "\n".join(
                body_lines
            ).strip()

    # پست عمومی: تیتر + متن خبر؛ تحلیل نقره فقط در صورت وجود ارتباط واقعی.
    parts = []

    if title:
        prefix = "🚨" if urgent else "📰"
        parts.append(
            f"{prefix} {title}"
        )

    if body:
        parts.append(
            body
        )

    if silver:
        parts.append(
            "🥈 ارتباط با بازار نقره:\n"
            + silver
        )

    return "\n\n".join(
        parts
    ).strip()


# =========================================================
# NEWS POLL
# =========================================================

def make_news_poll_question(
    article
):

    return (
        "📊 برداشت شما از این خبر چیست؟"
    )


# =========================================================
# TELEGRAM POLL BUILDER (version-safe)
# =========================================================
# لایه‌های جدید تلگرام/تلثون امضای Poll و PollAnswer را تغییر داده‌اند:
#   - در نسخه‌های تازه، question و text باید TextWithEntities باشند نه str.
#   - بعضی نسخه‌ها آرگومان اجباری اضافه دارند (خطای واقعی لاگ:
#     "Poll.__init__() missing 1 required positional argument: 'hash'").
# این سازنده امضای کلاس نصب‌شده را بازرسی می‌کند و پُر می‌کند تا کد روی
# هر نسخه‌ای از Telethon که روی GitHub Actions نصب شود کار کند.


def _poll_required_kwargs(
    cls,
    kwargs
):
    """
    Build only constructor fields accepted by the installed Telethon version.
    Also supplies a safe integer hash when the installed Poll layer requires it.
    """
    try:
        params = inspect.signature(cls).parameters
    except (TypeError, ValueError):
        try:
            params = inspect.signature(cls.__init__).parameters
        except (TypeError, ValueError):
            return kwargs

    for name, param in params.items():
        if name == "self" or name in kwargs:
            continue

        if param.kind in (
            param.VAR_POSITIONAL,
            param.VAR_KEYWORD
        ):
            continue

        if param.default is inspect.Parameter.empty:
            if name == "hash":
                kwargs[name] = 0
            elif name in ("flags",):
                kwargs[name] = 0
            elif name in ("question_entities", "solution_entities"):
                kwargs[name] = []
            elif name in ("correct_answers",):
                kwargs[name] = []
            else:
                # Preserve the existing version-safe behavior for any other
                # required TL constructor field.
                kwargs[name] = 0

    # A few Telethon builds expose `hash` in the signature differently from
    # the generated __init__. Keep the explicit compatibility fallback.
    try:
        if "hash" in inspect.signature(cls).parameters:
            kwargs.setdefault("hash", 0)
    except (TypeError, ValueError):
        pass

    return kwargs


def _poll_rich_text(
    value
):
    try:
        from telethon.tl.types import TextWithEntities

    except ImportError:
        return None

    return TextWithEntities(
        text=str(value),
        entities=[]
    )


def _make_poll(
    question,
    options,
    rich
):
    answers = []

    for text_value, option in options:
        answer_text = str(text_value)

        if rich:
            answer_text = _poll_rich_text(
                answer_text
            )

            if answer_text is None:
                raise RuntimeError(
                    "TextWithEntities not available in this Telethon version"
                )

        answers.append(
            PollAnswer(
                **_poll_required_kwargs(
                    PollAnswer,
                    {
                        "text": answer_text,
                        "option": option
                    }
                )
            )
        )

    poll_question = str(question)

    if rich:
        poll_question = _poll_rich_text(
            poll_question
        )

        if poll_question is None:
            raise RuntimeError(
                "TextWithEntities not available in this Telethon version"
            )

    poll_kwargs = _poll_required_kwargs(
        Poll,
        {
            "id": random.getrandbits(62),
            "question": poll_question,
            "answers": answers,
            "closed": False,
            "public_voters": False,
            "multiple_choice": False,
            "quiz": False
        }
    )

    # Explicit compatibility for the exact failure seen in GitHub Actions:
    # Poll.__init__() missing 1 required positional argument: 'hash'
    try:
        poll_params = inspect.signature(Poll).parameters
        if "hash" in poll_params:
            poll_kwargs.setdefault("hash", 0)
    except (TypeError, ValueError):
        pass

    return Poll(
        **poll_kwargs
    )


def build_telegram_poll(
    question,
    options
):
    """Build and serialize-test a native Telegram poll."""

    errors = []

    # Current/older layers generally accept plain strings; newer layers may
    # require TextWithEntities. Try both without changing the caller.
    for rich in (False, True):

        try:
            poll = _make_poll(
                question,
                options,
                rich
            )

            # Force TL serialization before sending. This catches a mismatch
            # locally instead of failing later inside SendMediaRequest.
            bytes(poll)

            return poll

        except Exception as error:
            errors.append(
                f"rich={rich}: {error}"
            )

    raise RuntimeError(
        "POLL BUILD FAILED | " + " | ".join(errors)
    )



def poll_random_id():

    return random.getrandbits(62)


async def send_news_poll(
    client,
    target,
    article
):

    question = make_news_poll_question(
        article
    )

    poll = build_telegram_poll(

        question,

        [
            ("🟢 مثبت", b"\x01"),
            ("🟡 خنثی", b"\x02"),
            ("🔴 منفی", b"\x03")
        ]

    )

    media = InputMediaPoll(
        poll=poll
    )

    sent = await client(
        SendMediaRequest(

            peer=target,

            media=media,

            message=(
                "📊 برداشت شما از این خبر چیست؟\n\n"
                "رأی خود را ثبت کنید 👇"
            ),

            random_id=poll_random_id()

        )
    )

    log.info(
        "NEWS POLL SENT | %s",
        sent.id
    )

    try:
        message_id = int(sent.id)

        if message_id not in RUBIKA_CURRENT_AUTO_MESSAGE_IDS:
            RUBIKA_CURRENT_AUTO_MESSAGE_IDS.append(
                message_id
            )

    except Exception:
        pass

    return int(
        sent.id
    )


# =========================================================
# MASHHAD REPORT
# =========================================================

def make_mashhad_report(
    market,
    rate,
    gold_ounce=None
):

    coin_bubble = calculate_coin_bubble(

        rate,

        market[
            "coin_imami"
        ],

        gold_ounce

    )

    log.info(
        "COIN INTRINSIC CALC | GOLD_OUNCE=%s | TEHRAN=%s | "
        "WEIGHT=%s | FINENESS=%s | INTRINSIC=%s",
        gold_ounce,
        rate.get("tehran"),
        COIN_IMAMI_WEIGHT,
        COIN_FINENESS,
        coin_bubble.get("intrinsic") if coin_bubble else None
    )

    if coin_bubble is None:
        log.warning(
            "COIN BUBBLE SKIPPED | GOLD OUNCE OR TEHRAN DOLLAR UNAVAILABLE"
        )
        return None

    coin_bubble_text = format_price(
        abs(
            coin_bubble["bubble"]
        )
    )

    if coin_bubble["bubble"] > 0:

        coin_bubble_label = (
            f"🟢 حباب مثبت: {coin_bubble_text} تومان"
        )

    elif coin_bubble["bubble"] < 0:

        coin_bubble_label = (
            f"🔴 حباب منفی: {coin_bubble_text} تومان"
        )

    else:

        coin_bubble_label = (
            "⚪ حباب: بدون حباب"
        )

    gold_bubble = None

    if gold_ounce is not None:

        try:

            gold_bubble = calculate_gold_18_bubble(

                rate,
                gold_ounce,
                market[
                    "gold_18_mashhad"
                ]

            )

        except Exception as error:

            log.exception(
                "GOLD 18 BUBBLE CALCULATION FAILED: %s",
                error
            )

    lines = [

        "🪙 گزارش بازار طلا و سکه مشهد",
        "━━━━━━━━━━━━━━",

        f"📅 {iran_date_string()}",
        f"🕐 {iran_time_string()}",
        "",

        "🥇 طلای ۱۸ عیار مشهد",
        f"💰 {format_price(market['gold_18_mashhad'])} تومان",

    ]

    if gold_bubble is not None:

        if gold_bubble["bubble"] > 0:

            gold_bubble_text = (
                f"🟢 حباب مثبت: "
                f"{format_price(gold_bubble['bubble'])} تومان"
            )

        elif gold_bubble["bubble"] < 0:

            gold_bubble_text = (
                f"🔴 حباب منفی: "
                f"{format_price(abs(gold_bubble['bubble']))} تومان"
            )

        else:

            gold_bubble_text = (
                "⚪ حباب: بدون حباب"
            )

        lines.extend([

            "",
            "🎈 حباب طلای ۱۸ عیار",
            gold_bubble_text,

        ])

    if gold_ounce is not None:

        lines.extend([

            "",
            "🌍 انس طلا",
            f"💵 {gold_ounce:.2f} دلار",

        ])

    # خرید طلای دست‌دوم از نرخ لحظه‌ای TGJU، در صورت دسترسی.
    if market.get("gold_secondhand") is not None:

        lines.extend([

            "",
            "🛒 خرید طلای دست‌دوم",
            f"💰 {format_price(market['gold_secondhand'])} تومان",

        ])

    lines.extend([

        "",
        "🪙 سکه امامی",
        f"💰 {format_price(market['coin_imami'])} تومان",

        "",
        "🎈 حباب سکه امامی",
        coin_bubble_label,

        "",
        "📌 ارزش ذاتی محاسبه‌شده سکه",
        f"{format_price(coin_bubble['intrinsic'])} تومان",

    ])

    lines.append(
        channel_footer()
    )

    return "\n".join(
        lines
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

        "🌙 جمع‌بندی بازار امروز",
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

        "🧱 شمش ندیر ۹۹۹.۹",
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
        "",
        "📌 جمع‌بندی:",
        "بازار نقره، طلا و ارز را با توجه به "
        "قیمت‌های به‌روزشده و اخبار مهم امروز دنبال کنید.",
        "",
        "💬 به نظر شما مهم‌ترین عامل بازار فردا چیست؟",

    ]

    lines.append(
        channel_footer()
    )

    return "\n".join(
        lines
    )


# =========================================================
# MARKET PULSE
# =========================================================

MARKET_PULSE_TGJU_BASE = "https://www.tgju.org/profile/"

MARKET_PULSE_TGJU_SYMBOLS = {
    "dollar": {
        "slug": "price_dollar_rl",
        "kind": "rial",
    },
    "euro": {
        "slug": "price_eur",
        "kind": "rial",
    },
    "pound": {
        "slug": "price_gbp",
        "kind": "rial",
    },
    "aed": {
        "slug": "price_aed",
        "kind": "rial",
    },
    "silver_ounce": {
        "slug": "silver",
        "kind": "global",
    },
    "gold_18": {
        "slug": "geram18",
        "kind": "rial",
    },
    "gold_24": {
        "slug": "geram24",
        "kind": "rial",
    },
    "gold_secondhand": {
        "slug": "gold_mini_size",
        "kind": "rial",
    },
    "mesghal": {
        "slug": "mesghal",
        "kind": "rial",
    },
    "melted_gold": {
        "slug": "gold_futures",
        "kind": "rial",
    },
    "coin_imami": {
        "slug": "sekee",
        "kind": "rial",
    },
    "coin_bahar": {
        "slug": "sekeb",
        "kind": "rial",
    },
    "coin_half": {
        "slug": "nim",
        "kind": "rial",
    },
    "coin_quarter": {
        "slug": "rob",
        "kind": "rial",
    },
    "coin_gram": {
        "slug": "gerami",
        "kind": "rial",
    },
    "bubble_imami": {
        "slug": "coin_blubber",
        "kind": "rial",
    },
    "bubble_bahar": {
        "slug": "sekeb_blubber",
        "kind": "rial",
    },
    "bubble_half": {
        "slug": "nim_blubber",
        "kind": "rial",
    },
    "bubble_quarter": {
        "slug": "rob_blubber",
        "kind": "rial",
    },
    "bubble_gram": {
        "slug": "gerami_blubber",
        "kind": "rial",
    },
}

def parse_tgju_profile_value(
    html,
    kind="rial"
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

    current = None
    change_percent = None

    current_match = re.search(
        r"نرخ\s*فعلی\s*[:：]*\s*"
        r"([\d,٬]+(?:\.\d+)?)"
        r"\s+"
        r"([+-]?\d+(?:\.\d+)?)",
        text
    )

    if current_match:
        current = decimal_value(
            current_match.group(1)
        )

        change_percent = decimal_value(
            current_match.group(2)
        )

    if current is None:
        current_match = re.search(
            r"نرخ\s*فعلی\s*[:：]*\s*"
            r"([\d,٬]+(?:\.\d+)?)",
            text
        )

        if current_match:
            current = decimal_value(
                current_match.group(1)
            )

    daily_match = re.search(
        r"درصد\s*تغییر\s*نسبت\s*به\s*روز\s*گذشته"
        r"\s*[:|]?\s*"
        r"([+-]?\d+(?:\.\d+)?)\s*%",
        text
    )

    if daily_match:
        change_percent = decimal_value(
            daily_match.group(1)
        )

    if current is None:
        return None

    if kind == "rial":
        current = current / 10.0

    return {
        "value": float(current),
        "change_percent": (
            float(change_percent)
            if change_percent is not None
            else None
        )
    }


def fetch_tgju_market_item(
    key,
    config
):
    slug = config["slug"]

    if slug == "__gold_ounce__":
        url = GOLD_OUNCE_URL
    else:
        url = (
            MARKET_PULSE_TGJU_BASE
            + slug
        )

    html = http_get(
        url,
        timeout=30
    )

    result = parse_tgju_profile_value(
        html,
        config.get(
            "kind",
            "rial"
        )
    )

    if result is None:
        raise RuntimeError(
            f"TGJU value not found: {key}"
        )

    result["source"] = url

    return result


def get_market_pulse_data_sync():
    data = {}

    symbols = dict(
        MARKET_PULSE_TGJU_SYMBOLS
    )

    symbols["gold_ounce"] = {
        "slug": "__gold_ounce__",
        "kind": "global",
    }

    def fetch_one(
        key,
        config
    ):
        try:
            result = fetch_tgju_market_item(
                key,
                config
            )

            return (
                key,
                result,
                None
            )

        except Exception as error:
            return (
                key,
                None,
                error
            )

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        futures = [
            executor.submit(
                fetch_one,
                key,
                config
            )
            for key, config
            in symbols.items()
        ]

        for future in as_completed(
            futures
        ):
            key, result, error = (
                future.result()
            )

            if result is not None:
                data[key] = result

                log.info(
                    "MARKET PULSE DATA OK | %s | %s",
                    key,
                    result.get("value")
                )

            else:
                log.warning(
                    "MARKET PULSE DATA FAILED | %s | %s",
                    key,
                    error
                )

    # اقلام ضروری نبض بازار: چند بار با TGJU مجدداً تلاش می‌کنیم تا
    # طلای ۱۸، طلای ۲۴، دست‌دوم، مثقال و ربع‌سکه به‌دلیل یک خطای
    # موقت شبکه/سرور از جدول حذف نشوند. قیمت قبلی state به‌عنوان
    # قیمت لحظه‌ای استفاده نمی‌شود.
    required_pulse_keys = (
        "gold_18",
        "gold_24",
        "gold_secondhand",
        "mesghal",
        "coin_quarter",
    )

    for retry_key in required_pulse_keys:
        if (
            retry_key in data
            and data[retry_key].get("value") is not None
        ):
            continue

        retry_config = MARKET_PULSE_TGJU_SYMBOLS.get(retry_key)
        if not retry_config:
            continue

        for retry_no in range(2):
            try:
                retry_result = fetch_tgju_market_item(
                    retry_key,
                    retry_config
                )
                if (
                    retry_result
                    and retry_result.get("value") is not None
                ):
                    data[retry_key] = retry_result
                    log.info(
                        "MARKET PULSE REQUIRED RETRY OK | %s | %s",
                        retry_key,
                        retry_result.get("value")
                    )
                    break
            except Exception as retry_error:
                log.warning(
                    "MARKET PULSE REQUIRED RETRY FAILED | %s | attempt=%s | %s",
                    retry_key,
                    retry_no + 1,
                    retry_error
                )

    # انس طلا و نقره: اگر TGJU در لحظه پاسخ نداد، از TradingView استفاده کن.
    try:
        tv_data = get_tradingview_market_data_sync()

        if (
            "gold_ounce" not in data
            or data["gold_ounce"].get("value") is None
        ):
            tv_gold = tv_data.get("gold")
            if tv_gold and tv_gold.get("close") is not None:
                data["gold_ounce"] = {
                    "value": float(tv_gold["close"]),
                    "change_percent": (
                        float(tv_gold["change"])
                        if tv_gold.get("change") is not None
                        else None
                    ),
                    "source": "TradingView:OANDA:XAUUSD",
                }
                log.info(
                    "MARKET PULSE GOLD OUNCE FALLBACK OK | %s",
                    tv_gold.get("close"),
                )

        if (
            "silver_ounce" not in data
            or data["silver_ounce"].get("value") is None
        ):
            tv_silver = tv_data.get("silver")
            if tv_silver and tv_silver.get("close") is not None:
                data["silver_ounce"] = {
                    "value": float(tv_silver["close"]),
                    "change_percent": (
                        float(tv_silver["change"])
                        if tv_silver.get("change") is not None
                        else None
                    ),
                    "source": "TradingView:OANDA:XAGUSD",
                }
                log.info(
                    "MARKET PULSE SILVER OUNCE FALLBACK OK | %s",
                    tv_silver.get("close"),
                )
    except Exception as error:
        log.warning(
            "MARKET PULSE TRADINGVIEW FALLBACK FAILED: %s",
            error,
        )

    return data


async def get_market_pulse_data():
    return await asyncio.to_thread(
        get_market_pulse_data_sync
    )


def market_pulse_change_text(
    percent
):
    if percent is None:
        return "—"

    if abs(percent) < 0.005:
        return "⚪ ۰.۰۰٪"

    if percent > 0:
        return f"🔺 +{percent:.2f}٪"

    return f"🔻 {percent:.2f}٪"


def market_pulse_price_text(
    item,
    decimals=0
):
    if not item:
        return "—"

    value = item.get(
        "value"
    )

    if value is None:
        return "—"

    if decimals:
        return f"{value:,.{decimals}f}"

    return format_price(
        value
    )


def market_pulse_bubble_percent(
    coin_price,
    bubble
):
    if (
        coin_price is None
        or
        bubble is None
    ):
        return None

    intrinsic = (
        coin_price
        - bubble
    )

    if intrinsic <= 0:
        return None

    return (
        bubble
        /
        intrinsic
        *
        100
    )


def make_market_pulse(
    data,
    previous_snapshot=None,
    pulse_label="۱۲:۰۰"
):
    """ساخت نسخه مرتب و حرفه‌ای نبض بازار.

    قیمت‌های معتبر نمایش داده می‌شوند و هیچ ردیفی با «—» به‌عنوان
    قیمت منتشر نمی‌شود. اقلام مهم طلا و ربع‌سکه با اولویت دریافت
    مستقیم TGJU در داده‌گیری چندباره حفظ می‌شوند.
    """

    lines = [
        "📊 نبض بازار | قیمت‌های لحظه‌ای",
        "━━━━━━━━━━━━━━━━━━",
        f"📅 {iran_date_string()}    🕐 {pulse_label}",
        "",
    ]

    def add_section(title, items):
        valid = [x for x in items if x is not None]
        if not valid:
            return False
        lines.append(title)
        lines.append("──────────────")
        lines.extend(valid)
        lines.append("")
        return True

    def compact_change(item):
        if not item or item.get("change_percent") is None:
            return ""
        return market_pulse_change_text(item.get("change_percent"))

    def local_line(icon, title, key):
        item = data.get(key)
        if not item or item.get("value") is None:
            return None
        change = compact_change(item)
        suffix = f"  {change}" if change else ""
        return (
            f"{icon} {title}: {market_pulse_price_text(item)} تومان{suffix}"
        )

    def global_line(icon, title, key):
        item = data.get(key)
        if not item or item.get("value") is None:
            return None
        change = compact_change(item)
        suffix = f"  {change}" if change else ""
        return (
            f"{icon} {title}: {market_pulse_price_text(item, 2)} دلار{suffix}"
        )

    # ارزهای مهم
    currency_lines = [
        local_line("💵", "دلار", "dollar"),
        local_line("💶", "یورو", "euro"),
        local_line("🇬🇧", "پوند", "pound"),
        local_line("🇦🇪", "درهم امارات", "aed"),
    ]
    add_section("💱 ارزهای مهم", currency_lines)

    # بازار جهانی
    global_lines = [
        global_line("🥇", "انس طلا", "gold_ounce"),
        global_line("🥈", "انس نقره", "silver_ounce"),
    ]
    add_section("🌍 بازار جهانی", global_lines)

    # طلا
    gold_lines = [
        local_line("🔸", "طلای ۱۸ عیار", "gold_18"),
        local_line("🔸", "طلای ۲۴ عیار", "gold_24"),
        local_line("🔸", "طلای دست‌دوم", "gold_secondhand"),
        local_line("🔸", "مثقال طلا", "mesghal"),
        local_line("🔸", "آبشده نقدی", "melted_gold"),
    ]
    add_section("🥇 طلا", gold_lines)

    # سکه
    coin_lines = []
    coin_items = [
        ("🪙", "سکه امامی", "coin_imami", "bubble_imami"),
        ("🪙", "سکه بهار آزادی", "coin_bahar", "bubble_bahar"),
        ("🪙", "نیم‌سکه", "coin_half", "bubble_half"),
        ("🪙", "ربع‌سکه", "coin_quarter", "bubble_quarter"),
        ("🪙", "سکه گرمی", "coin_gram", "bubble_gram"),
    ]

    for icon, title, price_key, bubble_key in coin_items:
        price_item = data.get(price_key)
        if not price_item or price_item.get("value") is None:
            continue

        price = price_item.get("value")
        change = compact_change(price_item)
        suffix = f"  {change}" if change else ""

        coin_lines.append(
            f"{icon} {title}: {market_pulse_price_text(price_item)} تومان{suffix}"
        )

        bubble_item = data.get(bubble_key)
        bubble = (
            bubble_item.get("value")
            if bubble_item and bubble_item.get("value") is not None
            else None
        )

        if bubble is not None:
            bubble_percent = market_pulse_bubble_percent(price, bubble)
            bubble_sign = "+" if bubble > 0 else ("-" if bubble < 0 else "")
            bubble_amount = format_price(abs(bubble))
            bubble_pct_text = (
                f"{bubble_percent:.2f}٪"
                if bubble_percent is not None
                else None
            )

            if bubble_pct_text is not None:
                coin_lines.append(
                    f"   └ حباب: {bubble_sign}{bubble_amount} تومان  |  {bubble_pct_text}"
                )
            else:
                coin_lines.append(
                    f"   └ حباب: {bubble_sign}{bubble_amount} تومان"
                )

    add_section("🪙 سکه", coin_lines)

    # تغییر از نبض ظهر تا نبض شب
    if previous_snapshot and pulse_label == "۲۰:۳۰":
        intraday_items = [
            ("دلار", "dollar"),
            ("طلای ۱۸", "gold_18"),
            ("انس طلا", "gold_ounce"),
            ("انس نقره", "silver_ounce"),
            ("سکه امامی", "coin_imami"),
        ]

        intraday_lines = []
        for title, key in intraday_items:
            current_item = data.get(key)
            previous_value = previous_snapshot.get(key)
            current_value = (
                current_item.get("value")
                if current_item
                else None
            )

            if (
                current_value is None
                or previous_value is None
                or previous_value == 0
            ):
                continue

            delta_percent = (
                (current_value - previous_value)
                / previous_value
                * 100
            )
            intraday_lines.append(
                f"• {title}: {market_pulse_change_text(delta_percent)}"
            )

        if intraday_lines:
            lines.extend([
                "⏱ تغییر از نبض ظهر",
                "──────────────",
                *intraday_lines,
                "",
            ])

    # جهت کلی فقط بر اساس داده‌هایی که واقعاً قیمت دارند.
    direction_values = []
    for key in (
        "dollar",
        "gold_18",
        "gold_ounce",
        "silver_ounce",
        "coin_imami",
    ):
        item = data.get(key)
        if item and item.get("change_percent") is not None:
            direction_values.append(item["change_percent"])

    if direction_values:
        average_change = sum(direction_values) / len(direction_values)
        if average_change > 0.30:
            direction = "📈 صعودی"
        elif average_change < -0.30:
            direction = "📉 نزولی"
        else:
            direction = "➡️ متعادل"
    else:
        direction = "⚪ بدون داده کافی"

    lines.extend([
        "📌 جمع‌بندی بازار",
        "──────────────",
        f"نبض کلی: {direction}",
        "",
        "ℹ️ درصدها نسبت به نرخ روز قبل هستند.",
        "ℹ️ حباب از اختلاف قیمت بازار و ارزش ذاتی محاسبه شده است.",
        "",
        "🔄 تمام قیمت‌های درج‌شده از داده زنده منابع قیمت دریافت شده‌اند.",
        "",
        channel_footer(),
    ])

    return "\n".join(lines)


# =========================================================
# AI ECONOMY LESSON
# =========================================================

def ai_economy_lesson_sync():

    if not OPENAI_API_KEY:

        return None

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url="https://1xai.ir/v1"
    )

    prompt = """
برای کانال تلگرامی «یزدان‌دوست» یک پست کوتاه آموزشی اقتصادی بنویس.

موضوع باید برای مخاطب بازار نقره و سرمایه‌گذاری عمومی مفید باشد.

قوانین:
- 60 تا 100 کلمه
- ساده و قابل فهم
- حرفه‌ای
- بدون پیش‌بینی قیمت
- بدون اطلاعات ساختگی
- بدون Markdown
- بدون هشتگ
- عنوان جذاب داشته باشد
- در پایان یک سؤال کوتاه برای تعامل مخاطب داشته باشد.
- موضوع آموزش نباید درباره قیمت یا نرخ دلار،
  قیمت یا نرخ طلا، قیمت سکه یا نرخ ارزها باشد.

موضوع را خودت از بین این موارد انتخاب کن:
نرخ بهره، تورم، انس جهانی نقره، عرضه و تقاضا،
فلزات گرانبها، فدرال رزرو.
"""

    response = client.responses.create(

        model=OPENAI_MODEL,

        instructions=(
            "محتوای آموزشی اقتصادی کوتاه و دقیق تولید کن."
        ),

        input=prompt

    )

    return clean_ai_output(
        response.output_text
    )


async def ai_economy_lesson():

    return await asyncio.to_thread(
        ai_economy_lesson_sync
    )


# =========================================================
# MARKET ANALYSIS / SUPPORT & RESISTANCE
# =========================================================

def tradingview_scan_sync():
    """
    دریافت آخرین قیمت و شاخص‌های تکنیکال روزانه مستقیماً از TradingView.
    این داده‌ها برای گزارش روزانه بازار استفاده می‌شوند و جایگزین
    قیمت‌های قبلی ربات، قیمت تابلو و Yahoo در این گزارش هستند.
    """

    columns = [
        "close",
        "change",
        "change_abs",
        "open",
        "high",
        "low",
        "Perf.5D",
        "Recommend.All|1D",
        "Recommend.MA|1D",
        "Recommend.Other|1D",
        "RSI|1D",
        "MACD.macd|1D",
        "MACD.signal|1D",
        "EMA20|1D",
        "SMA50|1D",
        "SMA200|1D",
        "Pivot.M.Classic.S1|1D",
        "Pivot.M.Classic.R1|1D",
        "Pivot.M.Classic.S2|1D",
        "Pivot.M.Classic.R2|1D",
    ]

    tickers = list(MARKET_TRADINGVIEW_SYMBOLS.values())

    response = requests.post(
        "https://scanner.tradingview.com/global/scan",
        json={
            "symbols": {
                "tickers": tickers,
                "query": {"types": []},
            },
            "columns": columns,
            "range": [0, len(tickers)],
        },
        headers={
            "User-Agent":
                "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)",
            "Content-Type": "application/json",
            "Origin": "https://www.tradingview.com",
            "Referer": "https://www.tradingview.com/",
        },
        timeout=25,
    )

    response.raise_for_status()
    payload = response.json()

    result = {}

    for item in payload.get("data", []):
        symbol = item.get("s", "")
        values = item.get("d", [])

        row = {}
        for index, column in enumerate(columns):
            key = column.split("|", 1)[0]
            value = values[index] if index < len(values) else None
            row[key] = value

        result[symbol] = row

    if not result:
        raise RuntimeError("TradingView returned no market data")

    return result


def get_tradingview_market_data_sync():
    """داده زنده/به‌روز TradingView برای گزارش روزانه."""

    raw = tradingview_scan_sync()
    data = {}

    reverse = {
        symbol: key
        for key, symbol in MARKET_TRADINGVIEW_SYMBOLS.items()
    }

    for symbol, row in raw.items():
        key = reverse.get(symbol)
        if not key:
            continue

        data[key] = row
        log.info(
            "TRADINGVIEW DATA OK | %s | close=%s | change=%s",
            key,
            row.get("close"),
            row.get("change"),
        )

    return data


async def get_tradingview_market_data():
    return await asyncio.to_thread(
        get_tradingview_market_data_sync
    )


def yahoo_chart_sync(
    symbol,
    range_name="1mo",
    interval="1d"
):
    """
    دریافت داده تاریخی از Yahoo Finance بدون نیاز به کتابخانه اضافی.
    فقط برای تحلیل تکنیکال و عوامل کلان استفاده می‌شود.
    """

    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + symbol
    )

    params = {
        "range": range_name,
        "interval": interval,
        "includePrePost": "false",
        "events": "div,splits",
    }

    response = requests.get(
        url,
        params=params,
        headers={
            "User-Agent":
                "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)"
        },
        timeout=20
    )

    response.raise_for_status()

    payload = response.json()

    result = (
        payload
        .get("chart", {})
        .get("result")
    )

    if not result:

        raise RuntimeError(
            f"Yahoo data not available for {symbol}"
        )

    result = result[0]

    timestamps = result.get(
        "timestamp",
        []
    )

    quote = (
        result
        .get("indicators", {})
        .get("quote", [{}])[0]
    )

    closes = quote.get(
        "close",
        []
    )

    highs = quote.get(
        "high",
        []
    )

    lows = quote.get(
        "low",
        []
    )

    rows = []

    for i, timestamp in enumerate(timestamps):

        close = (
            closes[i]
            if i < len(closes)
            else None
        )

        high = (
            highs[i]
            if i < len(highs)
            else None
        )

        low = (
            lows[i]
            if i < len(lows)
            else None
        )

        if (
            close is None
            and high is None
            and low is None
        ):

            continue

        rows.append({
            "timestamp": timestamp,
            "close": (
                float(close)
                if close is not None
                else None
            ),
            "high": (
                float(high)
                if high is not None
                else None
            ),
            "low": (
                float(low)
                if low is not None
                else None
            ),
        })

    if not rows:

        raise RuntimeError(
            f"No usable Yahoo rows for {symbol}"
        )

    return rows


def get_yahoo_market_data_sync():

    data = {}

    for key, symbol in MARKET_YAHOO_SYMBOLS.items():

        try:

            rows = yahoo_chart_sync(
                symbol,
                range_name="3mo",
                interval="1d"
            )

            data[key] = rows

            log.info(
                "MARKET DATA OK | %s | rows=%s",
                key,
                len(rows)
            )

        except Exception as error:

            log.warning(
                "MARKET DATA FAILED | %s | %s",
                key,
                error
            )

    return data


async def get_yahoo_market_data():

    return await asyncio.to_thread(
        get_yahoo_market_data_sync
    )


def nearest_support_resistance(
    rows,
    current,
    lookback=45
):

    if not rows or current is None:

        return {
            "support": None,
            "resistance": None,
            "support_2": None,
            "resistance_2": None,
        }

    usable = [
        row
        for row in rows[-lookback:]
        if (
            row.get("high") is not None
            and
            row.get("low") is not None
        )
    ]

    if len(usable) < 5:

        return {
            "support": None,
            "resistance": None,
            "support_2": None,
            "resistance_2": None,
        }

    supports = []
    resistances = []

    # کف/سقف‌های محلی سه‌روزه.
    for i in range(
        1,
        len(usable) - 1
    ):

        prev_row = usable[i - 1]
        row = usable[i]
        next_row = usable[i + 1]

        if (
            row["low"] <= prev_row["low"]
            and
            row["low"] <= next_row["low"]
        ):

            supports.append(
                row["low"]
            )

        if (
            row["high"] >= prev_row["high"]
            and
            row["high"] >= next_row["high"]
        ):

            resistances.append(
                row["high"]
            )

    below = sorted(
        {
            round(value, 4)
            for value in supports
            if value < current
        },
        reverse=True
    )

    above = sorted(
        {
            round(value, 4)
            for value in resistances
            if value > current
        }
    )

    # اگر نقطه محلی مناسب پیدا نشد، از کمینه/بیشینه اخیر
    # به‌عنوان سطح پشتیبان/مقاومت پشتیبان استفاده می‌کنیم.
    recent_lows = [
        row["low"]
        for row in usable
        if row["low"] is not None
        and row["low"] < current
    ]

    recent_highs = [
        row["high"]
        for row in usable
        if row["high"] is not None
        and row["high"] > current
    ]

    if not below and recent_lows:

        below = [
            round(
                max(recent_lows),
                4
            )
        ]

    if not above and recent_highs:

        above = [
            round(
                min(recent_highs),
                4
            )
        ]

    return {
        "support":
            below[0]
            if below
            else None,

        "support_2":
            below[1]
            if len(below) > 1
            else None,

        "resistance":
            above[0]
            if above
            else None,

        "resistance_2":
            above[1]
            if len(above) > 1
            else None,
    }


def percent_change(
    current,
    previous
):

    if (
        current is None
        or previous in (None, 0)
    ):

        return None

    return (
        (current - previous)
        / abs(previous)
        * 100
    )


def append_market_history(
    state,
    rate,
    products,
    gold_ounce=None
):

    history = state.get(
        "market_history",
        []
    )

    if not isinstance(
        history,
        list
    ):

        history = []

    item = {
        "timestamp":
            iran_now().isoformat(),

        "tehran":
            (
                float(rate["tehran"])
                if rate
                else None
            ),

        "silver_ounce":
            (
                float(rate["ounce"])
                if rate
                else None
            ),

        "gold_ounce":
            (
                float(gold_ounce)
                if gold_ounce is not None
                else state.get("gold_ounce")
            ),

        "shot_995":
            (
                float(products["shot_995"])
                if products
                else None
            ),
    }

    history.append(item)

    state[
        "market_history"
    ] = history[
        -MARKET_HISTORY_LIMIT:
    ]


def market_history_for_key(
    state,
    key
):

    history = state.get(
        "market_history",
        []
    )

    if not isinstance(
        history,
        list
    ):

        return []

    result = []

    for item in history:

        value = item.get(
            key
        )

        if value is None:

            continue

        try:

            result.append(
                (
                    item.get(
                        "timestamp",
                        ""
                    ),
                    float(value)
                )
            )

        except (
            TypeError,
            ValueError
        ):

            continue

    return result


def local_levels_from_history(
    state,
    key,
    current
):

    points = [
        value
        for _, value
        in market_history_for_key(
            state,
            key
        )
    ]

    if len(points) < 5:

        return {
            "support": None,
            "resistance": None,
            "support_2": None,
            "resistance_2": None,
        }

    rows = [
        {
            "high": value,
            "low": value,
        }
        for value in points
    ]

    return nearest_support_resistance(
        rows,
        current,
        lookback=min(
            len(rows),
            60
        )
    )


def latest_market_value(
    rows
):

    if not rows:

        return None

    for row in reversed(rows):

        if row.get("close") is not None:

            return row["close"]

    return None


def build_market_analysis_snapshot(
    state,
    rate,
    products,
    gold_ounce,
    tradingview_data
):
    """
    اسنپ‌شات گزارش روزانه فقط از TradingView ساخته می‌شود.
    قیمت‌های rate / products / gold_ounce عمداً برای تحلیل بازار استفاده نمی‌شوند.
    """

    snapshot = {}

    for key in (
        "silver",
        "gold",
        "dxy",
        "oil",
        "us10y",
        "sp500",
        "vix",
    ):
        row = tradingview_data.get(key, {})
        current = row.get("close")

        if current is None:
            continue

        levels = {
            "support": row.get("Pivot.M.Classic.S1"),
            "resistance": row.get("Pivot.M.Classic.R1"),
            "support_2": row.get("Pivot.M.Classic.S2"),
            "resistance_2": row.get("Pivot.M.Classic.R2"),
        }

        snapshot[key] = {
            "current": current,
            "daily_change_percent": row.get("change"),
            "five_day_change_percent": row.get("Perf.5D"),
            "levels": levels,
            "rsi": row.get("RSI"),
            "macd": row.get("MACD.macd"),
            "macd_signal": row.get("MACD.signal"),
            "ema20": row.get("EMA20"),
            "sma50": row.get("SMA50"),
            "sma200": row.get("SMA200"),
            "recommend_all": row.get("Recommend.All"),
            "recommend_ma": row.get("Recommend.MA"),
            "recommend_other": row.get("Recommend.Other"),
        }

    # دلار فقط از TradingView و به‌صورت USD/IRR گرفته می‌شود.
    # برای نمایش تومان، مقدار ریال بر ۱۰ تقسیم می‌شود.
    usd_irr = tradingview_data.get("usd_irr", {})
    if usd_irr.get("close") is not None:
        usd_irr_current = float(usd_irr["close"])
        snapshot["tradingview_usd_irr"] = {
            "current_irr": usd_irr_current,
            "current_toman": usd_irr_current / 10.0,
            "daily_change_percent": usd_irr.get("change"),
            "five_day_change_percent": usd_irr.get("Perf.5D"),
            "levels": {
                "support": usd_irr.get("Pivot.M.Classic.S1"),
                "resistance": usd_irr.get("Pivot.M.Classic.R1"),
                "support_2": usd_irr.get("Pivot.M.Classic.S2"),
                "resistance_2": usd_irr.get("Pivot.M.Classic.R2"),
            },
            "rsi": usd_irr.get("RSI"),
            "macd": usd_irr.get("MACD.macd"),
            "macd_signal": usd_irr.get("MACD.signal"),
            "ema20": usd_irr.get("EMA20"),
            "sma50": usd_irr.get("SMA50"),
            "sma200": usd_irr.get("SMA200"),
            "recommend_all": usd_irr.get("Recommend.All"),
            "recommend_ma": usd_irr.get("Recommend.MA"),
            "recommend_other": usd_irr.get("Recommend.Other"),
        }

    # قیمت فعلی ساچمه ۹۹۵ برای گزارش عمومی کانال.
    # شاخص‌های جهانی همچنان از TradingView گرفته می‌شوند.
    if isinstance(products, dict):
        shot_995 = products.get("shot_995")

        if shot_995 is None:
            shot_package = products.get("shot_package")
            if shot_package is not None:
                try:
                    shot_995 = float(shot_package) / 1000.0
                except (TypeError, ValueError):
                    shot_995 = None

        if shot_995 is not None:
            try:
                snapshot["shot_995"] = {
                    "current": float(shot_995)
                }
            except (TypeError, ValueError):
                pass

    silver_current = snapshot.get("silver", {}).get("current")
    gold_current = snapshot.get("gold", {}).get("current")

    if silver_current and gold_current and silver_current > 0:
        snapshot["gold_silver_ratio"] = gold_current / silver_current

    return snapshot


def format_level(
    value,
    decimals=2
):

    if value is None:

        return "نامشخص"

    return f"{value:,.{decimals}f}"


def market_analysis_text_fallback(
    snapshot
):
    """نسخه کوتاه و ساده برای انتشار عمومی در کانال."""
    def fmt(value, decimals=0):
        if value is None:
            return None
        return f"{value:,.{decimals}f}"

    silver = snapshot.get("silver", {})
    shot = snapshot.get("shot_995", {})
    gold = snapshot.get("gold", {})
    dxy = snapshot.get("dxy", {})
    usd = snapshot.get("tradingview_usd_irr", {})

    daily = silver.get("daily_change_percent")
    support = silver.get("levels", {}).get("support")
    support2 = silver.get("levels", {}).get("support_2")
    resistance = silver.get("levels", {}).get("resistance")

    if daily is not None and daily > 1:
        status = "🟢 صعودی"
    elif daily is not None and daily < -1:
        status = "🔴 نزولی"
    else:
        status = "🟡 خنثی"

    parts = [
        "📊 تحلیل روزانه نقره | یزدان‌دوست",
        "━━━━━━━━━━━━━━",
        "",
    ]

    if shot.get("current") is not None:
        parts.append(f"🥈 ساچمه ۹۹۵: {fmt(shot['current'])} تومان")

    if daily is not None:
        parts.append(f"📈 تغییر امروز: {daily:+.2f}٪")

    supports = [fmt(x) for x in (support, support2) if x is not None]
    if supports:
        parts.append(f"🎯 حمایت: {' و '.join(supports)} تومان")

    if resistance is not None:
        parts.append(f"🚧 مقاومت: {fmt(resistance)} تومان")

    if silver.get("current") is not None:
        line = f"🌍 انس نقره: {fmt(silver['current'], 2)} دلار"
        if silver.get("five_day_change_percent") is not None:
            line += f" | ۵روزه {silver['five_day_change_percent']:+.2f}٪"
        parts.append(line)

    if gold.get("daily_change_percent") is not None:
        parts.append(
            f"🥇 طلا: تغییر امروز {gold['daily_change_percent']:+.2f}٪؛ "
            "رشد طلا معمولاً به نفع نقره است."
        )

    if usd.get("daily_change_percent") is not None:
        parts.append(
            f"💵 دلار (شاخص جهت دلار): {usd['daily_change_percent']:+.2f}٪"
        )

    if dxy.get("daily_change_percent") is not None:
        parts.append(
            f"📊 DXY (شاخص قدرت دلار آمریکا): "
            f"{dxy['daily_change_percent']:+.2f}٪"
        )

    parts.extend([
        "",
        f"📌 وضعیت بازار: {status}",
        "📝 نتیجه: تمرکز اصلی روی حمایت و مقاومت‌های بالا باشد؛ "
        "عبور و تثبیت بالای مقاومت می‌تواند نشانه ادامه رشد باشد.",
        "",
        "⚠️ این تحلیل احتمالی است و توصیه خرید یا فروش نیست.",
    ])

    return "\n".join(parts)


def ai_market_analysis_sync(
    snapshot
):

    if not OPENAI_API_KEY:

        return market_analysis_text_fallback(
            snapshot
        )

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url="https://1xai.ir/v1"
    )

    prompt = f"""
برای کانال «یزدان‌دوست» یک «تحلیل روزانه نقره» بنویس.
مخاطب عمومی است و ممکن است هیچ آشنایی با بازارهای مالی نداشته باشد.
تحلیل باید کوتاه، روان، قابل فهم و کاربردی باشد.

داده‌های واقعی:
{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}

قالب خروجی نزدیک به این ساختار باشد:

📊 تحلیل روزانه نقره | یزدان‌دوست
━━━━━━━━━━━━━━

🥈 ساچمه ۹۹۵: ...
📈 تغییر امروز: ...
🎯 حمایت: ...
🚧 مقاومت: ...
🌍 انس نقره: ...
🥇 طلا: ...
💵 دلار (شاخص جهت دلار): ...
📊 DXY (شاخص قدرت دلار آمریکا): ...

📌 وضعیت بازار: 🟢 صعودی / 🟡 خنثی / 🔴 نزولی

📝 نتیجه: در ۱ تا ۲ جمله ساده بگو بازار فعلاً چه وضعیتی دارد و مهم‌ترین عددی که باید زیر نظر باشد چیست.

قواعد:
- حداکثر حدود 180 کلمه.
- فقط از داده‌های ورودی استفاده کن و هیچ عددی نساز.
- قیمت ساچمه ۹۹۵ را از shot_995 بردار.
- انس نقره را از silver و طلا را از gold بردار.
- حمایت و مقاومت را از levels نقره بردار.
- USD/IRR را فقط با عنوان «دلار (شاخص جهت دلار)» توضیح بده؛ آن را قیمت دلار تهران یا قیمت تابلو معرفی نکن.
- DXY را با توضیح «شاخص قدرت دلار آمریکا» بنویس.
- اگر داده یک شاخص موجود نیست، آن بخش را حذف کن.
- WTI، US10Y، S&P500، VIX، نسبت طلا/نقره، RSI و رتبه تکنیکال را در گزارش روزانه نیاور.
- از اصطلاحات سنگین و توضیحات اقتصادی پیچیده استفاده نکن.
- وضعیت بازار را بر اساس مجموع داده‌ها تعیین کن، نه فقط یک عدد.
- اگر داده‌ها متناقض هستند، «🟡 خنثی» را انتخاب کن.
- بدون جدول، بدون هشتگ و بدون توضیح اضافه.
"""

    try:

        response = client.responses.create(

            model=OPENAI_MODEL,

            instructions=(
                "تو تحلیلگر محافظه‌کار بازار فلزات گرانبها هستی. "
                "فقط از داده‌های ارائه‌شده استفاده کن و خروجی را کوتاه، "
                "ساده و مناسب مخاطب عمومی کانال تلگرام بنویس."
            ),

            input=prompt
        )

        result = clean_ai_output(
            response.output_text
        )

        if result:

            return result

    except Exception as error:

        log.exception(
            "AI MARKET ANALYSIS FAILED: %s",
            error
        )

    return market_analysis_text_fallback(
        snapshot
    )


async def ai_market_analysis(
    snapshot
):

    return await asyncio.to_thread(
        ai_market_analysis_sync,
        snapshot
    )


def should_send_market_analysis(
    state
):

    # جمعه گزارش اختصاصی هفتگی ساعت ۲۰ منتشر می‌شود؛
    # گزارش بازار ساعت ۲۲:۰۰ در جمعه تکراری است.
    if is_friday():
        return False

    current_minute = current_minutes()

    start = (
        MARKET_ANALYSIS_HOUR * 60
        + MARKET_ANALYSIS_MINUTE
    )

    if not (
        start
        <=
        current_minute
        <
        start + 20
    ):

        return False

    last = state.get(
        "market_analysis_sent_at"
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

        days = (
            iran_now().date()
            -
            last_dt.astimezone(
                IRAN_TZ
            ).date()
        ).days

        return (
            days
            >=
            MARKET_ANALYSIS_INTERVAL_DAYS
        )

    except Exception:

        return True


def mark_market_analysis_sent(
    state
):

    state[
        "market_analysis_sent_at"
    ] = iran_now().isoformat()


def price_alerts(
    state,
    rate,
    products
):

    """
    هشدارها را بر اساس آخرین نقطه‌ای که هشدار داده شده
    محاسبه می‌کند تا پیام‌ها بیش از حد زیاد نشوند.
    """

    alerts = []

    if rate is None or products is None:

        return alerts

    # -------------------------
    # انس نقره: هر ۱.۵ دلار
    # -------------------------

    current_silver = float(
        rate["ounce"]
    )

    last_silver = state.get(
        "silver_alert_base"
    )

    if last_silver is not None:

        try:

            last_silver = float(
                last_silver
            )

            difference = (
                current_silver
                -
                last_silver
            )

            if abs(difference) >= SILVER_OUNCE_ALERT_STEP:

                direction = (
                    "افزایش"
                    if difference > 0
                    else
                    "کاهش"
                )

                alerts.append(
                    (
                        "🥈 هشدار انس نقره\n"
                        "━━━━━━━━━━━━━━\n"
                        f"انس نقره {direction} داشته است.\n"
                        f"نقطه هشدار قبلی: {last_silver:.2f}$\n"
                        f"نرخ فعلی: {current_silver:.2f}$\n"
                        f"تغییر: {difference:+.2f}$\n"
                        f"این حرکت می‌تواند روی قیمت ساچمه نقره "
                        "اثر مستقیم داشته باشد."
                    )
                )

                state[
                    "silver_alert_base"
                ] = current_silver

        except (
            TypeError,
            ValueError
        ):

            state[
                "silver_alert_base"
            ] = current_silver

    else:

        state[
            "silver_alert_base"
        ] = current_silver

    # -------------------------
    # درصدی: طلا / دلار / ساچمه
    # -------------------------

    percent_items = [
        (
            "gold",
            "🥇 هشدار انس طلا",
            float(rate["gold_ounce"])
            if rate.get("gold_ounce") is not None
            else None,
            GOLD_OUNCE_ALERT_PERCENT
        ),
        (
            "dollar",
            "💵 هشدار دلار تهران",
            float(rate["tehran"]),
            DOLLAR_ALERT_PERCENT
        ),
        (
            "shot",
            "🥈 هشدار قیمت ساچمه",
            float(products["shot_995"]),
            SHOT_ALERT_PERCENT
        ),
    ]

    for key, title, current, threshold in percent_items:

        if current is None:

            continue

        state_key = (
            f"{key}_alert_base"
        )

        previous = state.get(
            state_key
        )

        if previous is None:

            state[
                state_key
            ] = current

            continue

        try:

            previous = float(
                previous
            )

        except (
            TypeError,
            ValueError
        ):

            state[
                state_key
            ] = current

            continue

        change = percent_change(
            current,
            previous
        )

        if (
            change is not None
            and
            abs(change)
            >= threshold
        ):

            direction = (
                "افزایش"
                if change > 0
                else
                "کاهش"
            )

            unit = (
                "دلار"
                if key == "gold"
                else
                "تومان"
                if key == "dollar"
                else
                "تومان به ازای هر گرم"
            )

            alerts.append(
                (
                    f"{title}\n"
                    "━━━━━━━━━━━━━━\n"
                    f"{direction} {abs(change):.2f}٪ نسبت به "
                    "آخرین نقطه هشدار.\n"
                    f"نرخ فعلی: {format_level(current)} {unit}\n"
                    f"آستانه هشدار: {threshold:.0f}٪"
                )
            )

            state[
                state_key
            ] = current

    return alerts


# =========================================================
# WEEKLY SILVER ANALYSIS
# =========================================================

def weekly_market_history(
    state,
    key
):
    """
    شنبه تا پنجشنبه هفته جاری را از تاریخچه قیمت جدا می‌کند.
    جمعه عمداً وارد نمودار نمی‌شود.
    """
    history = state.get(
        "market_history",
        []
    )

    if not isinstance(history, list):
        return []

    now = iran_now()

    # جمعه گزارش می‌شود؛ بازه شنبه تا پنجشنبه.
    start_date = (
        now.date()
        - timedelta(days=6)
    )
    end_date = (
        now.date()
        - timedelta(days=1)
    )

    rows = []

    for item in history:
        value = item.get(key)

        if value is None:
            continue

        timestamp = item.get("timestamp")

        try:
            dt = datetime.fromisoformat(
                timestamp
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=IRAN_TZ
                )

            dt = dt.astimezone(
                IRAN_TZ
            )

            if (
                start_date
                <= dt.date()
                <= end_date
            ):
                rows.append({
                    "datetime": dt,
                    "value": float(value)
                })

        except (
            TypeError,
            ValueError
        ):
            continue

    return rows


def weekly_stats(
    rows
):
    if not rows:
        return {
            "start": None,
            "end": None,
            "high": None,
            "low": None,
            "change_percent": None,
            "change_value": None
        }

    values = [
        row["value"]
        for row in rows
        if row.get("value") is not None
    ]

    if not values:
        return {
            "start": None,
            "end": None,
            "high": None,
            "low": None,
            "change_percent": None,
            "change_value": None
        }

    start = values[0]
    end = values[-1]

    return {
        "start": start,
        "end": end,
        "high": max(values),
        "low": min(values),
        "change_percent": percent_change(
            end,
            start
        ),
        "change_value": (
            end - start
            if start is not None
            and end is not None
            else None
        )
    }


def weekly_news_titles(
    state
):
    """
    خبرهای ثبت‌شده شنبه تا پنجشنبه را برمی‌گرداند.
    اگر آرشیو زمان‌دار هنوز وجود نداشته باشد،
    از عنوان‌های اخیر به‌عنوان fallback استفاده می‌شود.
    """
    archive = state.get(
        "news_archive",
        []
    )

    if isinstance(archive, list):
        now = iran_now()
        start_date = now.date() - timedelta(days=6)
        end_date = now.date() - timedelta(days=1)

        result = []

        for item in archive:
            timestamp = item.get("timestamp")

            try:
                dt = datetime.fromisoformat(
                    timestamp
                )

                if dt.tzinfo is None:
                    dt = dt.replace(
                        tzinfo=IRAN_TZ
                    )

                dt = dt.astimezone(
                    IRAN_TZ
                )

            except (
                TypeError,
                ValueError
            ):
                continue

            if (
                start_date
                <= dt.date()
                <= end_date
            ):
                title = (
                    item.get("title")
                    or ""
                ).strip()

                if title:
                    result.append(title)

        # حذف تکراری‌ها و محدود کردن ورودی AI.
        unique = []
        seen = set()

        for title in reversed(result):
            normalized = normalize_for_similarity(
                title
            )

            if normalized in seen:
                continue

            seen.add(normalized)
            unique.append(title)

            if len(unique) >= 20:
                break

        return list(reversed(unique))

    titles = state.get(
        "news_title_history",
        []
    )

    if not isinstance(titles, list):
        return []

    return [
        str(title)
        for title in titles[-15:]
        if str(title).strip()
    ]


def weekly_analysis_snapshot(
    state,
    rate,
    products,
    yahoo_data
):
    silver_rows = weekly_market_history(
        state,
        "silver_ounce"
    )

    dollar_rows = weekly_market_history(
        state,
        "tehran"
    )

    shot_rows = weekly_market_history(
        state,
        "shot_995"
    )

    gold_rows = weekly_market_history(
        state,
        "gold_ounce"
    )

    snapshot = {
        "silver_ounce": weekly_stats(
            silver_rows
        ),
        "tehran_dollar": weekly_stats(
            dollar_rows
        ),
        "shot_995": weekly_stats(
            shot_rows
        ),
        "gold_ounce": weekly_stats(
            gold_rows
        ),
        "news_titles": weekly_news_titles(
            state
        )
    }

    # در صورت کمبود تاریخچه، آخرین نرخ فعلی را برای نمایش نگه می‌داریم.
    if rate:
        snapshot[
            "current_silver_ounce"
        ] = float(
            rate["ounce"]
        )

        snapshot[
            "current_tehran_dollar"
        ] = float(
            rate["tehran"]
        )

    if products:
        snapshot[
            "current_shot_995"
        ] = float(
            products["shot_995"]
        )

    # حمایت/مقاومت انس نقره از داده سه‌ماهه جهانی.
    silver_global = yahoo_data.get(
        "silver",
        []
    )

    current_silver = (
        snapshot[
            "current_silver_ounce"
        ]
        if snapshot.get(
            "current_silver_ounce"
        ) is not None
        else latest_market_value(
            silver_global
        )
    )

    snapshot[
        "silver_levels"
    ] = nearest_support_resistance(
        silver_global,
        current_silver,
        lookback=min(
            len(silver_global),
            60
        )
    )

    return snapshot


def ai_weekly_silver_analysis_sync(
    snapshot
):
    if not OPENAI_API_KEY:
        return weekly_analysis_fallback(
            snapshot
        )

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url="https://1xai.ir/v1"
    )

    prompt = f"""
برای کانال «ساچمه نقره یزدان‌دوست» یک تحلیل کامل و حرفه‌ای
از هفته‌ای که گذشت و چشم‌انداز احتمالی هفته آینده نقره بنویس.

داده‌های عددی این هفته:
{json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)}

قوانین بسیار مهم:
- تحلیل را فقط بر اساس داده‌های ورودی بنویس.
- انس نقره و دلار تهران را دو عامل اصلی قرار بده.
- توضیح بده تغییر این دو عامل چه اثری بر نقره داخلی داشته است.
- خبرهای ثبت‌شده هفته را بررسی کن و فقط اگر واقعاً مرتبط هستند
  اثر احتمالی آنها بر نقره را توضیح بده.
- از ساختن خبر، عدد، حمایت یا مقاومت جدید خودداری کن.
- اگر داده کافی برای یک بخش وجود ندارد، صریحاً بگو «داده کافی نداریم».
- برای هفته آینده سه سناریو بده:
  سناریوی صعودی، سناریوی خنثی/نوسانی، سناریوی نزولی.
- بگو کدام سناریو در حال حاضر محتمل‌تر است و چرا،
  اما از قطعیت و توصیه خرید/فروش خودداری کن.
- حمایت و مقاومت انس نقره را فقط از داده ورودی استفاده کن.
- عملکرد هفتگی را با درصد تغییر واقعی توضیح بده.
- 260 تا 380 کلمه.
- فارسی روان، حرفه‌ای و مناسب مشتری عمومی.
- بدون Markdown و بدون هشتگ.
- عنوان کوتاه و جذاب داشته باشد.
"""

    try:
        response = client.responses.create(
            model=OPENAI_MODEL,
            instructions=(
                "تو تحلیلگر محافظه‌کار بازار نقره و فلزات گرانبها هستی. "
                "خبر و عدد اختراع نکن و بین واقعیت داده‌شده و سناریوی احتمالی تفاوت بگذار."
            ),
            input=prompt
        )

        result = clean_ai_output(
            response.output_text
        )

        if result:
            return result

    except Exception as error:
        log.exception(
            "AI WEEKLY SILVER ANALYSIS FAILED: %s",
            error
        )

    return weekly_analysis_fallback(
        snapshot
    )


def weekly_analysis_fallback(
    snapshot
):
    silver = snapshot.get(
        "silver_ounce",
        {}
    )

    dollar = snapshot.get(
        "tehran_dollar",
        {}
    )

    shot = snapshot.get(
        "shot_995",
        {}
    )

    silver_change = silver.get(
        "change_percent"
    )

    dollar_change = dollar.get(
        "change_percent"
    )

    shot_change = shot.get(
        "change_percent"
    )

    if silver_change is None:
        silver_view = (
            "برای محاسبه دقیق تغییر هفتگی انس نقره، داده کافی نداریم."
        )
    elif silver_change > 0:
        silver_view = (
            f"انس نقره در هفته گذشته {silver_change:.2f}٪ رشد کرد."
        )
    elif silver_change < 0:
        silver_view = (
            f"انس نقره در هفته گذشته {abs(silver_change):.2f}٪ افت کرد."
        )
    else:
        silver_view = (
            "انس نقره در هفته گذشته تقریباً بدون تغییر بود."
        )

    if dollar_change is None:
        dollar_view = (
            "برای تغییر هفتگی دلار تهران داده کافی نداریم."
        )
    elif dollar_change > 0:
        dollar_view = (
            f"دلار تهران نیز {dollar_change:.2f}٪ افزایش داشت."
        )
    elif dollar_change < 0:
        dollar_view = (
            f"دلار تهران {abs(dollar_change):.2f}٪ کاهش داشت."
        )
    else:
        dollar_view = (
            "دلار تهران در هفته گذشته تقریباً متعادل بود."
        )

    levels = snapshot.get(
        "silver_levels",
        {}
    )

    support = levels.get(
        "support"
    )

    resistance = levels.get(
        "resistance"
    )

    if (
        silver_change is not None
        and silver_change > 0
        and (
            dollar_change is None
            or dollar_change >= 0
        )
    ):
        outlook = (
            "سناریوی مثبت فعلاً دست بالاتر را دارد؛ "
            "اما ادامه حرکت به حفظ حمایت‌های مهم و رفتار دلار و انس وابسته است."
        )
    elif (
        silver_change is not None
        and silver_change < 0
        and dollar_change is not None
        and dollar_change < 0
    ):
        outlook = (
            "فشار نزولی بیشتر شده است و شکست حمایت‌های مهم می‌تواند "
            "ریسک افت بیشتر را افزایش دهد."
        )
    else:
        outlook = (
            "سناریوی نوسانی محتمل‌تر است و جهت بعدی به واکنش قیمت "
            "در حمایت و مقاومت‌های مهم وابسته خواهد بود."
        )

    news_count = len(
        snapshot.get(
            "news_titles",
            []
        )
    )

    return (
        "📊 تحلیل هفتگی نقره\n"
        "━━━━━━━━━━━━━━\n\n"
        f"{silver_view}\n"
        f"{dollar_view}\n\n"
        f"🥈 ساچمه ۹۹۵: "
        f"{'داده کافی نداریم' if shot_change is None else f'{shot_change:.2f}٪ تغییر هفتگی'}\n\n"
        f"🎯 حمایت انس نقره: "
        f"{format_level(support)} دلار\n"
        f"🎯 مقاومت انس نقره: "
        f"{format_level(resistance)} دلار\n\n"
        f"📰 تعداد خبرهای ثبت‌شده مرتبط در آرشیو هفته: {news_count}\n\n"
        f"🔮 چشم‌انداز هفته آینده:\n{outlook}\n\n"
        "⚠️ این گزارش تحلیل احتمالی بازار است و توصیه خرید یا فروش نیست."
    )


async def ai_weekly_silver_analysis(
    snapshot
):
    return await asyncio.to_thread(
        ai_weekly_silver_analysis_sync,
        snapshot
    )


def draw_rtl(
    draw,
    position,
    text_value,
    font,
    fill,
    anchor="ra"
):
    try:
        draw.text(
            position,
            str(text_value),
            font=font,
            fill=fill,
            anchor=anchor,
            direction="rtl",
            language="fa"
        )
    except Exception:
        draw.text(
            position,
            str(text_value),
            font=font,
            fill=fill,
            anchor=anchor
        )


def create_weekly_silver_image(
    snapshot
):
    """
    کارت گرافیکی هفتگی با نمودار واقعی ساچمه ۹۹۵.
    لوگوی رسمی، در صورت وجود فایل کنار ربات، به‌صورت
    کم‌رنگ داخل نمودار واترمارک می‌شود.
    """
    rows = weekly_market_history(
        {
            "market_history": snapshot.get(
                "_market_history_rows",
                []
            )
        },
        "shot_995"
    )

    # در این تابع تاریخچه آماده به شکل مستقیم از snapshot دریافت می‌شود.
    raw_rows = snapshot.get(
        "chart_rows",
        []
    )

    if not raw_rows:
        raise RuntimeError(
            "داده کافی برای نمودار هفتگی نقره وجود ندارد."
        )

    width = 1400
    height = 1750

    image = Image.new(
        "RGB",
        (width, height),
        (5, 16, 15)
    )

    draw = ImageDraw.Draw(
        image
    )

    # قاب اصلی
    draw.rounded_rectangle(
        (25, 25, width - 25, height - 25),
        radius=28,
        outline=(87, 115, 98),
        width=2
    )

    title_font = get_font(58)
    subtitle_font = get_font(30)
    label_font = get_font(28)
    value_font = get_font(48)
    small_font = get_font(25)

    # سربرگ
    draw_rtl(
        draw,
        (width - 60, 65),
        "تحلیل هفتگی نقره ۹۹۵",
        title_font,
        (245, 245, 245)
    )

    draw_rtl(
        draw,
        (width - 60, 130),
        "یزدان‌دوست سیلور | جمع‌بندی هفته و چشم‌انداز هفته آینده",
        subtitle_font,
        (214, 183, 116)
    )

    # لوگو
    if YAZDANDOUST_LOGO.exists():
        try:
            logo = Image.open(
                YAZDANDOUST_LOGO
            ).convert("RGBA")

            # سفیدهای پس‌زمینه لوگو را شفاف کن.
            pixels = logo.load()
            for y in range(logo.height):
                for x in range(logo.width):
                    r, g, b, a = pixels[x, y]
                    if r > 245 and g > 245 and b > 245:
                        pixels[x, y] = (r, g, b, 0)

            logo.thumbnail(
                (250, 180),
                Image.Resampling.LANCZOS
            )

            logo_layer = Image.new(
                "RGBA",
                image.size,
                (0, 0, 0, 0)
            )

            logo_layer.alpha_composite(
                logo,
                (
                    65,
                    45
                )
            )

            image = Image.alpha_composite(
                image.convert("RGBA"),
                logo_layer
            ).convert("RGB")

            draw = ImageDraw.Draw(
                image
            )

        except Exception as error:
            log.warning(
                "WEEKLY LOGO FAILED: %s",
                error
            )

    # کارت آمار
    card_y1 = 190
    card_y2 = 390

    draw.rounded_rectangle(
        (45, card_y1, width - 45, card_y2),
        radius=22,
        fill=(10, 28, 25),
        outline=(80, 105, 91),
        width=2
    )

    shot = snapshot.get(
        "shot_995",
        {}
    )

    shot_end = shot.get("end")
    shot_change = shot.get(
        "change_percent"
    )

    change_text = (
        "داده کافی نداریم"
        if shot_change is None
        else (
            f"{'+' if shot_change > 0 else ''}"
            f"{shot_change:.2f}٪"
        )
    )

    draw_rtl(
        draw,
        (width - 80, 220),
        "قیمت پایان هفته ساچمه نقره ۹۹۵",
        label_font,
        (235, 235, 235)
    )

    draw.text(
        (75, 250),
        (
            format_price(shot_end)
            if shot_end is not None
            else "—"
        ),
        font=value_font,
        fill=(245, 245, 245)
    )

    draw_rtl(
        draw,
        (width - 80, 315),
        f"تغییر هفتگی: {change_text}",
        label_font,
        (
            (87, 220, 83)
            if shot_change is not None and shot_change >= 0
            else (238, 94, 94)
        )
    )

    # آمار انس و دلار
    stats_y = 420
    stats = [
        (
            "انس نقره",
            snapshot.get(
                "silver_ounce",
                {}
            ),
            "دلار"
        ),
        (
            "دلار تهران",
            snapshot.get(
                "tehran_dollar",
                {}
            ),
            "تومان"
        ),
        (
            "انس طلا",
            snapshot.get(
                "gold_ounce",
                {}
            ),
            "دلار"
        ),
    ]

    card_w = (
        (width - 120)
        // 3
    )

    for i, (
        label,
        stat,
        unit
    ) in enumerate(stats):

        x1 = 45 + i * (
            card_w + 15
        )
        x2 = x1 + card_w

        draw.rounded_rectangle(
            (x1, stats_y, x2, stats_y + 150),
            radius=18,
            fill=(8, 24, 22),
            outline=(66, 91, 78),
            width=2
        )

        draw_rtl(
            draw,
            (x2 - 18, stats_y + 35),
            label,
            small_font,
            (215, 215, 215)
        )

        value = stat.get(
            "end"
        )

        if value is None:
            value_text = "—"
        elif unit == "تومان":
            value_text = format_price(value)
        else:
            value_text = f"{value:,.2f}"

        draw.text(
            (x1 + 18, stats_y + 62),
            value_text,
            font=label_font,
            fill=(245, 245, 245)
        )

        pct = stat.get(
            "change_percent"
        )

        pct_text = (
            "—"
            if pct is None
            else (
                f"{'+' if pct > 0 else ''}"
                f"{pct:.2f}٪"
            )
        )

        draw.text(
            (x1 + 18, stats_y + 105),
            pct_text,
            font=small_font,
            fill=(
                (87, 220, 83)
                if pct is not None and pct >= 0
                else (238, 94, 94)
            )
        )

    # نمودار
    chart_x1 = 75
    chart_y1 = 610
    chart_x2 = width - 75
    chart_y2 = 1120

    draw.rounded_rectangle(
        (45, 590, width - 45, 1150),
        radius=22,
        fill=(7, 22, 20),
        outline=(70, 96, 83),
        width=2
    )

    draw_rtl(
        draw,
        (width - 80, 625),
        "نمودار قیمت ساچمه نقره ۹۹۵ در طول هفته",
        label_font,
        (240, 240, 240)
    )

    values = [
        row["value"]
        for row in raw_rows
        if row.get("value") is not None
    ]

    if len(values) < 2:
        raise RuntimeError(
            "داده کافی برای رسم نمودار هفتگی وجود ندارد."
        )

    vmin = min(values)
    vmax = max(values)

    padding = (
        (vmax - vmin) * 0.12
        if vmax != vmin
        else max(
            abs(vmax) * 0.01,
            1
        )
    )

    vmin -= padding
    vmax += padding

    # خطوط راهنما
    for i in range(5):
        y = (
            chart_y2
            - i
            * (
                chart_y2
                - chart_y1
            )
            / 4
        )

        draw.line(
            (chart_x1, y, chart_x2, y),
            fill=(29, 55, 48),
            width=1
        )

        value = (
            vmin
            + (
                vmax - vmin
            )
            * i
            / 4
        )

        draw.text(
            (chart_x1, int(y) - 15),
            format_price(value),
            font=small_font,
            fill=(160, 175, 166)
        )

    points = []

    for i, row in enumerate(raw_rows):
        x = (
            chart_x1
            + (
                chart_x2 - chart_x1
            )
            * i
            /
            max(
                len(raw_rows) - 1,
                1
            )
        )

        y = (
            chart_y2
            -
            (
                row["value"] - vmin
            )
            /
            max(
                vmax - vmin,
                1
            )
            *
            (
                chart_y2 - chart_y1
            )
        )

        points.append(
            (int(x), int(y))
        )

    # سطح زیر نمودار
    polygon = (
        points
        +
        [
            (
                points[-1][0],
                chart_y2
            ),
            (
                points[0][0],
                chart_y2
            )
        ]
    )

    draw.polygon(
        polygon,
        fill=(20, 58, 42)
    )

    draw.line(
        points,
        fill=(235, 235, 235),
        width=4,
        joint="curve"
    )

    # واترمارک وسط نمودار
    watermark = "YAZDANDOUST SILVER"
    wm_font = get_font(48)

    bbox = draw.textbbox(
        (0, 0),
        watermark,
        font=wm_font
    )

    wm_x = (
        chart_x1
        +
        (
            chart_x2 - chart_x1
            -
            (
                bbox[2] - bbox[0]
            )
        )
        // 2
    )

    wm_y = (
        chart_y1
        +
        chart_y2
    ) // 2

    draw.text(
        (wm_x, wm_y),
        watermark,
        font=wm_font,
        fill=(80, 100, 91)
    )

    # سقف و کف
    max_index = values.index(
        max(values)
    )

    min_index = values.index(
        min(values)
    )

    for idx, label, fill in [
        (
            min_index,
            "کف هفته",
            (90, 220, 90)
        ),
        (
            max_index,
            "سقف هفته",
            (240, 90, 90)
        )
    ]:
        x, y = points[idx]

        draw.ellipse(
            (
                x - 10,
                y - 10,
                x + 10,
                y + 10
            ),
            fill=fill
        )

        draw.text(
            (x + 16, y - 25),
            f"{label} {format_price(values[idx])}",
            font=small_font,
            fill=fill
        )

    # خلاصه پایین
    summary_y = 1190

    for i, (
        label,
        key
    ) in enumerate([
        ("شروع هفته", "start"),
        ("کف هفته", "low"),
        ("سقف هفته", "high"),
        ("پایان هفته", "end")
    ]):

        x1 = 45 + i * (
            (width - 90)
            // 4
        )

        x2 = (
            45
            +
            (i + 1)
            *
            (
                (width - 90)
                // 4
            )
        ) - 12

        draw.rounded_rectangle(
            (
                x1,
                summary_y,
                x2,
                summary_y + 125
            ),
            radius=15,
            fill=(9, 28, 24),
            outline=(57, 82, 70),
            width=2
        )

        draw_rtl(
            draw,
            (
                x2 - 12,
                summary_y + 25
            ),
            label,
            small_font,
            (190, 205, 196)
        )

        draw.text(
            (
                x1 + 12,
                summary_y + 65
            ),
            format_price(
                shot.get(key)
            )
            if shot.get(key) is not None
            else "—",
            font=small_font,
            fill=(245, 245, 245)
        )

    # سناریو و برندینگ
    levels = snapshot.get(
        "silver_levels",
        {}
    )

    scenario_y = 1350

    draw.rounded_rectangle(
        (45, scenario_y, width - 45, 1575),
        radius=22,
        fill=(9, 27, 24),
        outline=(77, 100, 87),
        width=2
    )

    draw_rtl(
        draw,
        (width - 80, scenario_y + 40),
        "چشم‌انداز هفته آینده",
        label_font,
        (238, 211, 157)
    )

    support = levels.get(
        "support"
    )

    resistance = levels.get(
        "resistance"
    )

    draw_rtl(
        draw,
        (width - 80, scenario_y + 95),
        f"حمایت انس: {format_level(support)} دلار",
        small_font,
        (100, 220, 110)
    )

    draw_rtl(
        draw,
        (width - 80, scenario_y + 135),
        f"مقاومت انس: {format_level(resistance)} دلار",
        small_font,
        (240, 100, 100)
    )

    draw.text(
        (75, scenario_y + 175),
        "@yazdandoustsilver",
        font=small_font,
        fill=(210, 210, 210)
    )

    draw_rtl(
        draw,
        (width - 80, 1535),
        "این گزارش صرفاً تحلیل بازار است و توصیه خرید یا فروش نیست.",
        ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            22
        ),
        (150, 165, 158)
    )

    image.save(
        WEEKLY_ANALYSIS_IMAGE,
        "JPEG",
        quality=96,
        optimize=True
    )

    return WEEKLY_ANALYSIS_IMAGE


async def send_weekly_silver_analysis(
    client,
    target,
    state,
    rate,
    products
):
    if not rate or not products:
        return None

    yahoo_data = await get_yahoo_market_data()

    snapshot = weekly_analysis_snapshot(
        state,
        rate,
        products,
        yahoo_data
    )

    chart_rows = weekly_market_history(
        state,
        "shot_995"
    )

    if len(chart_rows) < 5:
        log.warning(
            "WEEKLY SILVER ANALYSIS SKIPPED | "
            "NOT ENOUGH LOCAL HISTORY | rows=%s",
            len(chart_rows)
        )
        return None

    snapshot[
        "chart_rows"
    ] = chart_rows

    # برای سازگاری با fallback و محاسبات داخلی.
    snapshot[
        "_market_history_rows"
    ] = state.get(
        "market_history",
        []
    )

    analysis = await ai_weekly_silver_analysis(
        snapshot
    )

    image = create_weekly_silver_image(
        snapshot
    )

    caption = (
        "📊 تحلیل هفتگی نقره | یزدان‌دوست\n"
        "━━━━━━━━━━━━━━\n\n"
        + analysis
        + "\n\n"
        "📌 این گزارش بر اساس عملکرد انس نقره، "
        "دلار تهران، قیمت نقره داخلی و خبرهای ثبت‌شده هفته تهیه شده است."
        "\n\n"
        "📲 @yazdandoustsilver"
    )

    if len(caption) >= 4000:
        caption = caption[:3950] + "\n\n📲 @yazdandoustsilver"

    weekly_teaser = (
        "📊 تحلیل هفتگی نقره | یزدان‌دوست\n"
        "━━━━━━━━━━━━━━"
    )

    # همان محدودیت ۱۰۲۴ کاراکتری کپشن عکس تلگرام (NEWS_MEDIA_CAPTION_LIMIT)
    # که در تحلیل روزانه هم رعایت می‌شود؛ در غیر این صورت
    # MediaCaptionTooLongError می‌دهد.
    if len(caption) <= NEWS_MEDIA_CAPTION_LIMIT:

        message_id = await send_rate_post(
            client,
            target,
            image,
            caption
        )

    else:

        message_id = await send_rate_post(
            client,
            target,
            image,
            weekly_teaser[:NEWS_MEDIA_CAPTION_LIMIT]
        )

        await send_text_post(
            client,
            target,
            caption
        )

    try:
        weekly_message = await client.get_messages(
            target,
            ids=message_id
        )

        if weekly_message:
            await send_rubika_media(
                weekly_message
            )

    except Exception as error:
        log.warning(
            "WEEKLY RUBIKA MEDIA SYNC FAILED: %s",
            error
        )

    state[
        "weekly_silver_analysis_sent_at"
    ] = iran_now().isoformat()

    save_state(
        state
    )

    log.info(
        "WEEKLY SILVER ANALYSIS SENT | %s",
        message_id
    )

    return message_id


def should_send_weekly_silver_analysis(
    state
):
    if not is_friday():
        return False

    now_minutes = current_minutes()

    start = (
        WEEKLY_SILVER_ANALYSIS_HOUR
        * 60
        +
        WEEKLY_SILVER_ANALYSIS_MINUTE
    )

    if not (
        start
        <= now_minutes
        <
        start + 20
    ):
        return False

    last = state.get(
        "weekly_silver_analysis_sent_at"
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

        return (
            last_dt.astimezone(
                IRAN_TZ
            ).date()
            !=
            iran_now().date()
        )

    except Exception:
        return True


# =========================================================
# AI MARKET RECAP
# =========================================================

def ai_market_recap_sync(
    rate,
    products,
    market
):

    if not OPENAI_API_KEY:

        return None

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url="https://1xai.ir/v1"
    )

    prompt = f"""
برای کانال «یزدان‌دوست» یک جمع‌بندی بسیار کوتاه
از وضعیت بازار امروز بنویس.

داده‌های قطعی امروز:

انس نقره:
{rate['ounce']}

دلار تهران:
{rate['tehran']}

ساچمه ۹۹۵:
{products['shot_995']}

شمش ندیر ۹۹۹.۹:
{products['nader_9999']}

طلای ۱۸ مشهد:
{market['gold_18_mashhad']}

سکه امامی:
{market['coin_imami']}

قوانین:
- فقط بر اساس همین داده‌ها بنویس.
- هیچ پیش‌بینی قطعی نکن.
- تغییر قیمت را اگر داده تغییر روزانه نداریم، ادعا نکن.
- 70 تا 110 کلمه.
- لحن حرفه‌ای و خبری.
- عنوان کوتاه داشته باشد.
- در پایان یک سؤال کوتاه برای مخاطب داشته باشد.
- بدون Markdown.
- بدون هشتگ.
"""

    response = client.responses.create(

        model=OPENAI_MODEL,

        instructions=(
            "ویراستار حرفه‌ای بازار مالی و اقتصادی باش."
        ),

        input=prompt

    )

    return clean_ai_output(
        response.output_text
    )


async def ai_market_recap(
    rate,
    products,
    market
):

    return await asyncio.to_thread(

        ai_market_recap_sync,

        rate,
        products,
        market

    )


# =========================================================
# TOMORROW MARKET MESSAGE
# =========================================================

def ai_tomorrow_message_sync():

    if not OPENAI_API_KEY:

        return None

    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url="https://1xai.ir/v1"
    )

    prompt = """
برای کانال «یزدان‌دوست» یک پست کوتاه با عنوان
«👀 فردا بازار را با این موارد دنبال کنید» بنویس.

چون اطلاعات تقویم اقتصادی واقعی در اختیار تو نیست،
نباید رویداد مشخص یا عدد مشخصی اختراع کنی.

فقط 3 مورد عمومی و حرفه‌ای بنویس:
- تحولات مهم اقتصادی و سیاسی
- رفتار انس جهانی نقره
- اخبار مهم اقتصادی و سیاسی

لحن حرفه‌ای و کوتاه باشد.
در پایان سؤال یا گزینه‌های نظرسنجی ننویس؛
نظرسنجی به‌صورت دکمه‌های واقعی تلگرام جداگانه ارسال می‌شود.
بدون هشتگ و بدون Markdown.
موضوع پست نباید درباره نرخ دلار،
نرخ ارزها، قیمت طلا یا قیمت سکه باشد.
"""

    response = client.responses.create(

        model=OPENAI_MODEL,

        instructions=(
            "محتوای اقتصادی محافظه‌کار و بدون حدس تولید کن."
        ),

        input=prompt

    )

    return clean_ai_output(
        response.output_text
    )


async def ai_tomorrow_message():

    return await asyncio.to_thread(
        ai_tomorrow_message_sync
    )


# =========================================================
# PROCESS LOCK
# =========================================================

def acquire_process_lock():

    payload = {
        "pid": os.getpid(),
        "started_at": time.time()
    }

    for _ in range(2):

        try:

            fd = os.open(
                PROCESS_LOCK,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY
            )

            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

            log.info(
                "PROCESS LOCK ACQUIRED | PID=%s",
                os.getpid()
            )

            return True

        except FileExistsError:

            stale = False

            try:

                lock_data = json.loads(
                    PROCESS_LOCK.read_text(encoding="utf-8")
                )

                lock_pid = int(lock_data.get("pid", 0))
                started_at = float(lock_data.get("started_at", 0))

                if (
                    time.time() - started_at
                    > PROCESS_LOCK_STALE_SECONDS
                ):
                    stale = True
                elif lock_pid and lock_pid != os.getpid():
                    try:
                        os.kill(lock_pid, 0)
                    except ProcessLookupError:
                        stale = True
                    except PermissionError:
                        stale = False
                    except OSError:
                        stale = True

            except Exception:
                stale = True

            if stale:

                try:
                    PROCESS_LOCK.unlink(missing_ok=True)
                    continue
                except Exception as error:
                    log.error(
                        "PROCESS LOCK STALE LOCK REMOVE FAILED: %s",
                        error
                    )

            log.warning(
                "ANOTHER BOT INSTANCE IS ALREADY RUNNING -> EXIT SAFELY"
            )

            return False

        except Exception as error:

            log.exception(
                "PROCESS LOCK FAILED: %s",
                error
            )

            return False

    return False


def release_process_lock():

    try:

        if not PROCESS_LOCK.exists():
            return

        try:
            lock_data = json.loads(
                PROCESS_LOCK.read_text(encoding="utf-8")
            )
            lock_pid = int(lock_data.get("pid", 0))
        except Exception:
            lock_pid = 0

        if lock_pid in (0, os.getpid()):
            PROCESS_LOCK.unlink(missing_ok=True)
            log.info(
                "PROCESS LOCK RELEASED | PID=%s",
                os.getpid()
            )

    except Exception as error:

        log.warning(
            "PROCESS LOCK RELEASE FAILED: %s",
            error
        )


# =========================================================
# PRICE VALIDATION
# =========================================================

def _relative_change_exceeds(old, new, limit):

    try:
        old = float(old)
        new = float(new)
    except (TypeError, ValueError):
        return True

    if old <= 0 or new <= 0:
        return True

    return abs(new - old) / old > limit


def validate_price_update(rate, products, state):

    required_rate_keys = (
        "ounce",
        "tehran"
    )

    required_product_keys = (
        "shot_995",
        "nader_9999",
        "mithqal_995"
    )

    for key in required_rate_keys:
        try:
            if float(rate[key]) <= 0:
                log.error("PRICE VALIDATION FAILED | %s <= 0", key)
                return False
        except (KeyError, TypeError, ValueError):
            log.error("PRICE VALIDATION FAILED | INVALID %s", key)
            return False

    for key in required_product_keys:
        try:
            if float(products[key]) <= 0:
                log.error("PRICE VALIDATION FAILED | %s <= 0", key)
                return False
        except (KeyError, TypeError, ValueError):
            log.error("PRICE VALIDATION FAILED | INVALID %s", key)
            return False

    previous = get_saved_rate(state)

    if previous:

        checks = (
            ("ounce", previous.get("ounce"), rate.get("ounce"), MAX_OUNCE_CHANGE),
            ("tehran", previous.get("tehran"), rate.get("tehran"), MAX_TEHRAN_CHANGE),
            ("shot_995", state.get("shot_995"), products.get("shot_995"), MAX_PRODUCT_CHANGE),
            ("nader_9999", state.get("nader_9999"), products.get("nader_9999"), MAX_PRODUCT_CHANGE),
            ("mithqal_995", state.get("mithqal_995"), products.get("mithqal_995"), MAX_PRODUCT_CHANGE),
        )

        for name, old, new, limit in checks:

            if old is None:
                continue

            if _relative_change_exceeds(old, new, limit):

                log.error(
                    "PRICE VALIDATION FAILED | %s changed too much | OLD=%s | NEW=%s | LIMIT=%s%%",
                    name,
                    old,
                    new,
                    int(limit * 100)
                )

                return False

    return True



# =========================================================
# MANUAL PRICE OVERRIDES
# =========================================================
# Manual prices are optional. When no override is active, the bot continues
# using the existing automatic website prices unchanged.
MANUAL_PRICE_OVERRIDES_KEY = "manual_price_overrides"
MANUAL_COMMAND_LAST_ID_KEY = "manual_price_command_last_id"

MANUAL_PRICE_ALIASES = {
    "995": "shot_995",
    "shot": "shot_995",
    "saچمه": "shot_995",
    "ساچمه": "shot_995",
    "9999": "nader_9999",
    "999.9": "nader_9999",
    "999/9": "nader_9999",
    "nader": "nader_9999",
    "شمش": "nader_9999",
    "mithqal": "mithqal_995",
    "mithqal_995": "mithqal_995",
    "مثقال": "mithqal_995",
}

def manual_price_overrides(state):
    overrides = state.get(MANUAL_PRICE_OVERRIDES_KEY, {})
    if not isinstance(overrides, dict):
        return {}
    return overrides

def cleanup_manual_price_overrides(state):
    overrides = manual_price_overrides(state)
    now = iran_now()
    changed = False

    for key in list(overrides.keys()):
        item = overrides.get(key)
        if not isinstance(item, dict):
            overrides.pop(key, None)
            changed = True
            continue

        expires_at = item.get("expires_at")
        if expires_at:
            try:
                expires = datetime.fromisoformat(str(expires_at))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=ZoneInfo("Asia/Tehran"))
                if expires <= now:
                    overrides.pop(key, None)
                    changed = True
            except Exception:
                # Invalid expiry is safer treated as expired.
                overrides.pop(key, None)
                changed = True

    if changed:
        state[MANUAL_PRICE_OVERRIDES_KEY] = overrides
        save_state(state)

    return overrides

def calculate_mithqal_995_from_gram_price(shot_995_per_gram):
    """Calculate the 995 silver mithqal from the current per-gram price."""
    try:
        value = float(shot_995_per_gram) * MITHQAL_GRAMS
    except (TypeError, ValueError):
        return None

    # Keep the board's existing تومان rounding convention (nearest 100).
    return int(round(value / 100) * 100)


def apply_manual_price_overrides(state, products):
    overrides = cleanup_manual_price_overrides(state)

    if not overrides:
        return products

    if products is None:
        products = get_saved_products(state)

    if products is None:
        return None

    result = dict(products)

    for key, item in overrides.items():
        if not isinstance(item, dict):
            continue
        try:
            price = int(item["price"])
        except Exception:
            continue

        if key == "shot_995":
            result["shot_995"] = price
            result["shot_package"] = price * 1000

        elif key == "nader_9999":
            result["nader_9999"] = price
            result["nader_package"] = price * 1000

        elif key == "mithqal_995":
            result["mithqal_995"] = price

    # IMPORTANT: whenever 995 per-gram is manually controlled, the mithqal
    # is ALWAYS derived from that same 995 price. This intentionally wins
    # over an older/stale manual mithqal override so the board can never show
    # a mismatched mithqal after the user changes the 995 gram price.
    if "shot_995" in overrides:
        mithqal = calculate_mithqal_995_from_gram_price(
            result.get("shot_995")
        )
        if mithqal is not None:
            result["mithqal_995"] = mithqal

    return result

def apply_manual_rate_overrides(state, rate):
    overrides = cleanup_manual_price_overrides(state)

    if rate is None:
        rate = get_saved_rate(state)

    if rate is None:
        return None

    result = dict(rate)

    for key in ("ounce", "tehran"):
        item = overrides.get(key)
        if not isinstance(item, dict):
            continue

        try:
            value = float(item["price"]) if key == "ounce" else int(item["price"])
        except Exception:
            continue

        result[key] = value

    return result

def manual_price_help_text():
    return (
        "🛠 راهنمای قیمت‌گذاری دستی\n"
        "━━━━━━━━━━━━━━\n\n"
        "قیمت سریع ۹۹۵ برای ۳۰ دقیقه:\n"
        "995 385000 30\n\n"
        "قیمت سریع ۹۹۵ بدون انقضا:\n"
        "995 385000\n\n"
        "قیمت ۹۹۵ با دستور کامل:\n"
        "/price 995 385000\n\n"
        "قیمت شمش ۹۹۹.۹:\n"
        "/price 9999 395000\n\n"
        "قیمت مثقال ۹۹۵:\n"
        "/price mithqal 1250000\n\n"
        "قیمت موقت برای ۶۰ دقیقه:\n"
        "/price 995 385000 60\n\n"
        "برگشت ۹۹۵ به حالت خودکار:\n"
        "/auto 995\n\n"
        "برگشت همه قیمت‌ها به حالت خودکار:\n"
        "/auto all\n\n"
        "قیمت‌های دستی فقط برای حساب مدیر پذیرفته می‌شوند."
    )


# =========================================================
# INTERACTIVE PRICE MENU
# =========================================================
# The menu is intentionally implemented with Telegram Bot API reply
# keyboards because the workflow is short-lived on GitHub Actions.
# The current screen/state is persisted in state.json, so the next
# scheduled run can continue the conversation.

PRICE_MENU_STAGE_KEY = "price_menu_stage"
PRICE_MENU_FIELD_KEY = "price_menu_field"
PRICE_MENU_DRAFT_KEY = "price_menu_draft"

PRICE_MENU_CHANGE = "💰 تغییر قیمت"
PRICE_MENU_CONFIRM = "✅ ادامه"
PRICE_MENU_CANCEL = "❌ لغو"

PRICE_MENU_FIELDS = {
    "ounce": "🌐 انس",
    "tehran": "💵 دلار",
    "shot_995": "⚪ ساچمه ۹۹۵",
    "nader_9999": "🧱 شمش",
}

def _telegram_bot_api_url(method):
    return f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"


def _prepare_telegram_bot_polling():
    """Make Bot API getUpdates safe for GitHub Actions polling.

    Telegram does not allow getUpdates while a webhook is configured.
    GitHub Actions uses polling, so remove an old webhook without dropping
    queued updates. This is idempotent and runs only once per process.
    """
    global _BOT_API_POLLING_PREPARED

    if _BOT_API_POLLING_PREPARED or not BOT_TOKEN:
        return True

    try:
        response = requests.get(
            _telegram_bot_api_url("getWebhookInfo"),
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()

        if not payload.get("ok"):
            log.warning(
                "TELEGRAM WEBHOOK INFO FAILED | %s",
                payload,
            )
            return False

        webhook = (payload.get("result") or {}).get("url") or ""
        if webhook:
            log.warning(
                "TELEGRAM WEBHOOK DETECTED | removing it for getUpdates"
            )
            deleted = requests.post(
                _telegram_bot_api_url("deleteWebhook"),
                json={"drop_pending_updates": False},
                timeout=10,
            )
            deleted.raise_for_status()
            deleted_payload = deleted.json()
            if not deleted_payload.get("ok"):
                log.error(
                    "TELEGRAM WEBHOOK REMOVE FAILED | %s",
                    deleted_payload,
                )
                return False

        _BOT_API_POLLING_PREPARED = True
        log.info("TELEGRAM BOT API POLLING READY")
        return True

    except Exception as error:
        log.warning(
            "TELEGRAM BOT API POLLING PREPARE FAILED | %s",
            error,
        )
        return False


def telegram_bot_send_message(chat_id, text, reply_keyboard=None, remove_keyboard=False):
    if not BOT_TOKEN:
        return False

    payload = {
        "chat_id": int(chat_id),
        "text": str(text),
    }

    if remove_keyboard:
        payload["reply_markup"] = {"remove_keyboard": True}
    elif reply_keyboard is not None:
        payload["reply_markup"] = {
            "keyboard": reply_keyboard,
            "resize_keyboard": True,
            "one_time_keyboard": False,
            "is_persistent": True,
        }

    try:
        response = requests.post(
            _telegram_bot_api_url("sendMessage"),
            json=payload,
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            log.warning("PRICE MENU SEND FAILED | %s", data)
            return False
        return True
    except Exception as error:
        log.warning("PRICE MENU SEND FAILED | %s", error)
        return False

def _format_ounce(value):
    try:
        number = float(value)
    except Exception:
        return "—"

    if number.is_integer():
        return f"{int(number):,}"

    return f"{number:,.2f}".rstrip("0").rstrip(".")

def _effective_price_menu_values(state):
    rate = get_saved_rate(state)
    products = get_saved_products(state)

    rate = apply_manual_rate_overrides(state, rate)
    products = apply_manual_price_overrides(state, products)

    values = {
        "ounce": rate.get("ounce") if isinstance(rate, dict) else None,
        "tehran": rate.get("tehran") if isinstance(rate, dict) else None,
        "shot_995": products.get("shot_995") if isinstance(products, dict) else None,
        "nader_9999": products.get("nader_9999") if isinstance(products, dict) else None,
    }

    return values

def _price_menu_keyboard():
    return [
        [PRICE_MENU_FIELDS["ounce"], PRICE_MENU_FIELDS["tehran"]],
        [PRICE_MENU_FIELDS["shot_995"], PRICE_MENU_FIELDS["nader_9999"]],
        [PRICE_MENU_CONFIRM],
        [PRICE_MENU_CANCEL],
    ]

def _price_menu_duration_keyboard():
    return [
        ["⏱ ۵ دقیقه", "⏱ ۱۰ دقیقه"],
        ["⏱ ۱۵ دقیقه", "⏱ ۳۰ دقیقه"],
        ["♾️ نامحدود"],
        [PRICE_MENU_CANCEL],
    ]

def _price_menu_text(values, title="💰 تغییر قیمت"):
    return (
        f"{title}\n"
        "━━━━━━━━━━━━━━\n"
        "قیمت فعلی را کنار هر گزینه می‌بینی.\n"
        "هر موردی را که می‌خواهی تغییر بده؛ در پایان «ادامه» را بزن.\n\n"
        f"🌐 انس: {_format_ounce(values.get('ounce'))}\n"
        f"💵 دلار: {format_price(values['tehran']) if values.get('tehran') is not None else '—'} تومان\n"
        f"⚪ ساچمه ۹۹۵: {format_price(values['shot_995']) if values.get('shot_995') is not None else '—'} تومان\n"
        f"🧱 شمش: {format_price(values['nader_9999']) if values.get('nader_9999') is not None else '—'} تومان"
    )

def _price_menu_draft_from_state(state):
    values = _effective_price_menu_values(state)
    draft = {
        key: values.get(key)
        for key in PRICE_MENU_FIELDS
    }
    return draft

def _price_menu_has_all_values(draft):
    return all(
        draft.get(key) is not None
        for key in PRICE_MENU_FIELDS
    )

def _price_menu_save_draft(state, draft):
    state[PRICE_MENU_DRAFT_KEY] = dict(draft)
    save_state(state)

def _price_menu_clear(state):
    state.pop(PRICE_MENU_STAGE_KEY, None)
    state.pop(PRICE_MENU_FIELD_KEY, None)
    state.pop(PRICE_MENU_DRAFT_KEY, None)

def _price_menu_parse_duration(raw):
    raw = normalize_fa(raw)

    if "۵ دقیقه" in raw or "5 دقیقه" in raw:
        return 5
    if "۱۰ دقیقه" in raw or "10 دقیقه" in raw:
        return 10
    if "۱۵ دقیقه" in raw or "15 دقیقه" in raw:
        return 15
    if "۳۰ دقیقه" in raw or "30 دقیقه" in raw:
        return 30
    if "نامحدود" in raw:
        return None

    return "invalid"

def _price_menu_field_from_text(raw):
    """Resolve a price-menu button robustly, including Telegram RTL/emoji order."""
    raw = normalize_fa(raw)
    normalized = normalize_digits(raw)

    # Telegram can visually/reportedly reorder the emoji around Persian text
    # because of bidirectional (RTL/LTR) rendering.  Do not require the exact
    # byte-for-byte button label; identify the button from its meaningful words.
    compact = re.sub(r"[\s:،,:؛|]+", " ", normalized).strip()
    compact_no_emoji = re.sub(
        r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]",
        " ",
        compact,
    )
    compact_no_emoji = re.sub(r"\s+", " ", compact_no_emoji).strip()

    for key, label in PRICE_MENU_FIELDS.items():
        label_normalized = normalize_digits(normalize_fa(label))
        if normalized == label_normalized or normalized.startswith(label_normalized + ":"):
            return key

    # Explicit semantic fallbacks. These also cover messages such as
    # "ساچمه 995 ⚪" and "⚪ ساچمه ۹۹۵".
    if "ساچمه" in compact_no_emoji and "995" in compact_no_emoji:
        return "shot_995"

    if "شمش" in compact_no_emoji:
        return "nader_9999"

    if "دلار" in compact_no_emoji:
        return "tehran"

    if "انس" in compact_no_emoji:
        return "ounce"

    return None

def _price_menu_price_prompt(field):
    prompts = {
        "ounce": "🌐 قیمت جدید انس را وارد کن.\nمثال: 4625.5",
        "tehran": "💵 قیمت جدید دلار را به تومان وارد کن.\nمثال: 132500",
        "shot_995": "⚪ قیمت جدید ساچمه ۹۹۵ را به تومان وارد کن.\nمثال: 425000",
        "nader_9999": "🧱 قیمت جدید شمش را به تومان وارد کن.\nمثال: 430000",
    }
    return prompts[field]

def _price_menu_apply_draft_to_overrides(state, draft, minutes):
    now = iran_now()
    expires_at = (
        (now + timedelta(minutes=minutes)).isoformat()
        if minutes is not None
        else None
    )

    overrides = manual_price_overrides(state)

    for key in ("ounce", "tehran"):
        value = draft.get(key)
        if value is None:
            continue
        overrides[key] = {
            "price": value,
            "set_at": now.isoformat(),
            "expires_at": expires_at,
        }

    for key in ("shot_995", "nader_9999"):
        value = draft.get(key)
        if value is None:
            continue
        overrides[key] = {
            "price": int(value),
            "set_at": now.isoformat(),
            "expires_at": expires_at,
        }

    # A new 995 gram price becomes the source of truth for the 995 mithqal.
    # Remove any older explicit mithqal override so it cannot remain stale.
    if draft.get("shot_995") is not None:
        overrides.pop("mithqal_995", None)

    state[MANUAL_PRICE_OVERRIDES_KEY] = overrides
    return overrides

async def process_price_menu_message(client, state, admin_id, raw):
    """
    Handle the interactive four-price menu.

    Returns True when the message belongs to the menu flow and has been
    handled; False lets the legacy /price commands continue unchanged.
    """
    raw = normalize_fa(raw)

    if raw == "/start":
        state[PRICE_MENU_STAGE_KEY] = "main"
        state.pop(PRICE_MENU_FIELD_KEY, None)
        state.pop(PRICE_MENU_DRAFT_KEY, None)
        save_state(state)

        sent = telegram_bot_send_message(
            admin_id,
            "سلام 👋\n\n"
            "برای مدیریت تابلو قیمت، گزینه زیر را بزن:",
            [[PRICE_MENU_CHANGE]],
        )
        if sent:
            log.info("PRICE MENU START SENT | chat_id=%s", admin_id)
        else:
            log.error("PRICE MENU START SEND FAILED | chat_id=%s", admin_id)
        return True

    if raw == PRICE_MENU_CHANGE:
        draft = _price_menu_draft_from_state(state)
        state[PRICE_MENU_STAGE_KEY] = "edit"
        state[PRICE_MENU_FIELD_KEY] = None
        _price_menu_save_draft(state, draft)

        telegram_bot_send_message(
            admin_id,
            _price_menu_text(draft),
            _price_menu_keyboard(),
        )
        log.info("PRICE MENU OPENED")
        return True

    stage = state.get(PRICE_MENU_STAGE_KEY)

    if not stage:
        return False

    if raw == PRICE_MENU_CANCEL:
        _price_menu_clear(state)
        save_state(state)
        telegram_bot_send_message(
            admin_id,
            "❌ تغییر قیمت لغو شد.",
            [[PRICE_MENU_CHANGE]],
            remove_keyboard=False,
        )
        log.info("PRICE MENU CANCELLED")
        return True

    if stage == "edit":
        field = _price_menu_field_from_text(raw)

        if field:
            state[PRICE_MENU_FIELD_KEY] = field
            state[PRICE_MENU_STAGE_KEY] = "input"
            save_state(state)

            telegram_bot_send_message(
                admin_id,
                _price_menu_price_prompt(field),
                [[PRICE_MENU_CANCEL]],
            )
            return True

        if raw == PRICE_MENU_CONFIRM:
            draft = state.get(PRICE_MENU_DRAFT_KEY) or {}

            if not _price_menu_has_all_values(draft):
                missing = [
                    PRICE_MENU_FIELDS[key]
                    for key in PRICE_MENU_FIELDS
                    if draft.get(key) is None
                ]
                telegram_bot_send_message(
                    admin_id,
                    "❌ هنوز قیمت این موارد مشخص نیست:\n"
                    + "\n".join(missing),
                    _price_menu_keyboard(),
                )
                return True

            state[PRICE_MENU_STAGE_KEY] = "duration"
            state.pop(PRICE_MENU_FIELD_KEY, None)
            save_state(state)

            telegram_bot_send_message(
                admin_id,
                "⏱ مدت اعمال این تابلو را انتخاب کن:\n\n"
                "بعد از انتخاب، تابلو همان لحظه در کانال منتشر می‌شود.",
                _price_menu_duration_keyboard(),
            )
            return True

        return True

    if stage == "input":
        field = state.get(PRICE_MENU_FIELD_KEY)

        if field not in PRICE_MENU_FIELDS:
            state[PRICE_MENU_STAGE_KEY] = "edit"
            save_state(state)
            telegram_bot_send_message(
                admin_id,
                "❌ مرحله تغییر قیمت نامعتبر شد. دوباره «💰 تغییر قیمت» را بزن.",
                [[PRICE_MENU_CHANGE]],
            )
            return True

        if field == "ounce":
            value = decimal_value(raw)
            if value is None or value <= 0:
                telegram_bot_send_message(
                    admin_id,
                    "❌ عدد معتبر نیست.\nمثال: 4625.5",
                    [[PRICE_MENU_CANCEL]],
                )
                return True
        else:
            value = integer_value(raw)
            if value is None or value <= 0:
                telegram_bot_send_message(
                    admin_id,
                    "❌ عدد معتبر نیست.\nمثال: 425000",
                    [[PRICE_MENU_CANCEL]],
                )
                return True

        draft = state.get(PRICE_MENU_DRAFT_KEY) or _price_menu_draft_from_state(state)
        draft[field] = value
        state[PRICE_MENU_STAGE_KEY] = "edit"
        state.pop(PRICE_MENU_FIELD_KEY, None)
        _price_menu_save_draft(state, draft)

        telegram_bot_send_message(
            admin_id,
            f"✅ {PRICE_MENU_FIELDS[field]} روی "
            + (
                _format_ounce(value)
                if field == "ounce"
                else f"{format_price(value)} تومان"
            )
            + " تنظیم شد.\n\n"
            + _price_menu_text(draft, "💰 تغییر قیمت"),
            _price_menu_keyboard(),
        )
        return True

    if stage == "duration":
        minutes = _price_menu_parse_duration(raw)

        if minutes == "invalid":
            telegram_bot_send_message(
                admin_id,
                "❌ یکی از مدت‌های زیر را انتخاب کن:",
                _price_menu_duration_keyboard(),
            )
            return True

        draft = state.get(PRICE_MENU_DRAFT_KEY) or {}
        if not _price_menu_has_all_values(draft):
            state[PRICE_MENU_STAGE_KEY] = "edit"
            save_state(state)
            telegram_bot_send_message(
                admin_id,
                "❌ اطلاعات قیمت کامل نیست. دوباره «💰 تغییر قیمت» را بزن.",
                [[PRICE_MENU_CHANGE]],
            )
            return True

        # Save the requested manual values. The actual board publication is
        # done below by the normal Telethon client so Telegram/Rubika keep
        # the same transaction semantics as the automatic price board.
        _price_menu_apply_draft_to_overrides(
            state,
            draft,
            minutes,
        )
        state[PRICE_MENU_STAGE_KEY] = "publishing"
        save_state(state)

        rate = {
            "ounce": float(draft["ounce"]),
            "tehran": int(draft["tehran"]),
        }
        products = get_saved_products(state)

        if products is None:
            products = {}
        else:
            products = dict(products)

        products["shot_995"] = int(draft["shot_995"])
        products["shot_package"] = int(draft["shot_995"]) * 1000
        products["nader_9999"] = int(draft["nader_9999"])
        products["nader_package"] = int(draft["nader_9999"]) * 1000

        # The 995 gram price is the source of truth for the 995 mithqal.
        # Always recalculate it for the new board snapshot.
        products["mithqal_995"] = (
            calculate_mithqal_995_from_gram_price(
                products["shot_995"]
            )
        )
        log.info(
            "MITHQAL 995 AUTO-CALCULATED | gram=%s | mithqal=%s",
            products["shot_995"],
            products["mithqal_995"],
        )

        # The caller performs the actual publish transaction. Store the
        # exact snapshot in state so it survives a GitHub runner restart.
        state["price_menu_pending_publish"] = {
            "rate": rate,
            "products": products,
            "minutes": minutes,
            "created_at": iran_now().isoformat(),
        }
        save_state(state)

        expiry_text = (
            f"{minutes} دقیقه"
            if minutes is not None
            else "نامحدود"
        )

        telegram_bot_send_message(
            admin_id,
            "⏳ تغییرات ثبت شد و آماده ارسال به کانال است.\n"
            f"مدت: {expiry_text}\n\n"
            "در حال انتشار تابلو…",
            remove_keyboard=True,
        )

        log.info(
            "PRICE MENU READY TO PUBLISH | minutes=%s",
            minutes if minutes is not None else "unlimited",
        )
        return True

    return True



# =========================================================
# PROFESSIONAL SILVER SHOT SALES ENGINE
# =========================================================
# This module is intentionally stored in the existing state.json so it does
# not introduce a second database or alter the existing price/news state.
SALES_ORDERS_KEY = "sales_orders"
SALES_CUSTOMERS_KEY = "sales_customers"
SALES_SEQ_KEY = "sales_order_sequence"
SALES_COUPONS_KEY = "sales_coupons"
SALES_REFERRALS_KEY = "sales_referrals"
SALES_INVENTORY_KEY = "sales_inventory_grams"
SALES_SETTINGS_KEY = "sales_settings"

# Receipt forwarding/OCR runs as background asyncio tasks so one slow receipt
# cannot hold up the shared Telegram getUpdates loop.
SALES_RECEIPT_TASKS = set()

SALES_WEIGHTS = [10,20,30,50,100,150,200,250,300,500,750,1000]
SALES_STATUSES = {
    "awaiting_name":"در انتظار نام",
    "awaiting_phone":"در انتظار موبایل",
    "awaiting_address":"در انتظار آدرس",
    "awaiting_payment":"در انتظار پرداخت",
    "awaiting_receipt":"در انتظار رسید",
    "receipt_submitted":"رسید ارسال شده",
    "approved":"پرداخت تأیید شد",
    "preparing":"در حال آماده‌سازی",
    "shipped":"ارسال شد",
    "completed":"تکمیل شد",
    "rejected":"رد شد",
    "expired":"منقضی شد",
    "cancelled":"لغو شد",
}

def sales_orders(state):
    if not isinstance(state.get(SALES_ORDERS_KEY), list): state[SALES_ORDERS_KEY] = []
    return state[SALES_ORDERS_KEY]

def sales_customers(state):
    if not isinstance(state.get(SALES_CUSTOMERS_KEY), dict): state[SALES_CUSTOMERS_KEY] = {}
    return state[SALES_CUSTOMERS_KEY]

def sales_coupons(state):
    if not isinstance(state.get(SALES_COUPONS_KEY), dict): state[SALES_COUPONS_KEY] = {}
    return state[SALES_COUPONS_KEY]

def sales_referrals(state):
    if not isinstance(state.get(SALES_REFERRALS_KEY), dict): state[SALES_REFERRALS_KEY] = {}
    return state[SALES_REFERRALS_KEY]

def sales_customer(state, uid):
    key=str(uid); c=sales_customers(state)
    if not isinstance(c.get(key),dict): c[key]={"telegram_id":int(uid),"name":"","phone":"","address":"","created_at":iran_now().isoformat()}
    c[key]["last_seen_at"]=iran_now().isoformat(); return c[key]

def sales_money(n): return f"{int(n):,} تومان"

def sales_weight(text):
    t=normalize_digits(str(text or "")).replace("٬","").replace(",","")
    m=re.search(r"(?<!\d)(\d{1,4})(?:\s*گرم)?(?!\d)",t)
    if not m: return None
    w=int(m.group(1)); return w if 10<=w<=1000 else None

def sales_percent(w):
    if w < 50: return 7
    if w < 100: return 6
    if w < 150: return 5
    if w < 200: return 4
    if w < 300: return 2
    if w < 500: return 1
    return 0

def sales_unit_price(state):
    try:
        p=get_saved_products(state)
        return int(p["shot_995"]) if p and int(p.get("shot_995",0))>0 else None
    except Exception: return None

def sales_quote(unit,w,coupon_percent=0):
    base=int(unit)*int(w); markup=(base*sales_percent(w)+50)//100
    subtotal=base+markup
    discount=(subtotal*max(0,min(100,int(coupon_percent)))+50)//100
    return {"unit_price":int(unit),"weight":int(w),"percent":sales_percent(w),"base_total":base,"markup_amount":markup,"coupon_percent":int(coupon_percent),"discount_amount":discount,"total":subtotal-discount}

def sales_keyboard():
    return [["🛒 خرید ساچمه","💰 قیمت لحظه‌ای"],["🧮 مقایسه قیمت","📦 سفارش‌های من"],["👤 حساب من","📞 پشتیبانی"]]

def sales_weight_keyboard():
    return [[f"{w} گرم" for w in SALES_WEIGHTS[i:i+4]] for i in range(0,len(SALES_WEIGHTS),4)] + [["✏️ وزن دلخواه","❌ لغو"]]

def sales_send(chat_id,text,keyboard=None,remove=False):
    if not BOT_TOKEN:
        log.warning("SALES SEND FAILED | BOT_TOKEN missing")
        return False

    payload={
        "chat_id":int(chat_id),
        "text":str(text),
        "disable_web_page_preview":True,
    }

    if keyboard is not None:
        payload["reply_markup"]=json.dumps(
            {
                "keyboard":keyboard,
                "resize_keyboard":True,
                "one_time_keyboard":False,
            },
            ensure_ascii=False,
        )
    elif remove:
        payload["reply_markup"]=json.dumps({"remove_keyboard":True})

    try:
        r=requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=payload,
            timeout=15,
        )
        try:
            data=r.json()
        except Exception:
            data={}

        if not r.ok or not data.get("ok", False):
            log.warning(
                "SALES SEND FAILED | chat=%s | http=%s | api=%s | response=%s",
                chat_id,
                r.status_code,
                data.get("ok"),
                data.get("description") or r.text[:300],
            )
            return False

        return True
    except Exception as e:
        log.warning("SALES SEND FAILED | chat=%s | %s",chat_id,e)
        return False

def sales_send_photo(chat_id,photo_id,caption):
    try:
        r=requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={
                "chat_id":int(chat_id),
                "photo":photo_id,
                "caption":caption,
            },
            timeout=10,
        )
        try:
            data=r.json()
        except Exception:
            data={}
        if not r.ok or not data.get("ok", False):
            log.warning(
                "SALES SEND PHOTO FAILED | chat=%s | http=%s | api=%s | response=%s",
                chat_id,
                r.status_code,
                data.get("ok"),
                data.get("description") or r.text[:300],
            )
            return False
        return True
    except Exception as e:
        log.warning("SALES SEND PHOTO FAILED | chat=%s | %s",chat_id,e)
        return False

def sales_send_document(chat_id,document_id,caption):
    """Forward a receipt document to the sales admin without blocking too long."""
    if not BOT_TOKEN:
        log.warning("SALES SEND DOCUMENT FAILED | BOT_TOKEN missing")
        return False
    try:
        r=requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
            data={
                "chat_id":int(chat_id),
                "document":document_id,
                "caption":caption,
            },
            timeout=10,
        )
        try:
            data=r.json()
        except Exception:
            data={}
        if not r.ok or not data.get("ok", False):
            log.warning(
                "SALES SEND DOCUMENT FAILED | chat=%s | http=%s | api=%s | response=%s",
                chat_id,
                r.status_code,
                data.get("ok"),
                data.get("description") or r.text[:300],
            )
            return False
        return True
    except Exception as e:
        log.warning("SALES SEND DOCUMENT FAILED | chat=%s | %s",chat_id,e)
        return False

def sales_order_summary(o):
    return (f"🧾 سفارش {o['order_id']}\n\n⚪ ساچمه نقره ۹۹۵\n⚖️ وزن: {o['weight']:,} گرم\n"
            f"💵 قیمت پایه هر گرم: {sales_money(o['unit_price'])}\n📊 درصد: {o['percent']}٪\n"
            f"💰 قیمت پایه: {sales_money(o['base_total'])}\n➕ درصد: {sales_money(o['markup_amount'])}\n"
            f"🎟 تخفیف: {sales_money(o.get('discount_amount',0))}\n💳 مبلغ نهایی: {sales_money(o['total'])}\n"
            f"📌 وضعیت: {SALES_STATUSES.get(o.get('status'),o.get('status'))}\n"
            f"🔒 اعتبار قیمت تا: {o.get('price_lock_expires_at','-')}")

def sales_active(state,uid):
    for o in reversed(sales_orders(state)):
        if str(o.get("telegram_id"))==str(uid) and o.get("status") in {"awaiting_name","awaiting_phone","awaiting_address","awaiting_payment","awaiting_receipt","receipt_submitted"}: return o
    return None

def sales_daily_used(state,identity,include_pending=True):
    """Return grams already committed by this customer today.

    Approved/fulfilled orders always count. Pending orders also reserve their
    weight so the daily 1,000g limit cannot be bypassed with multiple open
    orders. Cancelled, rejected and expired orders do not count.
    """
    total=0
    day=today_key()
    committed={"approved","preparing","shipped","completed"}
    pending={"awaiting_name","awaiting_phone","awaiting_address",
             "awaiting_payment","awaiting_receipt","receipt_submitted"}
    for o in sales_orders(state):
        if str(o.get("customer_key")) != str(identity):
            continue
        status=o.get("status")
        if status in committed:
            if o.get("approved_day")==day:
                total += int(o.get("weight",0))
        elif include_pending and status in pending:
            try:
                created=datetime.fromisoformat(o.get("created_at",""))
                if created.astimezone(ZoneInfo("Asia/Tehran")).date().isoformat()==day:
                    total += int(o.get("weight",0))
            except Exception:
                # Keep legacy records safe: if no valid timestamp exists,
                # do not reserve them against today's limit.
                pass
    return total

def sales_daily_approved(state,identity):
    # Backward-compatible helper used by the account/reporting UI.
    total=0; day=today_key()
    for o in sales_orders(state):
        if o.get("approved_day")!=day: continue
        if str(o.get("customer_key"))!=str(identity): continue
        if o.get("status") in {"approved","preparing","shipped","completed"}:
            total+=int(o.get("weight",0))
    return total

def sales_inventory(state):
    v=state.get(SALES_INVENTORY_KEY,None)
    return None if v in (None,"",0) else max(0,int(v))

def sales_order_new(state,uid,w):
    c=sales_customer(state,uid)
    identity=c.get("phone") or str(uid)
    used=sales_daily_used(state,identity,include_pending=True)
    remaining=max(0,SALES_DAILY_LIMIT_GRAMS-used)
    if w>remaining:
        return None,f"⚠️ سقف خرید روزانه شما {SALES_DAILY_LIMIT_GRAMS:,} گرم است. امروز {used:,} گرم در سفارش‌های ثبت‌شده/تأییدشده شما محاسبه شده و {remaining:,} گرم باقی مانده."
    inv=sales_inventory(state)
    if inv is not None and w>inv: return None,f"⚠️ موجودی قابل فروش فعلی {inv:,} گرم است."
    unit=sales_unit_price(state)
    if unit is None: return None,"⚠️ قیمت فعلی ساچمه ۹۹۵ در دسترس نیست."
    seq=int(state.get(SALES_SEQ_KEY,0))+1; state[SALES_SEQ_KEY]=seq; now=iran_now()
    q=sales_quote(unit,w)
    o={"order_id":f"YS-{now.strftime('%y%m%d')}-{seq:04d}","telegram_id":int(uid),"customer_key":identity,**q,"status":"awaiting_name","created_at":now.isoformat(),"price_lock_expires_at":(now+timedelta(minutes=SALES_PRICE_LOCK_MINUTES)).isoformat(),"payment_method":"","receipt_file_id":"","shipping_address":"","tracking_code":"","referral_code":"","coupon_code":""}
    sales_orders(state).append(o); return o,None

def sales_compare(state):
    unit=sales_unit_price(state)
    if unit is None:return "⚠️ قیمت فعلی در دسترس نیست."
    lines=["🧮 مقایسه قیمت ساچمه ۹۹۵",f"قیمت پایه: {sales_money(unit)} / گرم",""]
    for w in [50,100,150,200,300,500,1000]:
        q=sales_quote(unit,w); lines.append(f"{w:,} گرم | {q['percent']}٪ | {sales_money(q['total'])}")
    lines.append("\n💡 با افزایش وزن، درصد محاسبه کاهش پیدا می‌کند.")
    return "\n".join(lines)

def sales_payment_text(o):
    lines=[sales_order_summary(o),"","💳 روش پرداخت را انتخاب کنید:"]
    return "\n".join(lines)

def sales_payment_keyboard():
    rows=[]
    if PAYMENT_CARD_NUMBER: rows.append(["💳 پرداخت کارت"])
    if PAYMENT_IBAN: rows.append(["🏦 پرداخت شبا"])
    if PAYMENT_URL: rows.append(["🌐 پرداخت آنلاین"])
    rows.append(["📸 ارسال رسید","❌ لغو"]); return rows

def sales_notify_admin(state,o,photo_id=None,extra=""):
    c=sales_customer(state,o.get("telegram_id")); text=f"🔔 سفارش/رسید جدید\n\n{sales_order_summary(o)}\n👤 {c.get('name') or '-'}\n📱 {c.get('phone') or '-'}\n📍 {c.get('address') or o.get('shipping_address') or '-'}"
    if extra:text+=f"\n\n{extra}"
    if photo_id: sales_send_photo(ADMIN_TELEGRAM_ID,photo_id,text)
    else: sales_send(ADMIN_TELEGRAM_ID,text,[["🛠 مدیریت فروش"]])

def sales_download_file(file_id):
    """Download a Telegram receipt image with bounded network timeouts."""
    try:
        r=requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id":file_id},
            timeout=8,
        )
        r.raise_for_status()
        data=r.json()
        path=(data.get("result") or {}).get("file_path") or ""
        if not path:
            raise RuntimeError("Telegram getFile returned no file_path")

        # Keep the extension so Image.open() can correctly identify the format.
        suffix=Path(path).suffix.lower()
        if suffix not in {".jpg",".jpeg",".png",".webp",".bmp",".tif",".tiff"}:
            suffix=".jpg"

        safe_id=re.sub(r"[^A-Za-z0-9_-]", "_", str(file_id))[-80:]
        fp=BASE/f".sales_receipt_ocr_{safe_id}{suffix}"

        b=requests.get(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}",
            timeout=12,
        )
        b.raise_for_status()
        fp.write_bytes(b.content)
        return fp
    except Exception as e:
        log.warning("SALES RECEIPT DOWNLOAD FAILED | %s",e)
        return None

def sales_ocr_amount(file_id):
    """Best-effort OCR. It must never block the sales flow indefinitely."""
    if pytesseract is None:
        log.info("SALES OCR SKIPPED | pytesseract unavailable")
        return None

    fp=sales_download_file(file_id)
    if not fp:
        return None

    try:
        im=Image.open(fp).convert("L")

        # Avoid huge receipt images consuming the whole GitHub Actions run.
        max_side=1800
        scale=min(1.0, max_side/max(im.size))
        if scale < 1.0:
            im=im.resize(
                (max(1,int(im.width*scale)), max(1,int(im.height*scale)))
            )

        im=ImageOps.autocontrast(im)
        im=im.resize((im.width*2,im.height*2))

        try:
            txt=pytesseract.image_to_string(
                im,
                config="--psm 6",
                timeout=8,
            )
        except TypeError:
            # Compatibility with older pytesseract versions.
            txt=pytesseract.image_to_string(im,config="--psm 6")

        vals=[]
        for x in re.findall(r"\d[\d,٬\.]{5,}",normalize_digits(txt)):
            x=re.sub(r"[^0-9]","",x)
            if x:
                vals.append(int(x))
        return max(vals) if vals else None
    except Exception as e:
        log.warning("SALES OCR FAILED | %s",e)
        return None
    finally:
        try:
            fp.unlink(missing_ok=True)
        except Exception:
            pass

async def sales_process_receipt_async(state,message):
    """Finish receipt forwarding/OCR outside the synchronous update handler."""
    receipt_file_id=message.get("_sales_receipt_file_id")
    receipt_kind=message.get("_sales_receipt_kind","photo")
    order_id=message.get("_sales_receipt_order_id")

    if not receipt_file_id or not order_id:
        return

    order=next(
        (o for o in sales_orders(state) if o.get("order_id")==order_id),
        None,
    )
    if not order:
        log.warning(
            "SALES RECEIPT PROCESS SKIPPED | order=%s | order not found",
            order_id,
        )
        return

    c=sales_customer(state,order.get("telegram_id"))
    text=(
        f"🔔 سفارش/رسید جدید\n\n"
        f"{sales_order_summary(order)}\n"
        f"👤 {c.get('name') or '-'}\n"
        f"📱 {c.get('phone') or '-'}\n"
        f"📍 {c.get('address') or order.get('shipping_address') or '-'}"
    )

    # Forward the actual receipt first. This is the important part and does
    # not depend on OCR succeeding.
    sent=False
    try:
        if receipt_kind=="photo":
            sent=await asyncio.to_thread(
                sales_send_photo,
                ADMIN_TELEGRAM_ID,
                receipt_file_id,
                text,
            )
        else:
            sent=await asyncio.to_thread(
                sales_send_document,
                ADMIN_TELEGRAM_ID,
                receipt_file_id,
                text,
            )
    except Exception as e:
        log.exception(
            "SALES RECEIPT ADMIN FORWARD FAILED | order=%s | %s",
            order_id,
            e,
        )

    log.info(
        "SALES RECEIPT FORWARDED | order=%s | kind=%s | sent=%s",
        order_id,
        receipt_kind,
        sent,
    )

    # OCR is optional. Run it after the receipt has already been forwarded,
    # and outside the async event loop so a slow OCR process cannot freeze the
    # customer's next message.
    ocr=None
    if receipt_kind=="photo":
        try:
            ocr=await asyncio.to_thread(
                sales_ocr_amount,
                receipt_file_id,
            )
        except Exception as e:
            log.warning(
                "SALES RECEIPT OCR ASYNC FAILED | order=%s | %s",
                order_id,
                e,
            )

    extra=(
        f"🤖 مبلغ OCR: {sales_money(ocr)}"
        if ocr
        else "🤖 OCR مبلغ را تشخیص نداد یا رسید قابل OCR نبود."
    )

    try:
        await asyncio.to_thread(
            sales_send,
            ADMIN_TELEGRAM_ID,
            f"🧾 نتیجه بررسی خودکار رسید {order_id}\n\n{extra}",
            [["🛠 مدیریت فروش"]],
        )
    except Exception as e:
        log.warning(
            "SALES RECEIPT OCR RESULT SEND FAILED | order=%s | %s",
            order_id,
            e,
        )


def sales_admin_help():
    return (
        "🛠 پنل مدیریت فروش\n\n"
        "/sales_orders — سفارش‌های اخیر\n"
        "/sales_stats — گزارش فروش\n"
        "/sales_inventory 3200 — موجودی گرم\n"
        "/sales_rates — درصدها\n"
        "/sales_price — قیمت فعلی\n"
        "/sales_coupon CODE 5 — ساخت کد تخفیف\n"
        "/sales_coupon_off CODE — حذف کد\n\n"
        "مدیریت سفارش:\n"
        "/sales_approve ORDER — تأیید پرداخت\n"
        "/sales_reject ORDER — رد پرداخت\n"
        "/sales_prepare ORDER — آماده‌سازی\n"
        "/sales_ship ORDER TRACKING — ارسال\n"
        "/sales_complete ORDER — تکمیل\n"
        "/sales_cancel ORDER — لغو\n\n"
        "اگر دستورهای بالا را بدون شماره سفارش بفرستید، "
        "سفارش‌های قابل انجام همان مرحله نمایش داده می‌شوند."
    )


def _sales_admin_action_orders(state, cmd):
    """Return orders relevant to an admin action."""
    orders = sales_orders(state)
    status_map = {
        "/sales_approve": {"receipt_submitted", "awaiting_receipt"},
        "/sales_reject": {"receipt_submitted", "awaiting_receipt"},
        "/sales_prepare": {"approved"},
        "/sales_ship": {"preparing"},
        "/sales_complete": {"shipped"},
        "/sales_cancel": {
            "pending_payment", "awaiting_receipt", "receipt_submitted",
            "approved", "preparing", "shipped"
        },
    }
    allowed = status_map.get(cmd, set())
    return [o for o in orders if o.get("status") in allowed]


def _sales_admin_orders_text(orders, title):
    if not orders:
        return f"📭 {title}\n\nموردی برای انجام وجود ندارد."
    chunks = [f"📋 {title}\n"]
    for o in reversed(orders[-10:]):
        chunks.append(
            f"🆔 {o.get('order_id','-')}\n"
            f"⚖️ وزن: {int(o.get('weight',0)):,} گرم\n"
            f"💰 مبلغ: {sales_money(o.get('total',0))}\n"
            f"📌 وضعیت: {o.get('status','-')}\n"
            f"➡️ دستور: /{'' if False else ''}"
        )
    return "\n\n".join(chunks)


def sales_admin_handle(state,raw):
    parts=raw.split()
    cmd=parts[0].lower().split("@",1)[0] if parts else ""

    if cmd=="/sales_help" or raw=="🛠 مدیریت فروش":
        return sales_admin_help()

    if cmd=="/sales_price":
        return f"💰 قیمت ساچمه ۹۹۵: {sales_money(sales_unit_price(state) or 0)}"

    if cmd=="/sales_rates":
        return (
            "📊 درصدها\n"
            "۱۰ تا کمتر از ۵۰: ۷٪\n"
            "۵۰ تا کمتر از ۱۰۰: ۶٪\n"
            "۱۰۰ تا کمتر از ۱۵۰: ۵٪\n"
            "۱۵۰ تا کمتر از ۲۰۰: ۴٪\n"
            "۲۰۰ تا کمتر از ۳۰۰: ۲٪\n"
            "۳۰۰ تا کمتر از ۵۰۰: ۱٪\n"
            "۵۰۰ تا ۱۰۰۰: ۰٪"
        )

    if cmd=="/sales_inventory":
        if len(parts)<=1:
            inv=sales_inventory(state)
            return f"📦 موجودی فعلی: {int(inv or 0):,} گرم\n\nبرای تغییر: /sales_inventory 3200"
        try:
            value=int(re.sub(r"\D","",normalize_digits(parts[1])))
            state[SALES_INVENTORY_KEY]=value
            save_state(state)
            return f"✅ موجودی روی {value:,} گرم تنظیم شد."
        except Exception:
            return "❌ مقدار موجودی نامعتبر است."

    if cmd=="/sales_coupon":
        if len(parts)<3:
            return "❌ فرمت صحیح:\n/sales_coupon CODE 5"
        try:
            code=parts[1].upper()
            pct=int(re.sub(r"\D","",normalize_digits(parts[2])))
            sales_coupons(state)[code]={
                "percent":min(100,pct),
                "created_at":iran_now().isoformat()
            }
            save_state(state)
            return f"✅ کد {code} با تخفیف {min(100,pct)}٪ ساخته شد."
        except Exception:
            return "❌ درصد تخفیف نامعتبر است."

    if cmd=="/sales_coupon_off":
        if len(parts)<=1:
            return "❌ کد تخفیف را وارد کنید.\nمثال: /sales_coupon_off CODE"
        code=parts[1].upper()
        existed=code in sales_coupons(state)
        sales_coupons(state).pop(code,None)
        save_state(state)
        return "✅ کد حذف شد." if existed else "ℹ️ این کد وجود نداشت."

    if cmd=="/sales_orders":
        os=sales_orders(state)[-10:]
        return "\n\n".join(sales_order_summary(o) for o in reversed(os)) if os else "📦 سفارشی ثبت نشده."

    if cmd=="/sales_stats":
        day=today_key()
        os=[
            o for o in sales_orders(state)
            if o.get("approved_day")==day
            and o.get("status") in {"approved","preparing","shipped","completed"}
        ]
        grams=sum(int(o.get("weight",0)) for o in os)
        amount=sum(int(o.get("total",0)) for o in os)
        return (
            f"📊 گزارش امروز\n\n"
            f"سفارش تأییدشده: {len(os)}\n"
            f"وزن: {grams:,} گرم\n"
            f"فروش: {sales_money(amount)}\n"
            f"میانگین سفارش: {grams//len(os) if os else 0:,} گرم"
        )

    order_cmds={
        "/sales_approve","/sales_reject","/sales_prepare",
        "/sales_ship","/sales_complete","/sales_cancel"
    }

    if cmd in order_cmds:
        # FIX: commands sent without ORDER must no longer be silently ignored.
        if len(parts)<=1:
            action_titles={
                "/sales_approve":"رسیدهای منتظر تأیید پرداخت",
                "/sales_reject":"رسیدهای قابل رد",
                "/sales_prepare":"سفارش‌های آماده‌سازی",
                "/sales_ship":"سفارش‌های آماده ارسال",
                "/sales_complete":"سفارش‌های در انتظار تکمیل",
                "/sales_cancel":"سفارش‌های قابل لغو",
            }
            orders=_sales_admin_action_orders(state,cmd)
            if not orders:
                return f"📭 {action_titles[cmd]}\n\nموردی برای انجام وجود ندارد."
            out=[f"📋 {action_titles[cmd]}\n"]
            for o in reversed(orders[-10:]):
                out.append(
                    f"🆔 {o.get('order_id','-')}\n"
                    f"⚖️ {int(o.get('weight',0)):,} گرم | "
                    f"💰 {sales_money(o.get('total',0))}\n"
                    f"📌 وضعیت: {o.get('status','-')}"
                )
            extra=""
            if cmd=="/sales_ship":
                extra="\n\nبرای ارسال:\n/sales_ship ORDER TRACKING"
            else:
                extra=f"\n\nبرای انجام:\n{cmd} ORDER"
            return "\n\n".join(out)+extra

        oid=parts[1].upper()
        o=next((x for x in sales_orders(state) if x.get("order_id")==oid),None)
        if not o:
            return "❌ سفارش پیدا نشد."

        if cmd=="/sales_approve":
            if o.get("status") not in {"receipt_submitted","awaiting_receipt"}:
                return "❌ این سفارش آماده تأیید پرداخت نیست."
            inv=sales_inventory(state)
            if inv is not None and int(o["weight"])>inv:
                return "❌ موجودی کافی نیست."
            o["status"]="approved"
            o["approved_day"]=today_key()
            if inv is not None:
                state[SALES_INVENTORY_KEY]=inv-int(o["weight"])
            save_state(state)
            sales_send(
                o["telegram_id"],
                "✅ پرداخت شما تأیید شد.\n\n"+sales_order_summary(o),
                [["📦 سفارش‌های من","👤 حساب من"]]
            )
            return "✅ پرداخت تأیید شد."

        if cmd=="/sales_reject":
            if o.get("status") not in {"receipt_submitted","awaiting_receipt"}:
                return "❌ این سفارش در وضعیت قابل رد کردن نیست."
            o["status"]="rejected"
            save_state(state)
            sales_send(
                o["telegram_id"],
                "❌ رسید/پرداخت سفارش شما تأیید نشد. لطفاً با پشتیبانی تماس بگیرید.",
                sales_keyboard()
            )
            return "✅ سفارش رد شد."

        if cmd=="/sales_prepare":
            if o.get("status")!="approved":
                return "❌ این سفارش هنوز پرداخت تأییدشده ندارد."
            o["status"]="preparing"
            save_state(state)
            sales_send(
                o["telegram_id"],
                "📦 سفارش شما در حال آماده‌سازی است.",
                sales_keyboard()
            )
            return "✅ آماده‌سازی ثبت شد."

        if cmd=="/sales_ship":
            if o.get("status")!="preparing":
                return "❌ این سفارش هنوز آماده ارسال نیست."
            if len(parts)<3:
                return "❌ کد رهگیری را هم وارد کنید.\nمثال:\n/sales_ship ORDER TRACKING"
            o["status"]="shipped"
            o["tracking_code"]=" ".join(parts[2:])
            o["carrier"]=SHIPPING_CARRIER
            save_state(state)
            sales_send(
                o["telegram_id"],
                f"🚚 سفارش شما ارسال شد.\nشرکت: {SHIPPING_CARRIER}\nکد رهگیری: {o['tracking_code']}",
                sales_keyboard()
            )
            return "✅ ارسال ثبت شد."

        if cmd=="/sales_complete":
            if o.get("status")!="shipped":
                return "❌ این سفارش هنوز ارسال نشده است."
            o["status"]="completed"
            save_state(state)
            sales_send(
                o["telegram_id"],
                "✅ سفارش شما تکمیل شد. ممنون از اعتماد شما.",
                sales_keyboard()
            )
            return "✅ تکمیل شد."

        if cmd=="/sales_cancel":
            if o.get("status") not in {
                "pending_payment","awaiting_receipt","receipt_submitted",
                "approved","preparing","shipped"
            }:
                return "❌ این سفارش در وضعیت قابل لغو نیست."
            o["status"]="cancelled"
            save_state(state)
            sales_send(
                o["telegram_id"],
                "❌ سفارش لغو شد.",
                sales_keyboard()
            )
            return "✅ لغو شد."

    return None
def sales_customer_handle(state,message):
    chat=message.get("chat") or {}; user=message.get("from") or {}
    if chat.get("type")!="private": return False
    try: uid=int(user.get("id")); cid=int(chat.get("id"))
    except Exception:return False
    if str(uid)==str(ADMIN_TELEGRAM_ID): return False
    c=sales_customer(state,uid)
    text=(message.get("text") or "").strip()
    photos=message.get("photo") or []
    document=message.get("document") or {}
    document_is_image=(
        str(document.get("mime_type") or "").lower().startswith("image/")
        or Path(str(document.get("file_name") or "")).suffix.lower()
        in {".jpg",".jpeg",".png",".webp",".bmp",".tif",".tiff"}
    )
    receipt_document=document if document_is_image or document.get("file_id") else {}
    active=sales_active(state,uid)
    log.info(
        "SALES CUSTOMER MESSAGE | uid=%s | chat=%s | text=%r | stage=%s | active_status=%s",
        uid,
        cid,
        text[:120],
        c.get("stage"),
        active.get("status") if active else None,
    )
    if photos or receipt_document:
        if not active or active.get("status")!="awaiting_receipt":
            sales_send(
                cid,
                "⚠️ سفارش فعالی برای دریافت رسید ندارید.",
                sales_keyboard(),
            )
            return True

        if photos:
            receipt_file_id=photos[-1]["file_id"]
            receipt_kind="photo"
        else:
            receipt_file_id=receipt_document.get("file_id")
            receipt_kind="document"

        if not receipt_file_id:
            sales_send(
                cid,
                "❌ فایل رسید قابل دریافت نیست. لطفاً دوباره ارسال کنید.",
                sales_keyboard(),
            )
            return True

        active["receipt_file_id"]=receipt_file_id
        active["receipt_kind"]=receipt_kind
        active["status"]="receipt_submitted"
        active["receipt_submitted_at"]=iran_now().isoformat()
        save_state(state)

        # Mark the update for the async post-processing stage. Do not run
        # network downloads/OCR here: that used to freeze the whole bot after
        # the customer sent the receipt.
        message["_sales_receipt_file_id"]=receipt_file_id
        message["_sales_receipt_kind"]=receipt_kind
        message["_sales_receipt_order_id"]=active.get("order_id")

        sent=sales_send(
            cid,
            "✅ رسید دریافت شد.\n\n"
            "رسید برای مدیریت ارسال می‌شود و پس از بررسی نتیجه اعلام خواهد شد.",
            sales_keyboard(),
        )
        log.info(
            "SALES RECEIPT ACCEPTED | order=%s | kind=%s | customer_ack=%s",
            active.get("order_id"),
            receipt_kind,
            sent,
        )
        return True
    if text in {"/start","🛒 خرید ساچمه"}: c["stage"]="weight"; save_state(state); sales_send(cid,"⚖️ وزن مورد نظر را انتخاب کنید:",sales_weight_keyboard()); return True
    if text=="💰 قیمت لحظه‌ای":
        p=sales_unit_price(state); sales_send(cid,f"💰 قیمت فعلی ساچمه ۹۹۵:\n\n{sales_money(p or 0)} / گرم\n\n🔒 قیمت سفارش {SALES_PRICE_LOCK_MINUTES} دقیقه قفل می‌شود.",sales_keyboard()); return True
    if text=="🧮 مقایسه قیمت": sales_send(cid,sales_compare(state),sales_keyboard()); return True
    if text=="📦 سفارش‌های من":
        os=[o for o in sales_orders(state) if str(o.get("telegram_id"))==str(uid)]; sales_send(cid,"\n\n".join(sales_order_summary(o) for o in os[-10:]) if os else "📦 سفارشی ندارید.",sales_keyboard()); return True
    if text=="👤 حساب من":
        used=sales_daily_approved(state,c.get("phone") or str(uid)); sales_send(cid,f"👤 حساب من\n\nنام: {c.get('name') or 'ثبت نشده'}\nموبایل: {c.get('phone') or 'ثبت نشده'}\nخرید تأییدشده امروز: {used:,} گرم\nباقی‌مانده: {max(0,SALES_DAILY_LIMIT_GRAMS-used):,} گرم\n\n📦 سفارش‌ها از همین منو قابل پیگیری هستند.",sales_keyboard()); return True
    if text=="📞 پشتیبانی": sales_send(cid,f"📞 پشتیبانی\n\n{PHONE}",sales_keyboard()); return True
    if text=="❌ لغو":
        if active: active["status"]="cancelled"; save_state(state)
        c["stage"]="main"; sales_send(cid,"❌ سفارش لغو شد.",sales_keyboard()); return True
    if active:
        if active["status"]=="awaiting_name":
            if len(text)<3:sales_send(cid,"❌ نام و نام خانوادگی را کامل وارد کنید."); return True
            c["name"]=text
            active["status"]="awaiting_phone"
            save_state(state)
            sent=sales_send(cid,"📱 شماره موبایل را وارد کنید:",[ ["❌ لغو"] ])
            log.info("SALES NAME ACCEPTED | uid=%s | send_phone_prompt=%s",uid,sent)
            return True
        if active["status"]=="awaiting_phone":
            phone=re.sub(r"\D","",normalize_digits(text));
            if len(phone)<10:sales_send(cid,"❌ شماره موبایل معتبر وارد کنید."); return True
            # One phone identity cannot be used by a second Telegram account.
            for k,v in sales_customers(state).items():
                if k!=str(uid) and re.sub(r"\D","",v.get("phone", ""))==phone:
                    sales_send(cid,"❌ این شماره موبایل قبلاً برای حساب دیگری ثبت شده است."); return True
            # Re-check the daily limit after the customer identity becomes
            # the verified mobile number. This prevents a customer from
            # creating an order under Telegram ID first and then bypassing
            # the 1,000g daily limit by entering a phone number with prior
            # orders.
            used_by_phone=sales_daily_used(state,phone,include_pending=True)
            old_identity=str(active.get("customer_key") or "")
            # Do not count the current order twice when it was initially
            # created under the Telegram ID and is now being migrated to
            # the phone identity.
            current_weight=int(active.get("weight",0) or 0)
            adjusted=used_by_phone if old_identity != phone else max(0,used_by_phone-current_weight)
            if adjusted + current_weight > SALES_DAILY_LIMIT_GRAMS:
                remaining=max(0,SALES_DAILY_LIMIT_GRAMS-adjusted)
                sales_send(cid,f"⚠️ با این شماره موبایل، سقف خرید روزانه {SALES_DAILY_LIMIT_GRAMS:,} گرم است و فقط {remaining:,} گرم باقی مانده است. وزن این سفارش {current_weight:,} گرم است.",[ ["❌ لغو"] ])
                return True
            c["phone"]=phone
            active["customer_key"]=phone
            active["status"]="awaiting_address"
            save_state(state)
            sent=sales_send(cid,"📍 آدرس کامل تحویل را وارد کنید:",[ ["❌ لغو"] ])
            log.info("SALES PHONE ACCEPTED | uid=%s | send_address_prompt=%s",uid,sent)
            return True
        if active["status"]=="awaiting_address":
            if len(text)<10:sales_send(cid,"❌ آدرس کامل‌تری وارد کنید."); return True
            c["address"]=text; active["shipping_address"]=text; active["status"]="awaiting_payment"; save_state(state); sales_send(cid,sales_payment_text(active),sales_payment_keyboard());
            if PAYMENT_URL:sales_send(cid,"🌐 پرداخت آنلاین:"); sales_send(cid,PAYMENT_URL)
            return True
        if active["status"]=="awaiting_payment":
            if text=="💳 پرداخت کارت":
                active["payment_method"]="card"; active["status"]="awaiting_receipt"; save_state(state); sales_send(cid,f"💳 شماره کارت:\n{PAYMENT_CARD_NUMBER or 'تنظیم نشده'}\nبه نام: {PAYMENT_CARD_NAME or 'تنظیم نشده'}\nمبلغ: {sales_money(active['total'])}\n\n📸 عکس رسید را ارسال کنید.",[ ["📸 ارسال رسید","❌ لغو"] ]); return True
            if text=="🏦 پرداخت شبا":
                active["payment_method"]="iban"; active["status"]="awaiting_receipt"; save_state(state); sales_send(cid,f"🏦 شماره شبا:\n{PAYMENT_IBAN or 'تنظیم نشده'}\nبه نام: {PAYMENT_IBAN_NAME or 'تنظیم نشده'}\nمبلغ: {sales_money(active['total'])}\n\n📸 عکس رسید را ارسال کنید.",[ ["📸 ارسال رسید","❌ لغو"] ]); return True
            if text=="🌐 پرداخت آنلاین":
                if PAYMENT_URL:sales_send(cid,f"🌐 لینک پرداخت:\n{PAYMENT_URL}\n\nمبلغ: {sales_money(active['total'])}"); active["payment_method"]="online"; active["status"]="awaiting_receipt"; save_state(state); return True
            if text=="📸 ارسال رسید": active["status"]="awaiting_receipt"; save_state(state); sales_send(cid,"📸 عکس واضح رسید را ارسال کنید."); return True
        if active["status"]=="awaiting_receipt": sales_send(cid,"📸 لطفاً عکس رسید را ارسال کنید."); return True
    w=sales_weight(text)
    if w is not None and (c.get("stage")=="weight" or "گرم" in text):
        o,err=sales_order_new(state,uid,w)
        if err:sales_send(cid,err,sales_keyboard()); return True
        c["stage"]="order"; save_state(state); sales_send(cid,sales_order_summary(o)+"\n\n👤 نام و نام خانوادگی را وارد کنید:",[ ["❌ لغو"] ]); return True
    if text=="✏️ وزن دلخواه": c["stage"]="weight_custom"; save_state(state); sales_send(cid,"✏️ وزن را بین ۱۰ تا ۱۰۰۰ گرم وارد کنید:",[ ["❌ لغو"] ]); return True
    if c.get("stage")=="weight_custom":
        w=sales_weight(text)
        if w is None:sales_send(cid,"❌ وزن باید بین ۱۰ تا ۱۰۰۰ گرم باشد."); return True
        o,err=sales_order_new(state,uid,w)
        if err:sales_send(cid,err,sales_keyboard()); return True
        c["stage"]="order"; save_state(state); sales_send(cid,sales_order_summary(o)+"\n\n👤 نام و نام خانوادگی را وارد کنید:",[ ["❌ لغو"] ]); return True
    sales_send(cid,"⚖️ وزن مورد نظر را انتخاب کنید:",sales_weight_keyboard()); c["stage"]="weight"; save_state(state); return True

def sales_expire_orders(state):
    now=iran_now(); changed=False
    for o in sales_orders(state):
        if o.get("status") in {"awaiting_name","awaiting_phone","awaiting_address","awaiting_payment","awaiting_receipt"}:
            try:
                if now>=datetime.fromisoformat(o["price_lock_expires_at"]):
                    o["status"]="expired"; o["updated_at"]=now.isoformat(); changed=True; sales_send(o["telegram_id"],f"⏰ سفارش {o['order_id']} منقضی شد و قیمت قفل‌شده دیگر معتبر نیست.",sales_keyboard())
            except Exception: pass
    if changed: save_state(state)

async def process_manual_price_commands(client, state):
    """
    Read manual-price commands through the Telegram Bot API update queue.

    IMPORTANT:
    The previous implementation used Telethon client.get_messages() against
    the admin account. For a bot session Telegram rejects that history request
    (GetHistoryRequest / bot users are restricted). Bot API getUpdates is the
    correct mechanism for receiving messages sent to this bot.
    """

    if not ADMIN_TELEGRAM_ID:
        log.warning(
            "MANUAL PRICE DISABLED | ADMIN_TELEGRAM_ID is missing"
        )
        return

    if not BOT_TOKEN:
        log.warning(
            "MANUAL PRICE DISABLED | BOT_TOKEN is missing"
        )
        return

    try:
        admin_id = int(ADMIN_TELEGRAM_ID)
    except Exception:
        log.error("ADMIN_TELEGRAM_ID باید عدد باشد.")
        return

    if not _prepare_telegram_bot_polling():
        return

    # This is a Bot API update_id offset, NOT a Telegram message_id.
    offset_key = "manual_price_update_offset"

    try:
        offset = int(
            state.get(offset_key, 0) or 0
        )
    except Exception:
        offset = 0

    api_url = (
        f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    )

    params = {
        "limit": 100,
        "timeout": 5,
        "allowed_updates": json.dumps(["message"]),
    }

    if offset > 0:
        params["offset"] = offset

    try:
        response = requests.get(
            api_url,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()

        if not payload.get("ok"):
            description = payload.get("description", "")
            log.warning(
                "MANUAL PRICE UPDATE READ FAILED | %s",
                payload,
            )
            if "conflict" in str(description).lower():
                log.warning(
                    "MANUAL PRICE MENU POLLING CONFLICT | "
                    "another getUpdates consumer is active"
                )
            return

        updates = payload.get("result") or []
        log.info(
            "MANUAL PRICE POLL | offset=%s | updates=%s",
            offset,
            len(updates),
        )

    except Exception as error:
        log.warning(
            "MANUAL PRICE UPDATE READ FAILED: %s",
            error,
        )
        return

    # Establish the checkpoint only once.
    # IMPORTANT: if the first run has no pending updates, do NOT leave
    # offset=0 as the "uninitialized" marker; otherwise the next run would
    # see the newly-sent /price command and discard it as an old message.
    checkpoint_key = "manual_price_checkpoint_initialized"

    if not state.get(checkpoint_key, False):
        # The first interactive-menu deployment used to discard all pending
        # updates here. That made a freshly sent /start appear to do nothing.
        # Initialize the checkpoint but process the current batch normally.
        state[checkpoint_key] = True
        save_state(state)

        log.info(
            "MANUAL PRICE UPDATE CHECKPOINT INITIALIZED | updates=%s | processing current batch",
            len(updates),
        )

    if not updates:
        return

    overrides = cleanup_manual_price_overrides(state)
    changed = False
    newest_offset = offset

    for update in updates:
        try:
            update_id = int(
                update.get("update_id", 0)
            )
        except Exception:
            continue

        newest_offset = max(
            newest_offset,
            update_id + 1,
        )

        log.info(
            "MANUAL PRICE UPDATE RECEIVED | update_id=%s",
            update_id,
        )

        message = update.get("message") or {}
        from_user = message.get("from") or {}
        chat = message.get("chat") or {}

        try:
            sender_id = int(
                from_user.get("id", 0)
            )
        except Exception:
            sender_id = 0

        try:
            chat_id = int(
                chat.get("id", 0)
            )
        except Exception:
            chat_id = 0

        sender_username = (
            str(from_user.get("username") or "").strip().lstrip("@").lower()
        )
        is_admin = (
            sender_id == admin_id
            and chat_id == admin_id
        )
        if (
            not is_admin
            and ADMIN_TELEGRAM_USERNAME
            and sender_username == ADMIN_TELEGRAM_USERNAME
            and chat_id == sender_id
        ):
            # Username fallback is opt-in through ADMIN_TELEGRAM_USERNAME.
            # The numeric ID remains the primary secure setting.
            is_admin = True
            log.warning(
                "ADMIN AUTH VIA USERNAME FALLBACK | username=@%s | update_id=%s",
                sender_username,
                update_id,
            )

        # Customer sales messages use the same getUpdates consumer as the
        # existing manual-price menu. This avoids Telegram getUpdates conflicts.
        if not is_admin:
            try:
                if sales_customer_handle(state, message):
                    # Receipt forwarding/OCR is deliberately moved to a
                    # background task. The customer acknowledgement, state
                    # save, and update offset are completed immediately, so a
                    # slow Telegram file download/OCR process cannot make the
                    # bot appear stuck after payment.
                    if message.get("_sales_receipt_file_id"):
                        try:
                            receipt_task=asyncio.create_task(
                                sales_process_receipt_async(
                                    state,
                                    message.copy(),
                                )
                            )
                            SALES_RECEIPT_TASKS.add(receipt_task)

                            def _receipt_task_done(task):
                                SALES_RECEIPT_TASKS.discard(task)
                                try:
                                    error=task.exception()
                                except asyncio.CancelledError:
                                    return
                                if error:
                                    log.error(
                                        "SALES RECEIPT POST-PROCESS FAILED | %s",
                                        error,
                                        exc_info=(type(error), error, error.__traceback__),
                                    )

                            receipt_task.add_done_callback(
                                _receipt_task_done
                            )
                            log.info(
                                "SALES RECEIPT TASK QUEUED | order=%s",
                                message.get("_sales_receipt_order_id"),
                            )
                        except Exception as error:
                            log.exception(
                                "SALES RECEIPT TASK CREATE FAILED | %s",
                                error,
                            )

                    newest_offset = max(newest_offset, update_id + 1)
                    changed = True
                    continue
            except Exception as error:
                log.exception("SALES CUSTOMER UPDATE FAILED | %s", error)
            continue

        raw = (
            message.get("text")
            or message.get("caption")
            or ""
        ).strip()

        if not raw:
            continue

        log.info(
            "ADMIN COMMAND RECEIVED | update_id=%s | command=%s",
            update_id,
            raw[:80],
        )

        # Professional sales admin commands run before the legacy price menu.
        try:
            sales_admin_reply = sales_admin_handle(state, raw)
            if sales_admin_reply is not None:
                telegram_bot_send_message(admin_id, sales_admin_reply)
                continue
        except Exception as error:
            log.warning("SALES ADMIN COMMAND FAILED | %s", error)

        # Interactive price menu. It must run before the legacy command
        # parser so ordinary keyboard selections such as "💰 تغییر قیمت"
        # are handled as menu actions.
        try:
            menu_handled = await process_price_menu_message(
                client,
                state,
                admin_id,
                raw,
            )
        except Exception as error:
            menu_handled = False
            log.warning(
                "PRICE MENU FAILED | %s | %s",
                raw,
                error,
            )

        # A menu action may have prepared a complete board snapshot. Publish
        # it through the normal Telegram transaction path so the same board
        # image/caption and Rubika handling are preserved.
        pending_menu_publish = state.get("price_menu_pending_publish")

        if (
            menu_handled
            and
            isinstance(pending_menu_publish, dict)
        ):
            try:
                target_for_menu = await client.get_entity(TARGET_CHANNEL)
                await publish_price_transaction(
                    client,
                    target_for_menu,
                    state,
                    pending_menu_publish["rate"],
                    pending_menu_publish["products"],
                    None,
                )
                state.pop("price_menu_pending_publish", None)
                state.pop(PRICE_MENU_STAGE_KEY, None)
                state.pop(PRICE_MENU_FIELD_KEY, None)
                state.pop(PRICE_MENU_DRAFT_KEY, None)
                save_state(state)

                telegram_bot_send_message(
                    admin_id,
                    "✅ تابلو با موفقیت در کانال به‌روزرسانی شد.",
                    [[PRICE_MENU_CHANGE]],
                )

                log.info("PRICE MENU PUBLISHED SUCCESSFULLY")
            except Exception as error:
                log.exception(
                    "PRICE MENU PUBLISH FAILED: %s",
                    error,
                )
                telegram_bot_send_message(
                    admin_id,
                    "❌ ارسال تابلو به کانال انجام نشد.\n"
                    "تغییرات ثبت شده و در اجرای بعدی دوباره تلاش می‌شود.",
                    [[PRICE_MENU_CHANGE]],
                )

            # Do not let a menu action fall through into /price parsing.
            continue

        if menu_handled:
            continue

        parts = raw.split()
        if not parts:
            continue

        command = (
            parts[0]
            .lower()
            .split("@", 1)[0]
        )

        # Short manual-price syntax for the admin:
        #   995 425000 30
        # means: set 995 price to 425,000 تومان for 30 minutes.
        # A 2-part version is also accepted:
        #   995 425000
        # which stays manual until /auto is used.
        short_price_command = False
        short_product_key = None

        if not command.startswith("/") and len(parts) in (2, 3):
            short_product_key = MANUAL_PRICE_ALIASES.get(
                parts[0].lower()
            )
            if short_product_key:
                short_price_command = True

        try:
            if command in ("/price", "/manual_price") or short_price_command:

                if short_price_command:
                    price_parts = parts
                else:
                    if len(parts) not in (3, 4):
                        await client.send_message(
                            admin_id,
                            manual_price_help_text()
                        )
                        continue
                    price_parts = parts[1:]

                product_key = (
                    short_product_key
                    if short_price_command
                    else MANUAL_PRICE_ALIASES.get(
                        price_parts[0].lower()
                    )
                )

                if not product_key:
                    await client.send_message(
                        admin_id,
                        "❌ محصول نامعتبر است.\n"
                        "برای راهنما /pricehelp را بفرست.",
                    )
                    continue

                price = int(
                    re.sub(
                        r"[^\d]",
                        "",
                        price_parts[1]
                    )
                )

                if price <= 0:
                    raise ValueError

                minutes = None

                if len(price_parts) == 3:
                    minutes = int(price_parts[2])

                    if minutes <= 0:
                        raise ValueError

                expires_at = None

                if minutes is not None:
                    expires_at = (
                        iran_now()
                        + timedelta(
                            minutes=minutes
                        )
                    ).isoformat()

                overrides[product_key] = {
                    "price": price,
                    "set_at": iran_now().isoformat(),
                    "expires_at": expires_at,
                }

                # When the admin enters the 995 price per gram manually,
                # the 995 mithqal must follow it automatically. Remove any
                # older explicit mithqal override so it cannot stay stale.
                if product_key == "shot_995":
                    overrides.pop("mithqal_995", None)

                changed = True

                expiry_text = (
                    f"برای {minutes} دقیقه"
                    if minutes is not None
                    else "تا زمانی که خودت به حالت خودکار برگردانی"
                )

                label = {
                    "shot_995": "ساچمه ۹۹۵",
                    "nader_9999": "شمش ۹۹۹.۹",
                    "mithqal_995": "مثقال ۹۹۵",
                }[product_key]

                await client.send_message(
                    admin_id,
                    f"✅ قیمت دستی {label} "
                    f"روی {format_price(price)} تومان تنظیم شد.\n"
                    f"⏱ {expiry_text}.",
                )

                log.info(
                    "MANUAL PRICE SET | %s=%s | expires=%s",
                    product_key,
                    price,
                    expires_at or "none",
                )

            elif command in ("/auto", "/automatic"):

                if len(parts) != 2:
                    await client.send_message(
                        admin_id,
                        "فرمت صحیح:\n"
                        "/auto 995\n"
                        "/auto 9999\n"
                        "/auto mithqal\n"
                        "/auto all",
                    )
                    continue

                arg = parts[1].lower()

                if arg == "all":
                    removed = bool(overrides)
                    overrides.clear()

                else:
                    product_key = (
                        MANUAL_PRICE_ALIASES.get(arg)
                    )

                    if not product_key:
                        await client.send_message(
                            admin_id,
                            "❌ محصول نامعتبر است.",
                        )
                        continue

                    removed = (
                        product_key in overrides
                    )

                    overrides.pop(
                        product_key,
                        None
                    )

                if removed:
                    changed = True

                await client.send_message(
                    admin_id,
                    "✅ حالت خودکار فعال شد."
                    if removed
                    else
                    "ℹ️ برای این مورد قیمت دستی فعالی وجود نداشت.",
                )

                log.info(
                    "MANUAL PRICE AUTO | target=%s | removed=%s",
                    arg,
                    removed,
                )

            elif command in (
                "/pricehelp",
                "/manualhelp"
            ):
                await client.send_message(
                    admin_id,
                    manual_price_help_text()
                )

        except Exception as error:
            log.warning(
                "MANUAL PRICE COMMAND FAILED | %s | %s",
                raw,
                error,
            )

            await client.send_message(
                admin_id,
                "❌ فرمت دستور صحیح نیست.\n"
                "برای راهنما /pricehelp را بفرست.",
            )

    state[offset_key] = newest_offset
    state[MANUAL_PRICE_OVERRIDES_KEY] = overrides

    # Keep the legacy message-id key untouched for backward compatibility,
    # but no longer use it to read Bot history.
    if changed or newest_offset != offset:
        save_state(state)

    log.info(
        "MANUAL PRICE UPDATE CHECK COMPLETED | processed=%s",
        len(updates),
    )


# =========================================================
# TGH SILVER LIVE SHOT PRICE
# =========================================================
# The TGH public channel posts its "نرخ خرید فروش ساچمه و شمش" table
# as an image. The caption contains the ounce/dollar context, while the
# actual 995 shot price is inside the attached table image. We therefore
# read the newest table image and OCR the 995 row.
TGH_SHOT_PRICE_KEY = "tgh_shot_995"
TGH_SHOT_MESSAGE_ID_KEY = "tgh_shot_message_id"

def _ocr_numeric_values(text, min_value=100_000, max_value=2_000_000):
    text = normalize_digits(text or "")
    values = []

    # Accept both comma-separated and plain Persian/English digits.
    for token in re.findall(r"\d[\d,٬\.]*", text):
        raw = (
            token
            .replace(",", "")
            .replace("٬", "")
            .replace(".", "")
        )
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if min_value <= value <= max_value:
            values.append(value)

    return values

def _tgh_ocr_995_price(image_path):
    if pytesseract is None:
        log.warning("TGH OCR SKIPPED | pytesseract is not installed")
        return None

    try:
        image = Image.open(image_path)
        image = ImageOps.exif_transpose(image).convert("L")

        # Upscale to make the small table digits easier for Tesseract to read.
        scale = 3
        image = image.resize(
            (image.width * scale, image.height * scale),
            Image.Resampling.LANCZOS
        )
        image = ImageOps.autocontrast(image)

        # Try the Persian model first. A numeric-only fallback is also useful
        # if the host does not have the Persian language pack.
        languages = []
        try:
            available = pytesseract.get_languages(config="")
        except Exception:
            available = []

        if "fas" in available:
            languages.append("fas+eng")
        languages.append("eng")

        candidates = []

        for lang in languages:
            for psm in (6, 11, 12):
                try:
                    data = pytesseract.image_to_data(
                        image,
                        lang=lang,
                        config=f"--psm {psm}",
                        output_type=pytesseract.Output.DICT,
                    )
                except Exception as error:
                    log.debug("TGH OCR PASS FAILED | lang=%s psm=%s | %s", lang, psm, error)
                    continue

                lines = {}
                count = len(data.get("text", []))

                for i in range(count):
                    raw = (data["text"][i] or "").strip()
                    if not raw:
                        continue

                    key = (
                        data.get("block_num", [0] * count)[i],
                        data.get("par_num", [0] * count)[i],
                        data.get("line_num", [0] * count)[i],
                    )
                    lines.setdefault(key, []).append({
                        "text": raw,
                        "left": int(data.get("left", [0] * count)[i] or 0),
                        "top": int(data.get("top", [0] * count)[i] or 0),
                        "width": int(data.get("width", [0] * count)[i] or 0),
                    })

                for tokens in lines.values():
                    line_text = " ".join(t["text"] for t in tokens)
                    normalized_line = normalize_digits(line_text).replace("٫", ".")

                    # Look specifically for the 995 row. OCR may return
                    # 995, 995.0, ۹۹۵ or a slightly separated form.
                    has_995 = bool(
                        re.search(r"(?<!\d)995(?:[.,]0*)?(?!\d)", normalized_line)
                    )
                    if not has_995 and "ساچمه" not in normalized_line:
                        continue

                    values = _ocr_numeric_values(line_text)

                    # Exclude the row label itself and choose the highest
                    # per-gram value on the row. In TGH's table the selling
                    # value is normally above the buying value, so this
                    # avoids accidentally selecting the lower buy quote.
                    if values:
                        candidate = max(values)
                        candidates.append(candidate)

        if candidates:
            # Multiple OCR passes may return the same value. Median is more
            # resistant to a single bad OCR pass than simply taking the last.
            candidates.sort()
            return candidates[len(candidates) // 2]

        # Last-resort OCR over the whole image: useful when Tesseract merged
        # the table row into one paragraph.
        for lang in languages:
            for psm in (6, 11, 12):
                try:
                    raw = pytesseract.image_to_string(
                        image,
                        lang=lang,
                        config=f"--psm {psm}",
                    )
                except Exception:
                    continue

                normalized = normalize_digits(raw)
                positions = [
                    m.start()
                    for m in re.finditer(r"995(?:[.,]0*)?", normalized)
                ]

                for pos in positions:
                    window = normalized[max(0, pos - 100): pos + 180]
                    values = _ocr_numeric_values(window)
                    if values:
                        return max(values)

    except Exception as error:
        log.exception("TGH OCR FAILED | %s", error)

    return None

def find_latest_tgh_shot_995_price():
    """
    Find the newest TGH table post and extract the 995 shot selling price
    from its attached image. Returns (price_per_gram, message_id).
    """
    before = None
    seen = set()

    for page_number in range(1, 8):
        try:
            html = fetch_public_page(
                SOURCE_CHANNEL,
                before
            )
            messages = parse_public_messages_with_media(html)
        except Exception as error:
            log.warning("TGH PUBLIC PAGE FAILED | page=%s | %s", page_number, error)
            break

        if not messages:
            break

        for message in messages:
            text = clean_text(message.get("text", ""))

            if not (
                "ساچمه" in text
                and
                (
                    "نرخ خرید فروش" in text
                    or
                    "جدول" in text
                )
            ):
                continue

            photo_url = message.get("photo_url")
            if not photo_url:
                continue

            try:
                response = requests.get(
                    photo_url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://t.me/",
                    },
                    timeout=30,
                )
                response.raise_for_status()

                suffix = ".jpg"
                content_type = response.headers.get("Content-Type", "")
                if "png" in content_type:
                    suffix = ".png"
                elif "webp" in content_type:
                    suffix = ".webp"

                temp_path = BASE / f".tgh_price_{message['message_id']}{suffix}"
                temp_path.write_bytes(response.content)

                try:
                    price = _tgh_ocr_995_price(temp_path)
                finally:
                    temp_path.unlink(missing_ok=True)

                if price:
                    log.info(
                        "TGH SHOT 995 FOUND | price=%s | message=%s",
                        price,
                        message["message_id"],
                    )
                    return int(price), int(message["message_id"])

                log.warning(
                    "TGH TABLE FOUND BUT 995 OCR FAILED | message=%s",
                    message["message_id"],
                )

            except Exception as error:
                log.warning(
                    "TGH TABLE IMAGE FAILED | message=%s | %s",
                    message["message_id"],
                    error,
                )

        min_id = min(
            int(x["message_id"])
            for x in messages
        )

        if min_id in seen:
            break

        seen.add(min_id)
        before = min_id

    return None, None

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
            "news_count"
        ] = 0

        state[
            "news_last_posted_at"
        ] = None

        state[
            "economic_news_count"
        ] = 0

        state[
            "world_news_count"
        ] = 0

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

        log.info(
            "NEWS DAILY LIMIT REACHED | %s/%s",
            total,
            NEWS_TOTAL_MAX_PER_DAY
        )

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

        # Ordinary news uses the normal 15-minute spacing. Urgent news is
        # evaluated separately at posting time and is allowed through with
        # the shorter emergency cooldown.
        if elapsed < NEWS_MIN_GAP_MINUTES:
            log.info(
                "NEWS WAITING | %.1f/%s MINUTES",
                elapsed,
                NEWS_MIN_GAP_MINUTES
            )
            return False

        return True

    except Exception:

        return True


def update_news_state(
    state,
    article,
    message_id,
    category="economic",
    poll_message_id=None
):

    if category == "world":

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

    history_titles = state.get(
        "news_title_history",
        []
    )

    if not isinstance(
        history_titles,
        list
    ):

        history_titles = []

    title = article.get(
        "title",
        ""
    )

    if title:

        history_titles.append(
            title
        )

    state[
        "news_title_history"
    ] = history_titles[
        -NEWS_HISTORY_LIMIT:
    ]

    # امضای محتوایی خبر برای تشخیص بازنشر همان خبر با تیتر متفاوت.
    # سازگاری با stateهای قدیمی: نسخه‌های قبلی از
    # news_content_history استفاده می‌کردند.
    history_fingerprints = state.get(
        "news_fingerprint_history"
    )

    if not isinstance(history_fingerprints, list):
        history_fingerprints = state.get(
            "news_content_history",
            []
        )

    if not isinstance(
        history_fingerprints,
        list
    ):

        history_fingerprints = []

    signature = news_content_signature(
        article
    )

    if signature:

        history_fingerprints.append(
            signature
        )

    state[
        "news_fingerprint_history"
    ] = history_fingerprints[
        -NEWS_HISTORY_LIMIT:
    ]

    # نگهداری کلید قدیمی برای سازگاری با stateهای قبلی.
    state[
        "news_content_history"
    ] = state[
        "news_fingerprint_history"
    ]

    # آرشیو زمان‌دار خبرها برای تحلیل هفتگی.
    news_archive = state.get(
        "news_archive",
        []
    )

    if not isinstance(
        news_archive,
        list
    ):
        news_archive = []

    news_archive.append({
        "timestamp": iran_now().isoformat(),
        "title": title,
        "url": article.get("url", ""),
        "category": category
    })

    state[
        "news_archive"
    ] = news_archive[
        -NEWS_HISTORY_LIMIT:
    ]

    state[
        "last_news_message_id"
    ] = int(
        message_id
    )

    if poll_message_id:

        state[
            "last_news_poll_message_id"
        ] = int(
            poll_message_id
        )


# =========================================================
# RUBIKA SENDERS / TELEGRAM -> RUBIKA SYNC
# =========================================================

def rubika_clean_text(text):

    text = text or ""

    text = text.replace(
        PHONE,
        ""
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


def rubika_is_configured():

    return bool(
        RUBIKA_TOKEN
        and
        RUBIKA_CHAT_ID
        and
        RubikaRobot is not None
    )


def rubika_robot():

    if not RUBIKA_TOKEN:

        raise RuntimeError(
            "RUBIKA_TOKEN تنظیم نشده است."
        )

    if not RUBIKA_CHAT_ID:

        raise RuntimeError(
            "RUBIKA_CHAT_ID تنظیم نشده است."
        )

    if RubikaRobot is None:

        raise RuntimeError(
            "کتابخانه rubka نصب نشده است."
        )

    return RubikaRobot(
        token=RUBIKA_TOKEN
    )


async def send_rubika_text(
    text
):

    if not rubika_is_configured():

        log.warning(
            "RUBIKA TEXT SKIPPED | NOT CONFIGURED"
        )

        return False

    text = rubika_clean_text(
        text
    )

    if not text:

        return False

    try:

        bot = rubika_robot()

        await bot.send_message(

            chat_id=RUBIKA_CHAT_ID,

            text=text

        )

        log.info(
            "RUBIKA TEXT SENT"
        )

        return True

    except Exception as error:

        log.exception(
            "RUBIKA TEXT FAILED: %s",
            error
        )

        return False


async def send_rubika_media(
    message
):

    if not rubika_is_configured():

        log.warning(
            "RUBIKA MEDIA SKIPPED | NOT CONFIGURED"
        )

        return False

    if getattr(
        message,
        "poll",
        None
    ):

        log.info(
            "RUBIKA | POLL SKIPPED | TELEGRAM=%s",
            message.id
        )

        return False

    if getattr(
        message,
        "sticker",
        None
    ):

        log.info(
            "RUBIKA | STICKER SKIPPED | TELEGRAM=%s",
            message.id
        )

        return False

    caption = rubika_clean_text(

        getattr(
            message,
            "message",
            None
        )
        or
        getattr(
            message,
            "text",
            None
        )
        or
        ""

    )

    if not message.media:

        if caption:

            return await send_rubika_text(
                caption
            )

        return False

    temp_dir = BASE / ".rubika_media"

    temp_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    file_path = None

    try:

        file_path = await message.download_media(

            file=str(

                temp_dir
                /
                f"telegram_{message.id}"

            )

        )

        if not file_path:

            log.warning(
                "RUBIKA MEDIA DOWNLOAD FAILED | TELEGRAM=%s",
                message.id
            )

            return False

        bot = rubika_robot()

        if getattr(
            message,
            "photo",
            None
        ):

            await bot.send_image(

                chat_id=RUBIKA_CHAT_ID,

                path=file_path,

                text=caption

            )

        elif getattr(
            message,
            "video",
            None
        ):

            await bot.send_video(

                chat_id=RUBIKA_CHAT_ID,

                path=file_path,

                text=caption

            )

        elif getattr(
            message,
            "voice",
            None
        ):

            await bot.send_voice(

                chat_id=RUBIKA_CHAT_ID,

                path=file_path,

                text=caption

            )

        elif getattr(
            message,
            "audio",
            None
        ):

            await bot.send_music(

                chat_id=RUBIKA_CHAT_ID,

                path=file_path,

                text=caption

            )

        elif getattr(
            message,
            "gif",
            None
        ):

            await bot.send_gif(

                chat_id=RUBIKA_CHAT_ID,

                path=file_path,

                text=caption

            )

        else:

            await bot.send_document(

                chat_id=RUBIKA_CHAT_ID,

                path=file_path,

                text=caption

            )

        log.info(
            "RUBIKA MEDIA SENT | TELEGRAM=%s",
            message.id
        )

        return True

    except Exception as error:

        log.exception(
            "RUBIKA MEDIA FAILED | TELEGRAM=%s | %s",
            message.id,
            error
        )

        return False

    finally:

        try:

            if file_path:

                Path(
                    file_path
                ).unlink(
                    missing_ok=True
                )

        except Exception:

            pass


async def sync_manual_telegram_messages(
    client,
    target,
    state
):

    if not rubika_is_configured():

        return

    scan_id = state.get(
        RUBIKA_MANUAL_SCAN_STATE_KEY
    )

    auto_ids = state.get(
        RUBIKA_AUTO_MESSAGE_IDS_KEY,
        []
    )

    if not isinstance(
        auto_ids,
        list
    ):

        auto_ids = []

    auto_ids = {

        int(x)

        for x in auto_ids

        if str(x).isdigit()

    }

    if scan_id is None:

        try:

            latest = await client.get_messages(

                target,

                limit=1

            )

            if latest:

                state[
                    RUBIKA_MANUAL_SCAN_STATE_KEY
                ] = int(
                    latest[0].id
                )

                save_state(
                    state
                )

            log.info(
                "RUBIKA MANUAL SYNC INITIALIZED"
            )

        except Exception as error:

            log.exception(
                "RUBIKA MANUAL SYNC INIT FAILED: %s",
                error
            )

        return

    try:

        scan_id = int(
            scan_id
        )

    except Exception:

        scan_id = 0

    try:

        messages = []

        async for message in client.iter_messages(

            target,

            min_id=scan_id,

            reverse=True

        ):

            messages.append(
                message
            )

        if not messages:

            return

        newest_id = max(

            int(
                message.id
            )

            for message in messages

        )

        for message in messages:

            message_id = int(
                message.id
            )

            if message_id in auto_ids:

                continue

            if getattr(
                message,
                "poll",
                None
            ):

                log.info(
                    "RUBIKA MANUAL SYNC | POLL SKIPPED | %s",
                    message_id
                )

                continue

            if getattr(
                message,
                "sticker",
                None
            ):

                log.info(
                    "RUBIKA MANUAL SYNC | STICKER SKIPPED | %s",
                    message_id
                )

                continue

            try:

                await send_rubika_media(
                    message
                )

            except Exception as error:

                log.exception(
                    "RUBIKA MANUAL MESSAGE FAILED | %s | %s",
                    message_id,
                    error
                )

        state[
            RUBIKA_MANUAL_SCAN_STATE_KEY
        ] = newest_id

        save_state(
            state
        )

        log.info(

            "RUBIKA MANUAL SYNC COMPLETED | "
            "CHECKED=%s | NEWEST=%s",

            len(messages),

            newest_id

        )

    except Exception as error:

        log.exception(
            "RUBIKA MANUAL SYNC FAILED: %s",
            error
        )


def remember_rubika_auto_message(
    state,
    message_id
):

    if not message_id:

        return

    history = state.get(

        RUBIKA_AUTO_MESSAGE_IDS_KEY,

        []

    )

    if not isinstance(
        history,
        list
    ):

        history = []

    try:

        message_id = int(
            message_id
        )

    except Exception:

        return

    if message_id not in history:

        history.append(
            message_id
        )

    try:

        if (
            message_id
            not in
            RUBIKA_CURRENT_AUTO_MESSAGE_IDS
        ):

            RUBIKA_CURRENT_AUTO_MESSAGE_IDS.append(
                message_id
            )

    except Exception:

        pass

    state[
        RUBIKA_AUTO_MESSAGE_IDS_KEY
    ] = history[
        -RUBIKA_AUTO_MESSAGE_IDS_LIMIT:
    ]


async def send_rubika_rate_post(
    rate,
    products
):

    text = (

        "🥈 قیمت و معاملات نقره یزدان‌دوست\n"
        "━━━━━━━━━━━━━━\n\n"

        f"📅 تاریخ: {iran_date_string()}\n"
        f"🕐 آخرین بروزرسانی: {iran_time_string()}\n\n"

        "🌍 انس نقره\n"
        f"{rate['ounce']:.2f} دلار\n\n"

        "💵 دلار تهران\n"
        f"{format_price(rate['tehran'])} تومان\n\n"

        "🥈 ساچمه نقره ۹۹۵\n"
        f"{format_price(products['shot_995'])} تومان\n\n"

        "🧱 شمش ندیر ۹۹۹.۹\n"
        f"{format_price(products['nader_9999'])} تومان\n\n"

        "⚖️ مثقال نقره ۹۹۵\n"
        f"{format_price(products['mithqal_995'])} تومان\n\n"

        "━━━━━━━━━━━━━━\n"
        "📲 کانال قیمت نقره یزدان‌دوست\n"
        f"{CHANNEL_LINK}"

    )

    return await send_rubika_text(
        text
    )


# =========================================================
# TELEGRAM SENDERS
# =========================================================

async def send_market_poll(
    client,
    target
):

    # نظرسنجی درصدی: مخاطب بازه تغییر قیمت نقره در فردا را انتخاب می‌کند.
    poll = build_telegram_poll(
        "📊 فکر می‌کنید قیمت نقره فردا چند درصد تغییر کند؟",
        [
            ("🚀 بیشتر از ۳٪ افزایش", b"\x01"),
            ("📈 ۱٪ تا ۳٪ افزایش", b"\x02"),
            ("🟢 کمتر از ۱٪ افزایش", b"\x03"),
            ("🟡 کمتر از ۱٪ کاهش", b"\x04"),
            ("📉 ۱٪ تا ۳٪ کاهش", b"\x05"),
            ("🔻 بیشتر از ۳٪ کاهش", b"\x06")
        ]
    )

    media = InputMediaPoll(
        poll=poll
    )

    sent = await client(
        SendMediaRequest(
            peer=target,
            media=media,
            message=(
                "🔮 پیش‌بینی شما برای تغییر قیمت نقره در معاملات فردا چیست؟\n\n"
                "بازه موردنظر خود را انتخاب کنید 👇"
            ),
            random_id=poll_random_id()
        )
    )

    log.info(
        "PERCENTAGE MARKET POLL SENT | %s | OPTIONS=6_PERCENT_RANGES | ANONYMOUS=YES | SINGLE_CHOICE=YES | LIVE_RESULTS=TELEGRAM",
        sent.id
    )

    return int(sent.id)


# =========================================================
# POLL ACCURACY
# =========================================================

POLL_OPTION_LABELS = {

    b"\x01": "🚀 بیشتر از ۳٪ افزایش",
    b"\x02": "📈 ۱٪ تا ۳٪ افزایش",
    b"\x03": "🟢 کمتر از ۱٪ افزایش",
    b"\x04": "🟡 کمتر از ۱٪ کاهش",
    b"\x05": "📉 ۱٪ تا ۳٪ کاهش",
    b"\x06": "🔻 بیشتر از ۳٪ کاهش",

}


async def fetch_poll_vote_counts(
    client,
    target,
    message_id
):

    message = await client.get_messages(
        target,
        ids=message_id
    )

    if (

        message is None
        or
        message.media is None
        or
        not hasattr(
            message.media,
            "results"
        )
        or
        message.media.results is None

    ):

        return None

    results = message.media.results

    total_voters = (
        results.total_voters
        or
        0
    )

    votes = {

        option: 0
        for option in POLL_OPTION_LABELS

    }

    for answer in (
        results.results
        or
        []
    ):

        if answer.option in votes:

            votes[answer.option] = (
                answer.voters
                or
                0
            )

    return {

        "total_voters": total_voters,
        "votes": votes,

    }


def actual_market_direction(
    rate_start,
    rate_end
):

    if not rate_start:

        return None, None

    change_percent = percent_change(
        rate_end,
        rate_start
    )

    if change_percent is None:

        return None, None

    if change_percent > 3:

        return b"\x01", change_percent

    if change_percent >= 1:

        return b"\x02", change_percent

    if change_percent >= 0:

        return b"\x03", change_percent

    if change_percent > -1:

        return b"\x04", change_percent

    if change_percent >= -3:

        return b"\x05", change_percent

    return b"\x06", change_percent



def make_poll_accuracy_message(
    vote_data,
    rate_start,
    rate_end
):

    total_voters = vote_data["total_voters"]

    if total_voters <= 0:

        return None

    votes = vote_data["votes"]

    actual_option, change_percent = (
        actual_market_direction(
            rate_start,
            rate_end
        )
    )

    if actual_option is None:

        return None

    majority_option = max(
        votes,
        key=lambda option: votes[option]
    )

    matched = (
        majority_option
        ==
        actual_option
    )

    lines = [

        "📊 نتیجه پیش‌بینی دیروز",
        "━━━━━━━━━━━━━━",
        "",

    ]

    for option, label in POLL_OPTION_LABELS.items():

        count = votes.get(
            option,
            0
        )

        percent = (
            count
            /
            total_voters
            *
            100
        )

        lines.append(
            f"{label}: "
            f"{percent:.0f}٪ "
            f"({count} رأی)"
        )

    lines.append("")

    lines.append(
        f"نتیجه واقعی بازار: "
        f"{POLL_OPTION_LABELS[actual_option]} "
        f"({change_percent:+.2f}٪)"
    )

    lines.append("")

    if matched:

        lines.append(
            "✅ اکثریت درست پیش‌بینی کرده بودن!"
        )

    else:

        lines.append(
            "❌ این بار برخلاف پیش‌بینی اکثریت شد."
        )

    lines.append(
        channel_footer()
    )

    text = "\n".join(lines)

    return text if len(text) < 4000 else None


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

    try:

        message_id = int(
            sent.id
        )

        if (
            message_id
            not in
            RUBIKA_CURRENT_AUTO_MESSAGE_IDS
        ):

            RUBIKA_CURRENT_AUTO_MESSAGE_IDS.append(
                message_id
            )

    except Exception:

        pass

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

    try:

        message_id = int(
            sent.id
        )

        if (
            message_id
            not in
            RUBIKA_CURRENT_AUTO_MESSAGE_IDS
        ):

            RUBIKA_CURRENT_AUTO_MESSAGE_IDS.append(
                message_id
            )

    except Exception:

        pass

    await send_rubika_text(
        text
    )

    return int(
        sent.id
    )


NEWS_MEDIA_CAPTION_LIMIT = 1024


async def download_news_media(
    article
):

    url = (
        article.get("video_url")
        or
        article.get("photo_url")
    )

    if not url:

        return None, None

    is_video = bool(
        article.get("video_url")
    )

    suffix = (
        ".mp4"
        if is_video
        else ".jpg"
    )

    dest = (

        BASE
        /
        f"news_media_{int(time.time())}{suffix}"

    )

    def _download():

        response = requests.get(

            url,

            timeout=60,

            stream=True

        )

        response.raise_for_status()

        with open(dest, "wb") as file:

            for chunk in response.iter_content(
                chunk_size=65536
            ):

                if chunk:

                    file.write(chunk)

        return dest

    try:

        path = await asyncio.to_thread(
            _download
        )

    except Exception as error:

        log.warning(
            "NEWS MEDIA DOWNLOAD FAILED: %s",
            error
        )

        return None, None

    return path, is_video


def build_short_news_caption(
    article
):

    header = (
        "🚨 خبر فوری بازار"
        if is_urgent_news(article)
        else "📰 خبر مهم بازار"
    )

    body = sanitize_public_news_text(
        article.get("text", "")
    )

    text = f"{header}\n\n{body}"

    return text[:NEWS_MEDIA_CAPTION_LIMIT]


async def send_news_media_post(
    client,
    target,
    media_path,
    caption,
    is_video
):

    sent = await client.send_file(

        target,

        str(media_path),

        caption=caption,

        supports_streaming=is_video

    )

    log.info(
        "NEWS MEDIA POST SENT | %s",
        sent.id
    )

    try:

        message_id = int(
            sent.id
        )

        if (
            message_id
            not in
            RUBIKA_CURRENT_AUTO_MESSAGE_IDS
        ):

            RUBIKA_CURRENT_AUTO_MESSAGE_IDS.append(
                message_id
            )

    except Exception:

        pass

    return int(
        sent.id
    )


async def send_news_post(
    client,
    target,
    article
):

    if not article:
        return None, None

    if is_blocked_rate_gold_news(article) and (
        article.get("source_channel") not in TRUMP_NEWS_CHANNELS
    ):
        log.warning(
            "NEWS SEND BLOCKED | RATE/GOLD/CURRENCY TOPIC | %s",
            article.get("title", "")
        )
        return None, None

    # News is intentionally text-only. Do not download or attach
    # photos/videos even when the source channel contains media.
    caption = make_news_caption(article)

    if len(caption) >= 4000:
        log.error("NEWS CAPTION TOO LONG -> NOT SENT")
        return None, None

    try:
        news_message_id = await send_text_post(
            client,
            target,
            caption
        )

        log.info(
            "NEWS SENT TEXT ONLY | source=%s | message_id=%s",
            article.get("source_channel", ""),
            news_message_id
        )

        return news_message_id, None

    except Exception as error:
        log.exception("NEWS TEXT SEND FAILED: %s", error)
        return None, None


async def send_trade_banner(
    client,
    target,
    image_path,
    caption
):
    """
    Send Start/End trading artwork as a normal Telegram PHOTO.

    This intentionally does NOT use DocumentAttributeSticker.
    The image is therefore shown as a normal large preview in the
    channel instead of being rendered as a small sticker.
    """
    if not image_path.exists():
        log.warning("TRADE BANNER NOT FOUND | %s", image_path)
        return None

    try:
        sent = await client.send_file(
            target,
            str(image_path),
            caption=caption,
            force_document=False,
            supports_streaming=False,
            allow_cache=False
        )

        log.info(
            "TRADE BANNER SENT AS PHOTO | id=%s | file=%s",
            sent.id,
            image_path.name
        )

        try:
            message_id = int(sent.id)
            if message_id not in RUBIKA_CURRENT_AUTO_MESSAGE_IDS:
                RUBIKA_CURRENT_AUTO_MESSAGE_IDS.append(message_id)
        except Exception:
            pass

        return int(sent.id)

    except Exception as error:
        log.exception(
            "TRADE BANNER SEND FAILED | %s | %s",
            image_path,
            error
        )
        return None

# =========================================================
# PRICE PUBLICATION TRANSACTION
# =========================================================

async def find_existing_price_post(
    client,
    target,
    caption
):

    if not caption:
        return None

    try:

        messages = await client.get_messages(
            target,
            limit=20
        )

        for message in messages or []:

            message_text = (
                getattr(message, "message", None)
                or getattr(message, "text", None)
                or ""
            )

            if message_text.strip() == caption.strip():
                return int(message.id)

    except Exception as error:

        log.warning(
            "PENDING PRICE POST LOOKUP FAILED: %s",
            error
        )

    return None


async def publish_price_transaction(
    client,
    target,
    state,
    rate,
    products,
    source_message_id
):

    current_signature = make_price_signature(
        rate,
        products
    )

    pending = state.get(
        PRICE_PENDING_POST_KEY
    )

    # If an older price transaction is incomplete, finish that transaction
    # first. This prevents publishing a newer Telegram post while its Rubika
    # counterpart is still pending.
    if isinstance(pending, dict):

        pending_signature = pending.get("signature")

        if pending_signature != current_signature:

            pending_rate = pending.get("rate")
            pending_products = pending.get("products")

            if isinstance(pending_rate, dict) and isinstance(pending_products, dict):

                log.warning(
                    "INCOMPLETE PRICE TRANSACTION FOUND -> RESUMING OLD TRANSACTION FIRST"
                )

                result = await publish_price_transaction(
                    client,
                    target,
                    state,
                    pending_rate,
                    pending_products,
                    pending.get("source_message_id")
                )

                if result is None:
                    return None

                # The recursive call commits and clears the old transaction.
                pending = None

            else:

                log.error(
                    "INVALID PENDING PRICE TRANSACTION -> DROPPING CORRUPTED PENDING STATE"
                )

                state.pop(
                    PRICE_PENDING_POST_KEY,
                    None
                )

                save_state(state)

        else:
            log.info(
                "RESUMING PENDING PRICE TRANSACTION | SIGNATURE=%s",
                current_signature
            )

    pending = state.get(
        PRICE_PENDING_POST_KEY
    )

    if not isinstance(pending, dict):

        pending = {
            "signature": current_signature,
            "source_message_id": (
                int(source_message_id)
                if source_message_id is not None
                else None
            ),
            "rate": dict(rate),
            "products": dict(products),
            "caption": make_caption(),
            "telegram_message_id": None,
            "telegram_sent": False,
            "rubika_sent": False,
            "rubika_skipped": False,
            "created_at": iran_now().isoformat()
        }

        state[PRICE_PENDING_POST_KEY] = pending
        save_state(state)

    telegram_message_id = pending.get(
        "telegram_message_id"
    )

    telegram_sent = bool(
        pending.get("telegram_sent") and telegram_message_id
    )

    if not telegram_sent:

        existing_id = await find_existing_price_post(
            client,
            target,
            pending.get("caption", "")
        )

        if existing_id:

            telegram_message_id = existing_id

            log.warning(
                "PENDING PRICE POST ALREADY EXISTS ON TELEGRAM | %s",
                existing_id
            )

        else:

            image = create_board(
                pending["rate"],
                pending["products"]
            )

            telegram_message_id = await send_rate_post(
                client,
                target,
                image,
                pending["caption"]
            )

        pending["telegram_message_id"] = int(
            telegram_message_id
        )
        pending["telegram_sent"] = True

        state[PRICE_PENDING_POST_KEY] = pending
        save_state(state)

        log.info(
            "PRICE TRANSACTION | TELEGRAM COMMITTED | %s",
            telegram_message_id
        )

    # If Rubika is not configured, Telegram remains the authoritative
    # publication and we do not leave a permanently pending transaction.
    if not rubika_is_configured():

        pending["rubika_sent"] = False
        pending["rubika_skipped"] = True

        log.info(
            "PRICE TRANSACTION | RUBIKA SKIPPED | NOT CONFIGURED"
        )

    elif not pending.get("rubika_sent"):

        rubika_ok = await send_rubika_rate_post(
            pending["rate"],
            pending["products"]
        )

        if not rubika_ok:

            state[PRICE_PENDING_POST_KEY] = pending
            save_state(state)

            log.error(
                "PRICE TRANSACTION PAUSED | TELEGRAM SENT | RUBIKA FAILED"
            )

            return None

        pending["rubika_sent"] = True

        state[PRICE_PENDING_POST_KEY] = pending
        save_state(state)

        log.info(
            "PRICE TRANSACTION | RUBIKA COMMITTED"
        )

    # Both destinations are complete. Only now update the committed price
    # signature so the next execution cannot publish the same price again.
    committed_rate = pending["rate"]
    committed_products = pending["products"]

    state.update({
        "source_message_id": (
            int(pending["source_message_id"])
            if pending.get("source_message_id") is not None
            else None
        ),
        "target_message_id": int(telegram_message_id),
        "ounce": committed_rate["ounce"],
        "tehran": committed_rate["tehran"],
        "shot_995": committed_products["shot_995"],
        "nader_9999": committed_products["nader_9999"],
        "mithqal_995": committed_products["mithqal_995"],
        "shot_package": committed_products.get("shot_package"),
        "nader_package": committed_products.get("nader_package"),
        "price_signature": pending["signature"],
        "updated_at": iran_now().isoformat()
    })

    state.pop(
        PRICE_PENDING_POST_KEY,
        None
    )

    remember_rubika_auto_message(
        state,
        telegram_message_id
    )

    save_state(state)

    log.info(
        "PRICE TRANSACTION COMPLETED | TELEGRAM=%s | RUBIKA=%s",
        telegram_message_id,
        bool(pending.get("rubika_sent") or pending.get("rubika_skipped"))
    )

    return int(telegram_message_id)


# =========================================================
# SAVED DATA
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
        ) is None
    ):

        return None

    result = {

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

    if state.get("gold_secondhand") is not None:
        result["gold_secondhand"] = int(
            state["gold_secondhand"]
        )

    return result


def get_saved_gold_ounce(
    state
):

    if state.get(
        "gold_ounce"
    ) is None:

        return None

    try:

        value = float(
            state[
                "gold_ounce"
            ]
        )

        if (
            1000 <= value <= 10000
        ):

            return value

    except Exception:

        pass

    return None


# =========================================================
# LIVE PRICE MONITOR
# =========================================================
# GitHub Actions starts this process on a schedule.  During the running
# window we keep checking Taghizadegan's public Telegram source so a price
# change is reflected without waiting for the next 5-minute workflow tick.
# The GitHub Actions job is not a permanent Telegram process.  Keep the
# interactive admin menu alive for almost the entire 5-minute workflow
# interval so buttons such as «ادامه», duration choices, and «💰 تغییر قیمت»
# are not left waiting for the next scheduled run.
#
# IMPORTANT:
# This is deliberately slightly below 5 minutes.  It gives the workflow a
# small safety margin while still making the menu responsive throughout the
# normal 5-minute schedule.
LIVE_PRICE_POLL_SECONDS = 5
# Keep the total scheduled run comfortably below the 5-minute cron interval.
# The previous 290s window made runs take ~6 minutes, causing queued runners
# and stale state/update consumers while customers were mid-conversation.
LIVE_PRICE_MONITOR_SECONDS = 210


async def monitor_live_price_changes(
    client,
    target,
    state,
):
    """
    Keep the GitHub Actions runner alive for the short interactive window.

    IMPORTANT:
    The Telegram Bot API is polled by process_manual_price_commands(). A
    GitHub Actions job is not a permanent Telegram process, so a single
    getUpdates call at startup can miss a button pressed a few seconds later.
    During this monitor window we poll the bot update queue repeatedly, while
    also doing the existing live-price checks when the market window is open.
    """

    started = time.monotonic()
    last_rate = get_saved_rate(state)

    if isinstance(last_rate, dict):
        last_rate = {
            "ounce": last_rate.get("ounce"),
            "tehran": last_rate.get("tehran"),
        }

    log.info(
        "LIVE PRICE MONITOR STARTED | interval=%ss | duration=%ss | "
        "INTERACTIVE PRICE MENU ENABLED",
        LIVE_PRICE_POLL_SECONDS,
        LIVE_PRICE_MONITOR_SECONDS,
    )

    while (
        time.monotonic() - started
        <
        LIVE_PRICE_MONITOR_SECONDS
    ):
        # ---------------------------------------------------------
        # TELEGRAM INTERACTIVE MENU
        # ---------------------------------------------------------
        # Keep reading Bot API updates throughout the running workflow.
        # This is what makes "💰 تغییر قیمت" and the following buttons work
        # even when they are pressed after the initial /start update.
        try:
            await process_manual_price_commands(
                client,
                state
            )
        except Exception as error:
            log.warning(
                "INTERACTIVE PRICE MENU POLL FAILED | %s",
                error
            )

        # ---------------------------------------------------------
        # LIVE PRICE SOURCE
        # ---------------------------------------------------------
        # Manual menu interaction must work even outside the normal market
        # price window, so only the live-source part is conditional.
        if not is_price_time():
            elapsed = time.monotonic() - started
            remaining = LIVE_PRICE_MONITOR_SECONDS - elapsed

            if remaining <= 0:
                break

            await asyncio.sleep(
                min(
                    LIVE_PRICE_POLL_SECONDS,
                    remaining
                )
            )
            continue

        try:
            rate, source_message_id = await asyncio.to_thread(
                find_latest_public_rate
            )

            rate = apply_manual_rate_overrides(
                state,
                rate
            )

            source_changed = (
                not isinstance(last_rate, dict)
                or rate.get("ounce") != last_rate.get("ounce")
                or rate.get("tehran") != last_rate.get("tehran")
            )

            if source_changed:
                log.info(
                    "LIVE SOURCE PRICE CHANGED | ounce=%s | tehran=%s | message=%s",
                    rate.get("ounce"),
                    rate.get("tehran"),
                    source_message_id,
                )

                products = await get_website_prices()

                products = apply_manual_price_overrides(
                    state,
                    products
                )

                if products is None:
                    log.warning(
                        "LIVE PRICE CHANGE DETECTED BUT WEBSITE PRICES ARE UNAVAILABLE"
                    )
                else:
                    current_signature = make_price_signature(
                        rate,
                        products
                    )

                    pending = state.get(
                        PRICE_PENDING_POST_KEY
                    )

                    if isinstance(pending, dict):
                        pending_rate = pending.get("rate")
                        pending_products = pending.get("products")

                        if (
                            isinstance(pending_rate, dict)
                            and
                            isinstance(pending_products, dict)
                        ):
                            log.info(
                                "LIVE MONITOR | RESUMING INCOMPLETE PRICE TRANSACTION"
                            )

                            await publish_price_transaction(
                                client,
                                target,
                                state,
                                pending_rate,
                                pending_products,
                                pending.get("source_message_id")
                            )

                    if not isinstance(
                        state.get(PRICE_PENDING_POST_KEY),
                        dict
                    ):
                        previous_signature = state.get(
                            "price_signature"
                        )

                        if current_signature != previous_signature:
                            if validate_price_update(
                                rate,
                                products,
                                state
                            ):
                                await publish_price_transaction(
                                    client,
                                    target,
                                    state,
                                    rate,
                                    products,
                                    source_message_id
                                )
                                log.info(
                                    "LIVE PRICE UPDATE PUBLISHED"
                                )
                            else:
                                log.error(
                                    "LIVE PRICE UPDATE BLOCKED BY SAFETY VALIDATION"
                                )
                        else:
                            log.info(
                                "LIVE SOURCE CHANGED BUT FINAL BOARD SIGNATURE DID NOT CHANGE"
                            )

                last_rate = {
                    "ounce": rate.get("ounce"),
                    "tehran": rate.get("tehran"),
                }

            else:
                log.info(
                    "LIVE PRICE CHECK | NO SOURCE CHANGE"
                )

        except Exception as error:
            log.warning(
                "LIVE PRICE MONITOR CHECK FAILED | %s",
                error
            )

        elapsed = time.monotonic() - started
        remaining = LIVE_PRICE_MONITOR_SECONDS - elapsed

        if remaining <= 0:
            break

        await asyncio.sleep(
            min(
                LIVE_PRICE_POLL_SECONDS,
                remaining
            )
        )

    log.info("LIVE PRICE MONITOR FINISHED")


# =========================================================
# MAIN
# =========================================================

async def main():

    if not acquire_process_lock():
        return

    try:
        await _main_locked()
    finally:
        release_process_lock()


async def _main_locked():

    global RUBIKA_CURRENT_AUTO_MESSAGE_IDS

    RUBIKA_CURRENT_AUTO_MESSAGE_IDS = []

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

    if NEWS_ENABLED and AI_NEWS_ENABLED:

        if not OPENAI_API_KEY:

            raise RuntimeError(
                "OPENAI_API_KEY تنظیم نشده است."
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
    sales_expire_orders(state)

    reset_news_day_if_needed(
        state
    )

    now = iran_now()

    current_time = now.strftime(
        "%H:%M"
    )

    current_minute = current_minutes()

    log.info(
        "IRAN TIME = %s",
        current_time
    )

    log.info(
        "MARKET STATUS = %s",
        market_status_text()
    )

    log.info(
        "NEWS STATUS = ENABLED | MAX=%s/DAY | GAP=%s MIN",
        NEWS_TOTAL_MAX_PER_DAY,
        NEWS_MIN_GAP_MINUTES
    )

    log.info(
        "NEWS RATE/GOLD/CURRENCY FILTER = ENABLED"
    )

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

        if ADMIN_TELEGRAM_ID:
            log.info(
                "ADMIN MENU CONFIGURED | ADMIN_TELEGRAM_ID=%s",
                ADMIN_TELEGRAM_ID,
            )
        else:
            log.error(
                "ADMIN MENU NOT CONFIGURED | ADMIN_TELEGRAM_ID is missing"
            )

        await process_manual_price_commands(
            client,
            state
        )

        if not RUBIKA_TOKEN or not RUBIKA_CHAT_ID:

            log.warning(
                "RUBIKA IS NOT CONFIGURED | "
                "RUBIKA_TOKEN/RUBIKA_CHAT_ID MISSING"
            )

        elif RubikaRobot is None:

            log.warning(
                "RUBIKA IS NOT CONFIGURED | "
                "rubka PACKAGE IS MISSING"
            )

        # =================================================
        # MORNING
        # =================================================

        if (

            current_minute
            >=
            MORNING_HOUR * 60
            + MORNING_MINUTE

            and

            current_minute
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
        # POLL ACCURACY RECAP - MORNING
        # =================================================
        # Compares yesterday's market_poll majority vote against
        # what the price actually did, using the snapshot saved by
        # the "POLL ACCURACY SNAPSHOT" block the evening before.

        if (

            current_minute
            >=
            MORNING_HOUR * 60
            + MORNING_MINUTE

            and

            current_minute
            <
            11 * 60

            and

            state.get("poll_result_pending")

            and

            should_send_daily(
                state,
                "poll_accuracy"
            )

        ):

            try:

                pending = state["poll_result_pending"]

                vote_data = (
                    await fetch_poll_vote_counts(
                        client,
                        target,
                        pending["message_id"]
                    )
                )

                accuracy_text = None

                if vote_data:

                    accuracy_text = (
                        make_poll_accuracy_message(
                            vote_data,
                            pending["rate_start"],
                            pending["rate_end"]
                        )
                    )

                if accuracy_text:

                    await send_text_post(
                        client,
                        target,
                        accuracy_text
                    )

                    log.info(
                        "POLL ACCURACY RECAP SENT SUCCESSFULLY"
                    )

                else:

                    log.warning(
                        "POLL ACCURACY RECAP SKIPPED | "
                        "NO VOTES/POLL UNAVAILABLE"
                    )

                # Mark as handled either way so a poll with zero
                # votes (or one that was deleted) doesn't retry
                # forever and block future days.
                mark_daily_sent(
                    state,
                    "poll_accuracy"
                )

                state.pop(
                    "poll_result_pending",
                    None
                )

                save_state(
                    state
                )

            except Exception as error:

                log.exception(
                    "POLL ACCURACY RECAP FAILED: %s",
                    error
                )

        # =================================================
        # WEEKLY ECONOMIC CALENDAR - SATURDAY MORNING
        # =================================================
        # Saturday is the first day of the Iranian trading week
        # (weekday() == 5 with Monday == 0), so this posts once a
        # week, right after the morning message.

        if (

            iran_now().weekday() == 5

            and

            current_minute
            >=
            ECONOMIC_CALENDAR_HOUR * 60
            + ECONOMIC_CALENDAR_MINUTE

            and

            current_minute
            <
            11 * 60

            and

            should_send_daily(
                state,
                "economic_calendar"
            )

        ):

            try:

                calendar_events = (
                    await get_weekly_economic_calendar()
                )

                calendar_text = (
                    make_economic_calendar_message(
                        calendar_events
                    )
                )

                if calendar_text:

                    await send_text_post(
                        client,
                        target,
                        calendar_text
                    )

                    mark_daily_sent(
                        state,
                        "economic_calendar"
                    )

                    save_state(
                        state
                    )

                    log.info(
                        "WEEKLY ECONOMIC CALENDAR SENT SUCCESSFULLY"
                    )

                else:

                    log.warning(
                        "ECONOMIC CALENDAR SKIPPED | NO EVENTS/EMPTY"
                    )

            except Exception as error:

                log.exception(
                    "ECONOMIC CALENDAR FAILED: %s",
                    error
                )

        # =================================================
        # 22:10 NIGHTLY MARKET POLL
        # =================================================
        # DAILY MARKET POLL
        # =================================================
        # The percentage poll is now sent immediately after the
        # daily market recap, so no separate late-night duplicate
        # poll is scheduled here.

        # =================================================
        # FETCH CURRENT PRICE
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

                rate = apply_manual_rate_overrides(
                    state,
                    rate
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

            products = apply_manual_price_overrides(
                state,
                products
            )

        else:

            log.info(
                "PRICE CHECK SKIPPED"
            )

        # =================================================
        # PRICE UPDATE
        # =================================================

        if (

            is_price_time()

            and

            rate is not None

            and

            products is not None

        ):

            current_signature = make_price_signature(
                rate,
                products
            )

            # Always finish an incomplete transaction first. This is done
            # before validating the newest source price so a temporary parser
            # anomaly cannot prevent the older Telegram/Rubika transaction
            # from being completed.
            pending = state.get(
                PRICE_PENDING_POST_KEY
            )

            if isinstance(pending, dict):

                pending_rate = pending.get("rate")
                pending_products = pending.get("products")

                if isinstance(pending_rate, dict) and isinstance(pending_products, dict):

                    log.info(
                        "INCOMPLETE PRICE TRANSACTION -> RESUME BEFORE NEW PRICE CHECK"
                    )

                    await publish_price_transaction(
                        client,
                        target,
                        state,
                        pending_rate,
                        pending_products,
                        pending.get("source_message_id")
                    )

                    # State may have changed after the resumed transaction.
                    pending = state.get(PRICE_PENDING_POST_KEY)

            if not isinstance(pending, dict):

                previous_signature = state.get(
                    "price_signature"
                )

                if current_signature != previous_signature:

                    if not validate_price_update(
                        rate,
                        products,
                        state
                    ):

                        log.error(
                            "PRICE UPDATE BLOCKED BY SAFETY VALIDATION"
                        )

                    else:

                        log.info(
                            "PRICE CHANGED -> STARTING TRANSACTIONAL PUBLICATION"
                        )

                        await publish_price_transaction(
                            client,
                            target,
                            state,
                            rate,
                            products,
                            source_message_id
                        )

                else:

                    log.info(
                        "PRICE NOT CHANGED -> NO POST"
                    )


        # =================================================
        # MARKET HISTORY
        # =================================================

        if (
            rate is not None
            and
            products is not None
        ):

            try:

                append_market_history(
                    state,
                    rate,
                    products,
                    state.get("gold_ounce")
                )

                save_state(
                    state
                )

            except Exception as error:

                log.exception(
                    "MARKET HISTORY UPDATE FAILED: %s",
                    error
                )

        # =================================================
        # PRICE ALERTS
        # =================================================

        if (
            rate is not None
            and
            products is not None
        ):

            alert_rate = dict(rate)

            saved_gold_ounce = get_saved_gold_ounce(
                state
            )

            if saved_gold_ounce is not None:

                alert_rate[
                    "gold_ounce"
                ] = saved_gold_ounce

            else:

                alert_rate[
                    "gold_ounce"
                ] = None

            try:

                alerts = price_alerts(
                    state,
                    alert_rate,
                    products
                )

                if alerts:

                    alert_text = (
                        "\n\n"
                        .join(alerts)
                        +
                        "\n\n"
                        "📌 این پیام فقط هشدار تغییر قابل‌توجه "
                        "است و توصیه خرید یا فروش نیست."
                        +
                        channel_footer()
                    )

                    if len(alert_text) < 4000:

                        await send_text_post(
                            client,
                            target,
                            alert_text
                        )

                        save_state(
                            state
                        )

                        log.info(
                            "PRICE ALERTS SENT | count=%s",
                            len(alerts)
                        )

            except Exception as error:

                log.exception(
                    "PRICE ALERTS FAILED: %s",
                    error
                )

        # =================================================
        # START TRADES
        # =================================================

        if (

            not is_market_holiday()

            and

            current_minute
            >=
            START_TRADES_HOUR * 60
            + START_TRADES_MINUTE

            and

            current_minute
            <
            END_TRADES_HOUR * 60

            and

            should_send_daily(
                state,
                "start_trades"
            )

        ):

            try:

                message_id = await send_trade_banner(

                    client,
                    target,
                    START_TRADES_IMAGE,
                    START_TRADES_CAPTION

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
                    "START TRADE BANNER FAILED: %s",
                    error
                )

        # =================================================
        # MASHHAD REPORTS
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

            # Refresh the clock immediately before checking the report slot.
            # The old code used the minute captured near the start of the
            # workflow. If GitHub Actions started a few minutes before the
            # slot, or if earlier work took time, the 11:00/15:00/18:00
            # report could be skipped even though the process was still alive.
            report_current_minute = current_minutes()

            # GitHub Actions scheduled runs can be delayed under load. Keep
            # a generous catch-up window; should_send_daily() still guarantees
            # each report is sent only once per day.
            report_window_end = start_minute + 60

            log.info(
                "MASHHAD REPORT CHECK | TIME=%s | CURRENT=%s | WINDOW=%s-%s",
                report_time,
                report_current_minute,
                start_minute,
                report_window_end
            )

            if (

                start_minute
                <=
                report_current_minute
                <
                report_window_end

                and

                not is_market_holiday()

            ):

                if should_send_daily(
                    state,
                    report_key
                ):

                    # -----------------------------------------
                    # دریافت قیمت طلای ۱۸ و سکه
                    # -----------------------------------------

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

                    # -----------------------------------------
                    # دریافت انس طلا
                    # -----------------------------------------

                    gold_ounce = None

                    try:

                        gold_ounce = (
                            await get_gold_ounce()
                        )

                        state[
                            "gold_ounce"
                        ] = gold_ounce

                        state[
                            "gold_ounce_updated_at"
                        ] = iran_now().isoformat()

                        save_state(
                            state
                        )

                    except Exception as error:

                        log.warning(
                            "GOLD OUNCE FETCH FAILED: %s",
                            error
                        )

                        gold_ounce = (
                            get_saved_gold_ounce(
                                state
                            )
                        )

                        if gold_ounce is not None:

                            log.info(
                                "USING SAVED GOLD OUNCE = %.2f",
                                gold_ounce
                            )

                    # -----------------------------------------
                    # نرخ دلار و انس نقره
                    # بدون تغییر نسبت به قبل
                    # -----------------------------------------

                    report_rate = rate

                    if report_rate is None:

                        report_rate = (
                            get_saved_rate(
                                state
                            )
                        )

                    # -----------------------------------------
                    # قیمت خرید طلای دست‌دوم
                    # -----------------------------------------

                    try:

                        secondhand_config = (
                            MARKET_PULSE_TGJU_SYMBOLS.get(
                                "gold_secondhand"
                            )
                        )

                        if secondhand_config:

                            secondhand_item = await asyncio.to_thread(
                                fetch_tgju_market_item,
                                "gold_secondhand",
                                secondhand_config
                            )

                            if (
                                secondhand_item
                                and
                                secondhand_item.get("value") is not None
                            ):

                                mashhad_market[
                                    "gold_secondhand"
                                ] = int(
                                    round(
                                        secondhand_item["value"]
                                    )
                                )

                                state[
                                    "gold_secondhand"
                                ] = mashhad_market[
                                    "gold_secondhand"
                                ]

                                save_state(
                                    state
                                )

                                log.info(
                                    "MASHHAD REPORT SECONDHAND GOLD = %s",
                                    mashhad_market[
                                        "gold_secondhand"
                                    ]
                                )

                    except Exception as error:

                        log.warning(
                            "MASHHAD REPORT SECONDHAND GOLD FAILED: %s",
                            error
                        )

                    # -----------------------------------------
                    # ارسال گزارش
                    # -----------------------------------------

                    if mashhad_market is not None:

                        if report_rate is not None:

                            try:

                                await send_text_post(

                                    client,
                                    target,

                                    make_mashhad_report(

                                        mashhad_market,
                                        report_rate,
                                        gold_ounce

                                    )

                                )

                                mark_daily_sent(
                                    state,
                                    report_key
                                )

                                save_state(
                                    state
                                )

                                log.info(
                                    "MASHHAD REPORT SENT | "
                                    "TIME=%s | GOLD_OUNCE=%s",
                                    report_time,
                                    gold_ounce
                                )

                            except Exception as error:

                                log.exception(
                                    "MASHHAD REPORT SEND FAILED: %s",
                                    error
                                )

        # =================================================
        # MARKET PULSE
        # =================================================

        market_pulse_slots = [
            (
                "market_pulse_noon",
                MARKET_PULSE_HOUR,
                MARKET_PULSE_MINUTE,
                "۱۲:۰۰"
            ),
            (
                "market_pulse_evening",
                MARKET_PULSE_EVENING_HOUR,
                MARKET_PULSE_EVENING_MINUTE,
                "۲۰:۳۰"
            ),
        ]

        for (
            pulse_name,
            pulse_hour,
            pulse_minute,
            pulse_label
        ) in market_pulse_slots:

            pulse_start = (
                pulse_hour * 60
                +
                pulse_minute
            )

            if (
                not is_market_holiday()
                and
                current_minute >= pulse_start
                and
                current_minute < pulse_start + 20
                and
                should_send_daily(
                    state,
                    pulse_name
                )
            ):

                try:
                    pulse_data = (
                        await get_market_pulse_data()
                    )

                    if not pulse_data:
                        raise RuntimeError(
                            "هیچ داده‌ای برای نبض بازار دریافت نشد."
                        )

                    previous_snapshot = None

                    if pulse_name == "market_pulse_evening":
                        previous_snapshot = state.get(
                            "market_pulse_noon_snapshot"
                        )

                    pulse_text = make_market_pulse(
                        pulse_data,
                        previous_snapshot,
                        pulse_label
                    )

                    await send_text_post(
                        client,
                        target,
                        pulse_text
                    )

                    if pulse_name == "market_pulse_noon":
                        state[
                            "market_pulse_noon_snapshot"
                        ] = {
                            key: item.get("value")
                            for key, item
                            in pulse_data.items()
                            if (
                                isinstance(item, dict)
                                and
                                item.get("value") is not None
                            )
                        }

                    if pulse_name == "market_pulse_evening":
                        state.pop(
                            "market_pulse_noon_snapshot",
                            None
                        )

                    mark_daily_sent(
                        state,
                        pulse_name
                    )

                    save_state(
                        state
                    )

                    log.info(
                        "MARKET PULSE SENT | %s",
                        pulse_label
                    )

                except Exception as error:
                    log.exception(
                        "MARKET PULSE FAILED | %s | %s",
                        pulse_label,
                        error
                    )

        # =================================================
        # AI ECONOMY LESSON
        # =================================================

        if (

            current_minute
            >=
            ECONOMY_MINUTE_HOUR * 60
            + ECONOMY_MINUTE_MINUTE

            and

            current_minute
            <
            ECONOMY_MINUTE_HOUR * 60
            + ECONOMY_MINUTE_MINUTE
            + 20

            and

            should_send_daily(
                state,
                "economy_lesson"
            )

        ):

            try:

                lesson = await ai_economy_lesson()

                if lesson:

                    lesson_text = (

                        "💡 یک دقیقه اقتصاد\n"
                        "━━━━━━━━━━━━━━\n\n"
                        + lesson
                        + "\n\n"
                        "💬 نظر شما چیه؟"

                        + channel_footer()

                    )

                    if len(lesson_text) < 4000:

                        await send_text_post(

                            client,
                            target,
                            lesson_text

                        )

                        mark_daily_sent(
                            state,
                            "economy_lesson"
                        )

                        save_state(
                            state
                        )

            except Exception as error:

                log.exception(
                    "ECONOMY LESSON FAILED: %s",
                    error
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

            history_titles = state.get(
                "news_title_history",
                []
            )

            if not isinstance(
                history_titles,
                list
            ):

                history_titles = []

            # سازگاری با stateهای قدیمیِ ذخیره‌شده.
            history_fingerprints = state.get(
                "news_fingerprint_history"
            )

            if not isinstance(history_fingerprints, list):
                history_fingerprints = state.get(
                    "news_content_history",
                    []
                )

            if not isinstance(
                history_fingerprints,
                list
            ):

                history_fingerprints = []

            news_article = None
            news_category = "telegram_trump"

            # اولویت اول: سه کانال مشخص‌شده برای اخبار ترامپ.
            try:

                news_article = (
                    await get_trump_channel_news(
                        history,
                        history_titles
                    )
                )

                if news_article:
                    log.info(
                        "TRUMP NEWS SELECTED | %s | %s",
                        news_article.get("source_channel", ""),
                        news_article.get("title", "")
                    )

            except Exception as error:

                log.exception(
                    "TRUMP TELEGRAM NEWS FAILED: %s",
                    error
                )

            # اگر خبر ترامپ پیدا نشد، منطق قبلی منابع اقتصادی ادامه پیدا می‌کند.
            if news_article is None:
                news_category = "economic"

                try:

                    news_article = (
                        await get_economic_news(
                            history,
                            history_titles
                        )
                    )

                except Exception as error:

                    log.exception(
                        "ECONOMIC NEWS FAILED: %s",
                        error
                    )

            if news_article is None:

                try:

                    news_article = (
                        await get_world_news(
                            history,
                            history_titles
                        )
                    )

                    news_category = "world"

                except Exception as error:

                    log.exception(
                        "WORLD NEWS FAILED: %s",
                        error
                    )

            if news_article is None:

                try:

                    news_article = (
                        await get_telegram_channel_news(
                            history,
                            history_titles
                        )
                    )

                    news_category = "telegram"

                except Exception as error:

                    log.exception(
                        "TELEGRAM CHANNEL NEWS FAILED: %s",
                        error
                    )

            if news_article:

                if (
                    news_article.get("source_channel") not in TRUMP_NEWS_CHANNELS
                    and
                    is_blocked_rate_gold_news(
                        news_article
                    )
                ):

                    log.warning(
                        "NEWS REJECTED BEFORE AI | "
                        "RATE/GOLD/CURRENCY | %s",
                        news_article.get(
                            "title",
                            ""
                        )
                    )

                    news_article = None

            if news_article:

                try:

                    original_url = (
                        news_article["url"]
                    )

                    original_title = (
                        news_article["title"]
                    )

                    original_text = (
                        news_article.get(
                            "text",
                            ""
                        )
                    )

                    original_length = len(
                        original_text
                    )

                    log.info(
                        "ORIGINAL NEWS LENGTH = %s",
                        original_length
                    )

                    log.info(
                        "AI PROCESSING NEWS = %s",
                        original_title
                    )

                    ai_article = (
                        await ai_summarize_news(
                            news_article
                        )
                    )

                    if ai_article:

                        ai_article["url"] = (
                            original_url
                        )

                        if (
                            "importance"
                            in news_article
                        ):

                            ai_article[
                                "importance"
                            ] = news_article[
                                "importance"
                            ]

                        if (
                            "video_url"
                            in news_article
                        ):

                            ai_article[
                                "video_url"
                            ] = news_article[
                                "video_url"
                            ]

                        if (
                            "photo_url"
                            in news_article
                        ):

                            ai_article[
                                "photo_url"
                            ] = news_article[
                                "photo_url"
                            ]

                        if (
                            ai_article.get("source_channel") not in TRUMP_NEWS_CHANNELS
                            and
                            is_blocked_rate_gold_news(
                                ai_article
                            )
                        ):

                            log.warning(
                                "AI NEWS BLOCKED AFTER SUMMARY | "
                                "RATE/GOLD/CURRENCY | %s",
                                ai_article.get(
                                    "title",
                                    ""
                                )
                            )

                            news_article = None

                        else:

                            news_article = ai_article

                            log.info(
                                "AI NEWS READY | %s",
                                news_article["title"]
                            )

                    else:

                        news_article = None

                except Exception as error:

                    log.exception(
                        "AI NEWS FAILED: %s",
                        error
                    )

                    news_article = None

            if news_article:

                if is_blocked_rate_gold_news(
                    news_article
                ):

                    log.warning(
                        "FINAL NEWS BLOCK | RATE/GOLD/CURRENCY | %s",
                        news_article.get(
                            "title",
                            ""
                        )
                    )

                    news_article = None

            if news_article:

                source_story = {
                    "title": news_article.get(
                        "source_title",
                        news_article.get("title", "")
                    ),
                    "text": news_article.get(
                        "source_text",
                        news_article.get("text", "")
                    ),
                    "url": news_article.get("url", "")
                }

                if is_duplicate_news(
                    source_story,
                    history_titles,
                    history_fingerprints,
                    history_urls=history
                ):
                    log.warning(
                        "FINAL SOURCE DUPLICATE BLOCK | %s",
                        source_story.get("title", "")
                    )
                    news_article = None

            if news_article:

                try:

                    (
                        news_message_id,
                        poll_message_id
                    ) = (

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
                            news_message_id,
                            news_category,
                            poll_message_id

                        )

                        save_state(
                            state
                        )

                        log.info(
                            "AI NEWS + POLL SENT SUCCESSFULLY | "
                            "CATEGORY=%s | NEWS=%s | POLL=%s | TOTAL=%s/%s",
                            news_category,
                            news_message_id,
                            poll_message_id,
                            state.get(
                                "news_count",
                                0
                            ),
                            NEWS_TOTAL_MAX_PER_DAY
                        )

                except Exception as error:

                    log.exception(
                        "NEWS SEND FAILED: %s",
                        error
                    )

            else:

                log.info(
                    "NO SUITABLE NEWS FOUND THIS RUN"
                )

        # =================================================
        # MARKET RECAP
        # =================================================

        if (

            current_minute
            >=
            MARKET_RECAP_HOUR * 60
            + MARKET_RECAP_MINUTE

            and

            current_minute
            <
            MARKET_RECAP_HOUR * 60
            + MARKET_RECAP_MINUTE
            + 20

            and

            should_send_daily(
                state,
                "market_recap"
            )

        ):

            recap_rate = rate

            recap_products = products

            recap_market = get_saved_market(
                state
            )

            if recap_rate is None:

                recap_rate = get_saved_rate(
                    state
                )

            if recap_products is None:

                recap_products = get_saved_products(
                    state
                )

            if (
                recap_rate
                and
                recap_products
                and
                recap_market
            ):

                try:

                    recap = await ai_market_recap(

                        recap_rate,
                        recap_products,
                        recap_market

                    )

                    if recap:

                        recap_text = (

                            "🌙 جمع‌بندی بازار امروز\n"
                            "━━━━━━━━━━━━━━\n\n"
                            + recap
                            + "\n\n"
                            "📌 برای دنبال کردن نرخ‌های "
                            "به‌روز نقره، کانال یزدان‌دوست را دنبال کنید."

                            + channel_footer()

                        )

                        if len(recap_text) < 4000:

                            await send_text_post(

                                client,
                                target,
                                recap_text

                            )

                            mark_daily_sent(
                                state,
                                "market_recap"
                            )

                            # نظرسنجی درصدی بلافاصله بعد از جمع‌بندی روزانه ارسال می‌شود.
                            try:

                                poll_message_id = await send_market_poll(
                                    client,
                                    target
                                )

                                if poll_message_id:

                                    poll_ref_rate = get_saved_rate(
                                        state
                                    )

                                    if poll_ref_rate:

                                        state["poll_ref"] = {
                                            "date": jalali_date_key(),
                                            "message_id": poll_message_id,
                                            "rate_tehran": poll_ref_rate["tehran"],
                                        }

                                    log.info(
                                        "MARKET RECAP PERCENTAGE POLL SENT | %s",
                                        poll_message_id
                                    )

                            except Exception as poll_error:

                                log.exception(
                                    "MARKET RECAP PERCENTAGE POLL FAILED: %s",
                                    poll_error
                                )

                            save_state(
                                state
                            )

                except Exception as error:

                    log.exception(
                        "MARKET RECAP FAILED: %s",
                        error
                    )

        # =================================================
        # TOMORROW LOOK
        # =================================================

        if (

            current_minute
            >=
            TOMORROW_LOOK_HOUR * 60
            + TOMORROW_LOOK_MINUTE

            and

            current_minute
            <
            TOMORROW_LOOK_HOUR * 60
            + TOMORROW_LOOK_MINUTE
            + 20

            and

            should_send_daily(
                state,
                "tomorrow_look"
            )

        ):

            try:

                tomorrow = await ai_tomorrow_message()

                if tomorrow:

                    tomorrow_text = (

                        "👀 فردا بازار را با این موارد دنبال کنید\n"
                        "━━━━━━━━━━━━━━\n\n"
                        + tomorrow

                        + channel_footer()

                    )

                    if len(tomorrow_text) < 4000:

                        # متن تحلیلی را جداگانه منتشر می‌کنیم تا سؤال انتهایی
                        # به‌صورت نظرسنجی واقعی و قابل کلیک نمایش داده شود.
                        # درصد رأی‌ها را خود Telegram به‌صورت زنده نمایش می‌دهد.
                        await send_text_post(
                            client,
                            target,
                            tomorrow_text
                        )

                        tomorrow_poll = build_telegram_poll(
                            "👀 فردا کدام مورد را در اولویت قرار می‌دهید؟",
                            [
                                ("📊 تحولات اقتصادی و سیاسی", b"\x11"),
                                ("🌐 رفتار انس جهانی نقره", b"\x12"),
                                ("📰 اخبار مهم اقتصادی و سیاسی", b"\x13"),
                            ]
                        )

                        await client(
                            SendMediaRequest(
                                peer=target,
                                media=InputMediaPoll(
                                    poll=tomorrow_poll
                                ),
                                message=(
                                    "👆 انتخاب کنید؛ نتیجه نظرسنجی "
                                    "به‌صورت درصدی نمایش داده می‌شود."
                                ),
                                random_id=poll_random_id()
                            )
                        )

                        mark_daily_sent(
                            state,
                            "tomorrow_look"
                        )

                        save_state(
                            state
                        )

            except Exception as error:

                log.exception(
                    "TOMORROW LOOK FAILED: %s",
                    error
                )

        # =================================================
        # END TRADES
        # =================================================

        if (

            not is_market_holiday()

            and

            current_minute
            >=
            END_TRADES_HOUR * 60
            + END_TRADES_MINUTE

            and

            should_send_daily(
                state,
                "end_trades"
            )

        ):

            try:

                message_id = await send_trade_banner(
                    client,
                    target,
                    END_TRADES_IMAGE,
                    END_TRADES_CAPTION
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
                    "END TRADE BANNER FAILED: %s",
                    error
                )

        # =================================================
        # WEEKLY SILVER ANALYSIS - FRIDAY 20:00
        # =================================================

        if should_send_weekly_silver_analysis(
            state
        ):

            try:
                weekly_rate = rate

                if weekly_rate is None:
                    weekly_rate = get_saved_rate(
                        state
                    )

                weekly_products = products

                if weekly_products is None:
                    weekly_products = get_saved_products(
                        state
                    )

                if (
                    weekly_rate is not None
                    and
                    weekly_products is not None
                ):

                    await send_weekly_silver_analysis(
                        client,
                        target,
                        state,
                        weekly_rate,
                        weekly_products
                    )

                else:
                    log.warning(
                        "WEEKLY SILVER ANALYSIS SKIPPED | "
                        "RATE/PRODUCTS UNAVAILABLE"
                    )

            except Exception as error:

                log.exception(
                    "WEEKLY SILVER ANALYSIS FAILED: %s",
                    error
                )

        # =================================================
        # DAILY SILVER VISUAL ANALYSIS - 21:45
        # =================================================

        if should_send_daily_silver_analysis(
            state
        ):

            try:
                daily_rate = rate

                if daily_rate is None:
                    daily_rate = get_saved_rate(
                        state
                    )

                daily_products = (
                    dict(products)
                    if isinstance(products, dict)
                    else None
                )

                saved_products = get_saved_products(
                    state
                )

                if daily_products is None:
                    daily_products = (
                        dict(saved_products)
                        if isinstance(saved_products, dict)
                        else None
                    )
                elif isinstance(saved_products, dict):
                    # داده‌ی تازه را حفظ می‌کنیم، اما کلیدهای مفقود را از
                    # آخرین snapshot معتبر state تکمیل می‌کنیم.
                    for product_key, product_value in saved_products.items():
                        if daily_products.get(product_key) is None:
                            daily_products[product_key] = product_value

                # اگر parser سایت قیمت per-gram را موقتاً نداد، از قیمت
                # بسته‌ی ۱۰۰۰ گرمی همان محصول محاسبه می‌کنیم.
                if (
                    isinstance(daily_products, dict)
                    and daily_products.get("shot_995") is None
                ):
                    shot_package = daily_products.get("shot_package")

                    if shot_package is not None:
                        try:
                            daily_products["shot_995"] = int(
                                round(
                                    float(shot_package) / 1000.0
                                )
                            )
                        except (TypeError, ValueError):
                            pass

                if (
                    daily_rate is not None
                    and
                    daily_products is not None
                ):

                    await send_daily_silver_analysis(
                        client,
                        target,
                        state,
                        daily_rate,
                        daily_products
                    )

                else:
                    log.warning(
                        "DAILY SILVER VISUAL ANALYSIS SKIPPED | "
                        "RATE/PRODUCTS UNAVAILABLE"
                    )

            except Exception as error:

                log.exception(
                    "DAILY SILVER VISUAL ANALYSIS FAILED: %s",
                    error
                )


        # =================================================
        # BI-DAILY MARKET ANALYSIS - 22:00
        # =================================================

        if should_send_market_analysis(
            state
        ):

            try:

                analysis_rate = rate

                if analysis_rate is None:

                    analysis_rate = get_saved_rate(
                        state
                    )

                analysis_products = products

                if analysis_products is None:

                    analysis_products = get_saved_products(
                        state
                    )

                analysis_gold_ounce = (
                    get_saved_gold_ounce(
                        state
                    )
                )

                if (
                    analysis_rate is not None
                    and
                    analysis_products is not None
                ):

                    tradingview_data = (
                        await get_tradingview_market_data()
                    )

                    snapshot = (
                        build_market_analysis_snapshot(
                            state,
                            analysis_rate,
                            analysis_products,
                            analysis_gold_ounce,
                            tradingview_data
                        )
                    )

                    analysis = await ai_market_analysis(
                        snapshot
                    )

                    if analysis:

                        analysis_text = (
                            "📊 تحلیل بازار نقره | یزدان‌دوست\n"
                            "━━━━━━━━━━━━━━\n\n"
                            + analysis
                            + "\n\n"
                            "⚠️ این تحلیل احتمالی است و "
                            "توصیه خرید یا فروش محسوب نمی‌شود."
                            +
                            channel_footer()
                        )

                        if len(analysis_text) < 4000:

                            await send_text_post(
                                client,
                                target,
                                analysis_text
                            )

                            mark_market_analysis_sent(
                                state
                            )

                            state[
                                "last_market_analysis_snapshot"
                            ] = snapshot

                            save_state(
                                state
                            )

                            log.info(
                                "BI-DAILY MARKET ANALYSIS SENT"
                            )

                else:

                    log.warning(
                        "MARKET ANALYSIS SKIPPED | "
                        "RATE/PRODUCTS UNAVAILABLE"
                    )

            except Exception as error:

                log.exception(
                    "BI-DAILY MARKET ANALYSIS FAILED: %s",
                    error
                )

        # =================================================
        # POLL ACCURACY SNAPSHOT - END OF DAY
        # =================================================
        # If today's market poll was sent, capture today's closing
        # price once, near day end, so tomorrow morning's recap can
        # compare the prediction against what actually happened.

        if (

            current_minute
            >=
            21 * 60

            and

            state.get("poll_ref", {}).get("date")
            ==
            jalali_date_key()

            and

            should_send_daily(
                state,
                "poll_snapshot"
            )

        ):

            try:

                snapshot_rate = get_saved_rate(
                    state
                )

                if snapshot_rate:

                    state["poll_result_pending"] = {

                        "message_id":
                            state["poll_ref"]["message_id"],

                        "rate_start":
                            state["poll_ref"]["rate_tehran"],

                        "rate_end":
                            snapshot_rate["tehran"],

                    }

                    mark_daily_sent(
                        state,
                        "poll_snapshot"
                    )

                    save_state(
                        state
                    )

                    log.info(
                        "POLL ACCURACY SNAPSHOT SAVED"
                    )

            except Exception as error:

                log.exception(
                    "POLL ACCURACY SNAPSHOT FAILED: %s",
                    error
                )

        # =================================================
        # 24H REPORT
        # =================================================

        if (

            current_minute
            >=
            REPORT_24H_HOUR * 60
            + REPORT_24H_MINUTE

            and

            current_minute
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

                try:

                    report_rate, _ = (
                        await asyncio.to_thread(
                            find_latest_public_rate
                        )
                    )

                    report_rate = apply_manual_rate_overrides(
                        state,
                        report_rate
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
                        "24H REPORT SKIPPED"
                    )

            except Exception as error:

                log.exception(
                    "24H REPORT FAILED: %s",
                    error
                )

        # =================================================
        # LIVE PRICE MONITOR
        # =================================================

        try:

            await monitor_live_price_changes(
                client,
                target,
                state
            )

        except Exception as error:

            log.exception(
                "LIVE PRICE MONITOR FAILED: %s",
                error
            )

        # =================================================
        # TELEGRAM -> RUBIKA MANUAL SYNC
        # =================================================

        for auto_message_id in RUBIKA_CURRENT_AUTO_MESSAGE_IDS:

            remember_rubika_auto_message(

                state,

                auto_message_id

            )

        save_state(
            state
        )

        await sync_manual_telegram_messages(

            client,

            target,

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
