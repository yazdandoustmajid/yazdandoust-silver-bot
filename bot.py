# -*- coding: utf-8 -*-
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from telethon import TelegramClient
from telethon.tl.functions.messages import SendMediaRequest
from telethon.tl.types import (
    InputMediaPoll,
    Poll,
    PollAnswer
)
from openai import OpenAI

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

START_STICKER = BASE / "start_trades.webp"
END_STICKER = BASE / "end_trades.webp"


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

MASHHAD_UNION_URL = os.getenv(
    "MASHHAD_UNION_URL",
    "https://etjmir.ir"
).strip()


# =========================================================
# GOLD OUNCE SOURCE
# =========================================================

GOLD_OUNCE_URL = os.getenv(
    "GOLD_OUNCE_URL",
    "https://www.tgju.org/profile/%D8%A7%D9%86%D8%B3-%D8%B7%D9%84%D8%A7"
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
        outline=(235, 105, 105),
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
        fill=(105, 215, 145)
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
        fill=(240, 120, 120)
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
        (100, 205, 140)
    )

    draw.text(
        (
            105,
            1240
        ),
        f"مقاومت: {format_level(resistance, 0)} تومان",
        font=small_font,
        fill=(235, 110, 110)
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

    yahoo_data = await get_yahoo_market_data()

    snapshot = build_market_analysis_snapshot(
        state,
        rate,
        products,
        get_saved_gold_ounce(state),
        yahoo_data
    )

    # مقدارهای تحلیل را با آخرین داده‌های واقعی داخلی هماهنگ می‌کنیم.
    shot_current = float(
        products["shot_995"]
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
        "📌 داده‌های نمودار از تاریخچه ثبت‌شده قیمت "
        "در خود ربات استخراج شده‌اند."
        "\n\n"
        "📲 @yazdandoustsilver"
    )

    if len(caption) >= 4000:
        caption = (
            caption[:3950]
            + "\n\n📲 @yazdandoustsilver"
        )

    message_id = await send_rate_post(
        client,
        target,
        image,
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

    if not (
        start
        <= now_minutes
        <
        start + 20
    ):
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

# نمادهای Yahoo Finance برای تحلیل عوامل اثرگذار بر نقره.
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

NEWS_MIN_GAP_MINUTES = 120

NEWS_HISTORY_LIMIT = 300

NEWS_MIN_IMPORTANCE = 6

NEWS_MAX_CANDIDATES_PER_SOURCE = 20

NEWS_AI_RETRY_DELAY_SECONDS = 4

NEWS_TITLE_SIMILARITY_LIMIT = 0.78


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
    "ین",
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

    return await asyncio.to_thread(
        find_latest_mashhad_market
    )


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
    coin_price
):

    intrinsic = (

        rate["ounce"]
        * rate["tehran"]
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

    return (

        "\n\n"
        "━━━━━━━━━━━━━━\n"
        "📲 عضویت در کانال قیمت نقره یزدان‌دوست:\n"
        f"{CHANNEL_LINK}"

    )


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

        "━━━━━━━━━━━━━━\n"
        "📲 عضویت در کانال قیمت نقره یزدان‌دوست:\n"
        f"{CHANNEL_LINK}"

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

    return any(

        keyword.lower() in text

        for keyword in keywords

    )


def keyword_hits(
    text,
    keywords
):

    text = normalize_fa(
        text
    ).lower()

    hits = 0

    for keyword in keywords:

        if keyword.lower() in text:

            hits += 1

    return hits


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


def is_duplicate_news(
    article,
    history_titles
):

    title = article.get(
        "title",
        ""
    )

    for old_title in history_titles:

        if news_titles_similar(
            title,
            old_title
        ):

            log.info(
                "DUPLICATE NEWS SKIPPED | %s | OLD=%s",
                title,
                old_title
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
                history_titles
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
                history_titles
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

    if not generated_words:

        return 0.0

    return (
        len(
            source_words
            &
            generated_words
        )
        /
        len(generated_words)
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

    if overlap >= 0.78:

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

        if (
            "ارتباط با بازار نقره" in normalized
            or
            "اثر بر نقره" in normalized
            or
            "بازار نقره" in normalized
        ):

            current = "silver"

            remainder = re.sub(
                r"^(?:🥈\s*)?(?:ارتباط با بازار نقره|اثر بر نقره|بازار نقره)\s*[:：]?\s*",
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

    if not sections["why"]:

        sections["why"] = (
            "این خبر می‌تواند بر فضای بازار اثرگذار باشد."
        )

    if not sections["silver"]:

        sections["silver"] = (
            "ارتباط آن با نقره می‌تواند از مسیر تحولات اقتصادی و بازار جهانی باشد."
        )

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

    generated_content = "\n".join([

        sections["title"],
        sections["text"],
        sections["why"],
        sections["silver"]

    ])

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

    ai_article_for_filter = {

        "title":
            sections["title"],

        "text":
            (
                sections["text"]
                + " "
                + sections["why"]
                + " "
                + sections["silver"]
            )

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
11. بخش «چرا مهم است» فقط یک جمله کوتاه باشد.
12. بخش «ارتباط با بازار نقره» فقط یک جمله کوتاه باشد.
13. از تکرار یک مفهوم در بخش‌های مختلف خودداری کن.
14. اگر ارتباط مستقیم با نقره وجود ندارد،
    صادقانه بگو ارتباط غیرمستقیم است.
15. از عبارت‌های زرد و هیجانی استفاده نکن.
16. هیچ Markdown و هشتگ استفاده نکن.
17. از ایموجی‌های 🟢، 🟡 و 🔴 برای تحلیل بازار استفاده نکن.
18. سؤال پایانی تولید نکن.
19. ساعت یا زمان انتشار خبر را در خروجی نیاور.
20. عنوان باید کوتاه و خبری باشد.
21. متن باید خلاصه واقعی و مستقل باشد، نه بازنویسی خط‌به‌خط.
22. اگر موضوع اصلی خبر قیمت یا نرخ دلار، هر نوع ارز،
    طلا، طلای جهانی، سکه یا نرخ تبدیل ارزهاست،
    این خبر نباید برای انتشار انتخاب شود.
23. اگر خبر صرفاً درباره تغییر قیمت یا نرخ دلار،
    ارز، طلا یا سکه است، آن را منتشر نکن.
24. حتی اگر خبر درباره یک رویداد اقتصادی باشد،
    نباید موضوع اصلی آن نرخ دلار، نرخ ارز،
    قیمت طلا یا قیمت سکه باشد.
25. خروجی دقیقاً با این ساختار باشد:

عنوان: ...

متن:
...

چرا مهم است:
...

ارتباط با بازار نقره:
...

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
                    "خبرهای مربوط به نرخ و قیمت دلار، ارزها، طلا و سکه را تولید نکن."
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
            "📰 خبر مهم بازار"
        )

    return (

        f"{header}\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🔸 {article['title']}\n\n"

        f"{article['text']}\n\n"

        "📌 چرا مهم است؟\n"
        f"{article.get('why', '')}\n\n"

        "🥈 ارتباط با بازار نقره\n"
        f"{article.get('silver', '')}"

        + channel_footer()

    )


# =========================================================
# NEWS POLL
# =========================================================

def make_news_poll_question(
    article
):

    return (
        "📊 برداشت شما از این خبر چیست؟"
    )


async def send_news_poll(
    client,
    target,
    article
):

    question = make_news_poll_question(
        article
    )

    poll = Poll(

        id=0,

        question=question,

        answers=[

            PollAnswer(
                text="🟢 مثبت",
                option=b"\x01"
            ),

            PollAnswer(
                text="🟡 خنثی",
                option=b"\x02"
            ),

            PollAnswer(
                text="🔴 منفی",
                option=b"\x03"
            )

        ],

        closed=False,

        public_voters=False,

        multiple_choice=False,

        quiz=False

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

            random_id=client.rng.getrandbits(
                64
            )

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
        ]

    )

    coin_bubble_text = format_price(
        abs(
            coin_bubble["bubble"]
        )
    )

    if coin_bubble["bubble"] > 0:

        coin_bubble_label = (
            f"🔴 حباب مثبت: {coin_bubble_text} تومان"
        )

    elif coin_bubble["bubble"] < 0:

        coin_bubble_label = (
            f"🟢 حباب منفی: {coin_bubble_text} تومان"
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

    if gold_ounce is not None:

        lines.extend([

            "",
            "🌍 انس طلا",
            f"💵 {gold_ounce:.2f} دلار",

        ])

    if gold_bubble is not None:

        if gold_bubble["bubble"] > 0:

            gold_bubble_text = (
                f"🔴 حباب مثبت: "
                f"{format_price(gold_bubble['bubble'])} تومان"
            )

        elif gold_bubble["bubble"] < 0:

            gold_bubble_text = (
                f"🟢 حباب منفی: "
                f"{format_price(abs(gold_bubble['bubble']))} تومان"
            )

        else:

            gold_bubble_text = (
                "⚪ حباب: بدون حباب"
            )

        lines.extend([

            "",
            f"🎈 حباب طلای ۱۸ عیار",
            gold_bubble_text,

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
    lines = [
        "📊 نبض بازار",
        "━━━━━━━━━━━━━━",
        f"📅 {iran_date_string()}",
        f"🕐 گزارش {pulse_label}",
        "",
        "💱 ارزهای مهم",
    ]

    currency_items = [
        (
            "💵 دلار",
            "dollar"
        ),
        (
            "💶 یورو",
            "euro"
        ),
        (
            "🇬🇧 پوند",
            "pound"
        ),
        (
            "🇦🇪 درهم امارات",
            "aed"
        ),
    ]

    for title, key in currency_items:
        item = data.get(key)

        lines.append(
            f"{title}: "
            f"{market_pulse_price_text(item)} تومان "
            f"{market_pulse_change_text(item.get('change_percent') if item else None)}"
        )

    lines.extend([
        "",
        "🌍 انس جهانی",
    ])

    for title, key, decimals in [
        (
            "🥇 انس طلا",
            "gold_ounce",
            2
        ),
        (
            "🥈 انس نقره",
            "silver_ounce",
            2
        ),
    ]:
        item = data.get(key)

        lines.append(
            f"{title}: "
            f"{market_pulse_price_text(item, decimals)} دلار "
            f"{market_pulse_change_text(item.get('change_percent') if item else None)}"
        )

    lines.extend([
        "",
        "🥇 طلا",
    ])

    gold_items = [
        (
            "طلای ۱۸ عیار",
            "gold_18"
        ),
        (
            "طلای ۲۴ عیار",
            "gold_24"
        ),
        (
            "طلای دست‌دوم",
            "gold_secondhand"
        ),
        (
            "مثقال طلا",
            "mesghal"
        ),
        (
            "آبشده نقدی",
            "melted_gold"
        ),
    ]

    for title, key in gold_items:
        item = data.get(key)

        lines.append(
            f"• {title}: "
            f"{market_pulse_price_text(item)} تومان "
            f"{market_pulse_change_text(item.get('change_percent') if item else None)}"
        )

    lines.extend([
        "",
        "🪙 سکه",
    ])

    coin_items = [
        (
            "سکه امامی (ضرب ۸۶)",
            "coin_imami",
            "bubble_imami"
        ),
        (
            "سکه بهار آزادی",
            "coin_bahar",
            "bubble_bahar"
        ),
        (
            "نیم‌سکه",
            "coin_half",
            "bubble_half"
        ),
        (
            "ربع‌سکه",
            "coin_quarter",
            "bubble_quarter"
        ),
        (
            "سکه گرمی",
            "coin_gram",
            "bubble_gram"
        ),
    ]

    for title, price_key, bubble_key in coin_items:
        price_item = data.get(
            price_key
        )

        bubble_item = data.get(
            bubble_key
        )

        price = (
            price_item.get("value")
            if price_item
            else None
        )

        bubble = (
            bubble_item.get("value")
            if bubble_item
            else None
        )

        bubble_percent = (
            market_pulse_bubble_percent(
                price,
                bubble
            )
        )

        bubble_text = "—"

        if bubble is not None:
            bubble_text = (
                f"{format_price(abs(bubble))} تومان"
            )

            if bubble < 0:
                bubble_text = (
                    f"-{bubble_text}"
                )
            elif bubble > 0:
                bubble_text = (
                    f"+{bubble_text}"
                )

        bubble_percent_text = "—"

        if bubble_percent is not None:
            bubble_percent_text = (
                f"{bubble_percent:.2f}٪"
            )

        change_percent = (
            price_item.get(
                "change_percent"
            )
            if price_item
            else None
        )

        lines.append(
            f"• {title}: "
            f"{market_pulse_price_text(price_item)} تومان "
            f"{market_pulse_change_text(change_percent)}"
        )

        lines.append(
            f"  حباب: {bubble_text} "
            f"| حباب٪: {bubble_percent_text}"
        )

    if previous_snapshot:
        intraday_items = [
            (
                "دلار",
                "dollar"
            ),
            (
                "طلای ۱۸",
                "gold_18"
            ),
            (
                "انس نقره",
                "silver_ounce"
            ),
            (
                "سکه امامی",
                "coin_imami"
            ),
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
                or
                previous_value is None
                or
                previous_value == 0
            ):
                continue

            delta_percent = (
                (
                    current_value
                    -
                    previous_value
                )
                /
                previous_value
                *
                100
            )

            intraday_lines.append(
                f"• {title}: "
                f"{market_pulse_change_text(delta_percent)}"
            )

        if intraday_lines:
            lines.extend([
                "",
                "⏱ تغییر از ۱۲:۰۰ تا ۲۰:۳۰",
            ])

            lines.extend(
                intraday_lines
            )

    direction_values = []

    for key in (
        "dollar",
        "gold_18",
        "silver_ounce",
        "coin_imami",
    ):
        item = data.get(key)

        if (
            item
            and
            item.get(
                "change_percent"
            ) is not None
        ):
            direction_values.append(
                item["change_percent"]
            )

    if direction_values:
        average_change = (
            sum(direction_values)
            /
            len(direction_values)
        )

        if average_change > 0.30:
            direction = "📈 صعودی"
        elif average_change < -0.30:
            direction = "📉 نزولی"
        else:
            direction = "➡️ متعادل"
    else:
        direction = "—"

    lines.extend([
        "",
        f"📌 نبض کلی بازار: {direction}",
        "",
        "ℹ️ درصد تغییرات، نسبت به نرخ روز قبل است.",
        "ℹ️ حباب سکه از اختلاف قیمت بازار و ارزش ذاتی محاسبه می‌شود.",
        "",
        channel_footer()
    ])

    return "\n".join(
        lines
    )


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
    yahoo_data
):

    snapshot = {
        "silver": {
            "current":
                (
                    float(rate["ounce"])
                    if rate
                    else None
                )
        },

        "gold": {
            "current":
                (
                    float(gold_ounce)
                    if gold_ounce is not None
                    else None
                )
        },

        "tehran_dollar": {
            "current":
                (
                    float(rate["tehran"])
                    if rate
                    else None
                )
        },

        "shot_995": {
            "current":
                (
                    float(products["shot_995"])
                    if products
                    else None
                )
        }
    }

    # انس نقره و طلا
    for key in (
        "silver",
        "gold"
    ):

        rows = yahoo_data.get(
            key,
            []
        )

        current = (
            snapshot[key]["current"]
            or
            latest_market_value(rows)
        )

        if current is not None:

            snapshot[key]["current"] = current

        snapshot[key][
            "levels"
        ] = nearest_support_resistance(
            rows,
            current
        )

    # دلار تهران از تاریخچه خود ربات.
    dollar_current = (
        snapshot[
            "tehran_dollar"
        ]["current"]
    )

    snapshot[
        "tehran_dollar"
    ]["levels"] = local_levels_from_history(
        state,
        "tehran",
        dollar_current
    )

    # ساچمه نیز از تاریخچه خود ربات.
    shot_current = (
        snapshot[
            "shot_995"
        ]["current"]
    )

    snapshot[
        "shot_995"
    ]["levels"] = local_levels_from_history(
        state,
        "shot_995",
        shot_current
    )

    # عوامل کلان اثرگذار بر نقره.
    for key in (
        "dxy",
        "oil",
        "us10y",
        "sp500",
        "vix"
    ):

        rows = yahoo_data.get(
            key,
            []
        )

        current = latest_market_value(
            rows
        )

        previous = None

        if len(rows) >= 2:

            previous = (
                rows[-2].get(
                    "close"
                )
            )

        snapshot[key] = {
            "current": current,
            "daily_change_percent":
                percent_change(
                    current,
                    previous
                )
        }

    silver_current = (
        snapshot["silver"]["current"]
    )

    gold_current = (
        snapshot["gold"]["current"]
    )

    if (
        silver_current
        and
        gold_current
        and
        silver_current > 0
    ):

        snapshot[
            "gold_silver_ratio"
        ] = (
            gold_current
            /
            silver_current
        )

    else:

        snapshot[
            "gold_silver_ratio"
        ] = None

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

    silver = snapshot.get(
        "silver",
        {}
    )

    gold = snapshot.get(
        "gold",
        {}
    )

    dollar = snapshot.get(
        "tehran_dollar",
        {}
    )

    ratio = snapshot.get(
        "gold_silver_ratio"
    )

    dxy = snapshot.get(
        "dxy",
        {}
    )

    us10y = snapshot.get(
        "us10y",
        {}
    )

    oil = snapshot.get(
        "oil",
        {}
    )

    silver_levels = silver.get(
        "levels",
        {}
    )

    gold_levels = gold.get(
        "levels",
        {}
    )

    dollar_levels = dollar.get(
        "levels",
        {}
    )

    silver_current = silver.get(
        "current"
    )

    dxy_change = dxy.get(
        "daily_change_percent"
    )

    us10y_change = us10y.get(
        "daily_change_percent"
    )

    oil_change = oil.get(
        "daily_change_percent"
    )

    if (
        silver_current is not None
        and
        silver_levels.get("support")
        is not None
        and
        silver_current
        > silver_levels["support"]
    ):

        silver_view = (
            "نقره بالاتر از حمایت نزدیک خود قرار دارد؛ "
            "حفظ این محدوده برای ادامه حرکت مثبت مهم است."
        )

    else:

        silver_view = (
            "نقره نزدیک محدوده‌های حمایتی قرار دارد؛ "
            "شکست حمایت نزدیک می‌تواند فشار فروش را بیشتر کند."
        )

    dxy_view = (
        "افت شاخص دلار در مجموع به نفع فلزات گرانبهاست."
        if (
            dxy_change is not None
            and dxy_change < 0
        )
        else
        "قدرت دلار می‌تواند در کوتاه‌مدت برای فلزات گرانبها مانع ایجاد کند."
    )

    rates_view = (
        "افزایش بازدهی اوراق آمریکا معمولاً فشار کوتاه‌مدت بر فلزات بدون سود ایجاد می‌کند."
        if (
            us10y_change is not None
            and us10y_change > 0
        )
        else
        "افت یا ثبات بازدهی اوراق آمریکا می‌تواند فضای بهتری برای فلزات ایجاد کند."
    )

    return (
        "📊 تحلیل دوره‌ای بازار\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🥈 انس نقره: "
        f"{format_level(silver_current)} دلار\n"
        f"حمایت: "
        f"{format_level(silver_levels.get('support'))} | "
        f"مقاومت: "
        f"{format_level(silver_levels.get('resistance'))}\n\n"

        f"🥇 انس طلا: "
        f"{format_level(gold.get('current'))} دلار\n"
        f"حمایت: "
        f"{format_level(gold_levels.get('support'))} | "
        f"مقاومت: "
        f"{format_level(gold_levels.get('resistance'))}\n\n"

        f"💵 دلار تهران: "
        f"{format_level(dollar.get('current'), 0)} تومان\n"
        f"حمایت: "
        f"{format_level(dollar_levels.get('support'), 0)} | "
        f"مقاومت: "
        f"{format_level(dollar_levels.get('resistance'), 0)}\n\n"

        f"📐 نسبت طلا به نقره: "
        f"{format_level(ratio)}\n\n"

        f"🌐 DXY: "
        f"{format_level(dxy.get('current'))} | "
        f"نفت: {format_level(oil.get('current'))}\n"
        f"📈 بازدهی ۱۰ساله آمریکا: "
        f"{format_level(us10y.get('current'))}٪\n\n"

        f"{silver_view}\n"
        f"{dxy_view}\n"
        f"{rates_view}\n\n"

        "🔎 جمع‌بندی: برای نقره، هم‌زمانی ضعف دلار "
        "و افت بازدهی اوراق معمولاً فضای مساعدتری ایجاد می‌کند؛ "
        "در مقابل، تقویت دلار و جهش بازدهی می‌تواند فشار ایجاد کند."
    )


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
برای کانال «یزدان‌دوست» یک تحلیل حرفه‌ای و قابل فهم
از بازار طلا و نقره بنویس.

این تحلیل قرار است هر دو روز یک‌بار ساعت ۲۲ منتشر شود.

داده‌های بازار:
{json.dumps(snapshot, ensure_ascii=False, indent=2)}

الزام‌ها:
- حمایت و مقاومت انس طلا و انس نقره را مشخص کن.
- حمایت و مقاومت دلار تهران را اگر داده کافی وجود دارد مشخص کن.
- توضیح بده DXY، بازدهی اوراق ۱۰ ساله آمریکا، نفت،
  شاخص S&P500، VIX و نسبت طلا به نقره چه اثری می‌توانند
  بر نقره داشته باشند.
- بگو وضعیت فعلی برای نقره بیشتر «مثبت»، «منفی» یا «خنثی» است
  و دلیلش را کوتاه توضیح بده.
- تحلیل احتمالی است؛ پیش‌بینی قطعی و توصیه خرید/فروش نده.
- اعداد حمایت و مقاومت را دقیقاً از داده‌های ورودی بگیر
  و عدد جدید اختراع نکن.
- اگر داده‌ای وجود ندارد، صریحاً بنویس «داده کافی نداریم».
- 180 تا 260 کلمه.
- فارسی روان و حرفه‌ای.
- بدون Markdown و بدون هشتگ.
- عنوان مناسب داشته باشد.
- در پایان یک جمع‌بندی کوتاه با تمرکز روی اثر بازار بر نقره بده.
"""

    try:

        response = client.responses.create(

            model=OPENAI_MODEL,

            instructions=(
                "تو تحلیلگر محافظه‌کار بازار فلزات گرانبها هستی. "
                "فقط از داده‌های ارائه‌شده استفاده کن."
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
    # تحلیل دو-روزه ۲۲:۰۰ در جمعه تکراری است.
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
{json.dumps(snapshot, ensure_ascii=False, indent=2)}

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

    message_id = await send_rate_post(
        client,
        target,
        image,
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
در پایان یک سؤال تعاملی کوتاه قرار بده.
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

    poll = Poll(
        id=0,
        question="📊 پیش‌بینی بازار نقره | امروز",
        answers=[
            PollAnswer(
                text="🟢 صعودی",
                option=b"\x01"
            ),
            PollAnswer(
                text="🔴 کاهشی",
                option=b"\x02"
            ),
            PollAnswer(
                text="🟡 کم‌نوسان",
                option=b"\x03"
            )
        ],
        closed=False,
        public_voters=False,
        multiple_choice=False,
        quiz=False
    )

    media = InputMediaPoll(
        poll=poll
    )

    sent = await client(
        SendMediaRequest(
            peer=target,
            media=media,
            message=(
                "🔮 به نظر شما روند بازار نقره "
                "امروز چگونه خواهد بود؟\n\n"
                "قبل از شروع معاملات، "
                "پیش‌بینی خودت را ثبت کن 👇"
            ),
            random_id=client.rng.getrandbits(64)
        )
    )

    log.info(
        "MARKET POLL SENT | %s",
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


async def send_news_post(
    client,
    target,
    article
):

    if not article:

        return None, None

    if is_blocked_rate_gold_news(
        article
    ):

        log.warning(
            "NEWS SEND BLOCKED | RATE/GOLD/CURRENCY TOPIC | %s",
            article.get(
                "title",
                ""
            )
        )

        return None, None

    caption = make_news_caption(
        article
    )

    if len(caption) >= 4000:

        log.error(
            "NEWS CAPTION TOO LONG -> NOT SENT"
        )

        return None, None

    news_message_id = await send_text_post(
        client,
        target,
        caption
    )

    poll_message_id = None

    try:

        poll_message_id = (
            await send_news_poll(
                client,
                target,
                article
            )
        )

    except Exception as error:

        log.exception(
            "NEWS POLL FAILED: %s",
            error
        )

    return (
        news_message_id,
        poll_message_id
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
        # CALENDAR
        # =================================================

        if (

            current_minute
            >=
            CALENDAR_HOUR * 60
            + CALENDAR_MINUTE

            and

            current_minute
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
        # 09:45 DAILY MARKET POLL
        # =================================================

        if (

            not is_market_holiday()

            and

            current_minutes()
            >=
            9 * 60
            + 45

            and

            current_minutes()
            <
            10 * 60

            and

            should_send_daily(
                state,
                "market_poll"
            )

        ):

            try:

                poll_message_id = (
                    await send_market_poll(
                        client,
                        target
                    )
                )

                if poll_message_id:

                    mark_daily_sent(
                        state,
                        "market_poll"
                    )

                    save_state(
                        state
                    )

                    log.info(
                        "DAILY MARKET POLL SENT SUCCESSFULLY"
                    )

            except Exception as error:

                log.exception(
                    "DAILY MARKET POLL FAILED: %s",
                    error
                )

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

                message_id = await send_sticker(

                    client,
                    target,
                    START_STICKER

                )

                await send_rubika_text(

                    "🟢 شروع معاملات\n"
                    "━━━━━━━━━━━━━━\n"
                    "معاملات نقره یزدان‌دوست آغاز شد."

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

            if (

                start_minute
                <=
                current_minute
                <
                start_minute + 20

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

            news_article = None
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

            if news_article:

                if is_blocked_rate_gold_news(
                    news_article
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

                        if is_blocked_rate_gold_news(
                            ai_article
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

                        await send_text_post(

                            client,
                            target,
                            tomorrow_text

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

            current_minute
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

                await send_rubika_text(

                    "🔴 پایان معاملات\n"
                    "━━━━━━━━━━━━━━\n"
                    "معاملات نقره یزدان‌دوست پایان یافت."

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

                daily_products = products

                if daily_products is None:
                    daily_products = get_saved_products(
                        state
                    )

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

                    yahoo_data = (
                        await get_yahoo_market_data()
                    )

                    snapshot = (
                        build_market_analysis_snapshot(
                            state,
                            analysis_rate,
                            analysis_products,
                            analysis_gold_ounce,
                            yahoo_data
                        )
                    )

                    analysis = await ai_market_analysis(
                        snapshot
                    )

                    if analysis:

                        analysis_text = (
                            analysis
                            +
                            "\n\n"
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
