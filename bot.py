import os
import math
import sqlite3
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

TZ = ZoneInfo("Asia/Tehran")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_USER_ID = int(os.environ["ADMIN_USER_ID"])
CHANNEL_ID = os.environ["CHANNEL_ID"]

METALPRICE_API_KEY = os.getenv("METALPRICE_API_KEY", "")
IRAN_FX_API_KEY = os.getenv("IRAN_FX_API_KEY", "")
NEWS_API_TOKEN = os.getenv("NEWS_API_TOKEN", "")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")
DB = os.getenv("DB_PATH", "yazdandoust.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("yazdandoust")


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS ticks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            ounce REAL,
            dollar REAL,
            premium REAL,
            theoretical REAL,
            published_price INTEGER,
            published INTEGER NOT NULL DEFAULT 0
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS daily (
            date TEXT PRIMARY KEY,
            start_price INTEGER,
            high_price INTEGER,
            low_price INTEGER,
            last_price INTEGER,
            message_id INTEGER
        )
    """)
    con.commit()
    con.close()


def get_setting(k, default=None):
    con = db()
    row = con.execute(
        "SELECT value FROM settings WHERE key=?",
        (k,),
    ).fetchone()
    con.close()
    return row["value"] if row else default


def set_setting(k, v):
    con = db()
    con.execute(
        """
        INSERT INTO settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
        """,
        (k, str(v)),
    )
    con.commit()
    con.close()


def fmt(n):
    return f"{int(round(float(n))):,}".replace(",", "Ù¬")


def round_5000(x):
    return int(math.floor((float(x) + 2500) / 5000) * 5000)


def session_open():
    now = datetime.now(TZ).time()
    return time(11, 0) <= now < time(21, 0)


def current_inputs():
    ounce = get_setting("ounce")
    dollar = get_setting("dollar")
    premium = float(get_setting("premium", "0"))
    return (
        float(ounce) if ounce is not None else None,
        float(dollar) if dollar is not None else None,
        premium,
    )


def theoretical_995(ounce, dollar):
    return (ounce * dollar / 31.1034768) * 0.995


def calculate_price(ounce, dollar, premium):
    return round_5000(theoretical_995(ounce, dollar) + premium)


def fetch_silver_ounce():
    if not METALPRICE_API_KEY:
        return None

    response = requests.get(
        "https://api.metalpriceapi.com/v1/latest",
        params={
            "api_key": METALPRICE_API_KEY,
            "base": "USD",
            "currencies": "XAG",
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    if not data.get("success"):
        raise ValueError(f"MetalpriceAPI error: {data}")

    rate = data.get("rates", {}).get("XAG")
    if rate is None:
        raise ValueError(f"XAG rate missing: {data}")

    return 1.0 / float(rate)


def fetch_iran_dollar_toman():
    if not IRAN_FX_API_KEY:
        return None

    response = requests.post(
        "https://api.apidevelopers.ir/v1/exchange-rates",
        json={"apiKey": IRAN_FX_API_KEY},
        timeout=15,
    )
    response.raise_for_status()

    data = response.json()
    usd = data.get("result", {}).get("usd")

    if not usd:
        raise ValueError("Ù¾Ø§Ø³Ø® Ø³Ø±ÙÛØ³ Ø¯ÙØ§Ø± Ø´Ø§ÙÙ usd ÙÛØ³Øª.")

    value = usd.get("sell") or usd.get("buy")
    if value is None:
        raise ValueError("ÙÛÙØª Ø®Ø±ÛØ¯/ÙØ±ÙØ´ Ø¯ÙØ§Ø± Ø¯Ø± Ù¾Ø§Ø³Ø® Ø³Ø±ÙÛØ³ ÙØ¬ÙØ¯ ÙØ¯Ø§Ø±Ø¯.")

    unit = str(usd.get("currency", "irt")).lower()
    value = float(value)
    return value / 10 if unit == "irt" else value


def daily_row():
    d = datetime.now(TZ).date().isoformat()
    con = db()
    row = con.execute(
        "SELECT * FROM daily WHERE date=?",
        (d,),
    ).fetchone()
    con.close()
    return row


def update_daily(price, message_id=None):
    d = datetime.now(TZ).date().isoformat()
    con = db()
    row = con.execute(
        "SELECT * FROM daily WHERE date=?",
        (d,),
    ).fetchone()

    if row is None:
        con.execute(
            """
            INSERT INTO daily(
                date,start_price,high_price,low_price,last_price,message_id
            )
            VALUES(?,?,?,?,?,?)
            """,
            (d, price, price, price, price, message_id),
        )
    else:
        con.execute(
            """
            UPDATE daily SET
                high_price=MAX(high_price, ?),
                low_price=MIN(low_price, ?),
                last_price=?,
                message_id=COALESCE(?, message_id)
            WHERE date=?
            """,
            (price, price, price, message_id, d),
        )

    con.commit()
    con.close()


def rate_message(ounce, dollar, premium, price, stamp):
    return (
        "ð¥ <b>ÙØ±Ø® ÙØ­Ø¸ÙâØ§Û ÙÙØ±Ù | ÛØ²Ø¯Ø§ÙâØ¯ÙØ³Øª</b>\n\n"
        "âª <b>Ø³Ø§ÚÙÙ ÙÙØ±Ù Û¹Û¹Ûµ</b>\n"
        f"<b>{fmt(price)} ØªÙÙØ§Ù / Ú¯Ø±Ù</b>\n\n"
        f"ð Ø§ÙØ³ ÙÙØ±Ù: <b>{ounce:.2f} $</b>\n"
        f"ðµ Ø¯ÙØ§Ø± Ø¢Ø²Ø§Ø¯: <b>{fmt(dollar)} ØªÙÙØ§Ù</b>\n"
        f"ð Ù¾Ø±ÙÛÙÙ Ø¨Ø§Ø²Ø§Ø±: <b>{fmt(premium)} ØªÙÙØ§Ù</b>\n\n"
        f"ð Ø¢Ø®Ø±ÛÙ Ø¨Ø±ÙØ²Ø±Ø³Ø§ÙÛ: <b>{stamp}</b>\n\n"
        "<b>YAZDANDOUST SILVER</b>\n"
        "Ø¯ÙÛÙ â¢ Ø³Ø±ÛØ¹ â¢ ÙØ·ÙØ¦Ù"
    )


def admin_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ð Ø§ÙØ³ Ø¯Ø³ØªÛ", callback_data="help_ounce"),
            InlineKeyboardButton("ðµ Ø¯ÙØ§Ø± Ø¯Ø³ØªÛ", callback_data="help_dollar"),
        ],
        [InlineKeyboardButton("ð Ù¾Ø±ÙÛÙÙ", callback_data="help_premium")],
        [InlineKeyboardButton("ð¤ Ø¯Ø±ÛØ§ÙØª Ø®ÙØ¯Ú©Ø§Ø±", callback_data="auto")],
        [
            InlineKeyboardButton("ð§® ÙØ­Ø§Ø³Ø¨Ù", callback_data="calc"),
            InlineKeyboardButton("ð¢ Ø§ÙØªØ´Ø§Ø±", callback_data="publish"),
        ],
        [InlineKeyboardButton("ð ÙØ¶Ø¹ÛØª Ø§ÙØ±ÙØ²", callback_data="status")],
    ])


def admin(update):
    return bool(
        update.effective_user
        and update.effective_user.id == ADMIN_USER_ID
    )


async def start(update, context):
    if not admin(update):
        await update.message.reply_text("Ø§ÛÙ Ø±Ø¨Ø§Øª Ø®ØµÙØµÛ Ø§Ø³Øª.")
        return

    await update.message.reply_text(
        "âï¸ <b>Ù¾ÙÙ ÙØ¯ÛØ±ÛØª ÛØ²Ø¯Ø§ÙâØ¯ÙØ³Øª</b>\n\n"
        "ÙÛÙØª ÙÙØ§ÛÛ = ÙÛÙØª ØªØ¦ÙØ±ÛÚ© Û¹Û¹Ûµ + Ù¾Ø±ÙÛÙÙ Ø¯Ø³ØªÛ\n"
        "Ø§ÙØªØ´Ø§Ø± ÙÙØ· Ø¯Ø± Ø¨Ø§Ø²Ù Û±Û± ØªØ§ Û²Û± Ù Ø¯Ø± ØªØºÛÛØ±Ø§Øª ÛµÙ¬Û°Û°Û° ØªÙÙØ§ÙÛ Ø§ÙØ¬Ø§Ù ÙÛâØ´ÙØ¯.",
        parse_mode="HTML",
        reply_markup=admin_kb(),
    )


async def myid(update, context):
    await update.message.reply_text(
        f"Telegram User ID: {update.effective_user.id}"
    )


async def setounce(update, context):
    if not admin(update):
        return
    try:
        v = float(context.args[0])
        set_setting("ounce", v)
        await update.message.reply_text(f"â Ø§ÙØ³ Ø°Ø®ÛØ±Ù Ø´Ø¯: {v:.2f}")
    except (IndexError, ValueError):
        await update.message.reply_text("ÙØ±ÙØª: /setounce 63.45")


async def setdollar(update, context):
    if not admin(update):
        return
    try:
        v = float(context.args[0])
        set_setting("dollar", v)
        await update.message.reply_text(
            f"â Ø¯ÙØ§Ø± Ø°Ø®ÛØ±Ù Ø´Ø¯: {fmt(v)} ØªÙÙØ§Ù"
        )
    except (IndexError, ValueError):
        await update.message.reply_text("ÙØ±ÙØª: /setdollar 186000")


async def setpremium(update, context):
    if not admin(update):
        return
    try:
        v = float(context.args[0])
        set_setting("premium", v)
        await update.message.reply_text(
            f"â Ù¾Ø±ÙÛÙÙ Ø°Ø®ÛØ±Ù Ø´Ø¯: {fmt(v)} ØªÙÙØ§Ù"
        )
    except (IndexError, ValueError):
        await update.message.reply_text("ÙØ±ÙØª: /setpremium 12500")


async def calc(update, context):
    if not admin(update):
        return

    ounce, dollar, premium = current_inputs()

    if ounce is None or dollar is None:
        await update.effective_message.reply_text(
            "â ÙÙÙØ² Ø§ÙØ³ Ù Ø¯ÙØ§Ø± ÙØ´Ø®Øµ ÙÛØ³Øª."
        )
        return

    t = theoretical_995(ounce, dollar)
    p = calculate_price(ounce, dollar, premium)

    await update.effective_message.reply_text(
        f"ð§® ØªØ¦ÙØ±ÛÚ© Û¹Û¹Ûµ: <b>{fmt(t)} ØªÙÙØ§Ù</b>\n"
        f"ð Ù¾Ø±ÙÛÙÙ: <b>{fmt(premium)}</b>\n"
        f"ð¥ ÙØ±Ø® ÙØ§Ø¨Ù Ø§ÙØªØ´Ø§Ø±: <b>{fmt(p)} ØªÙÙØ§Ù</b>",
        parse_mode="HTML",
    )


async def publish_if_needed(context, force=False):
    if not session_open() and not force:
        return

    ounce, dollar, premium = current_inputs()
    if ounce is None or dollar is None:
        return

    price = calculate_price(ounce, dollar, premium)
    last = get_setting("last_published")

    if not force and last is not None and abs(price - int(last)) < 5000:
        con = db()
        con.execute(
            """
            INSERT INTO ticks(
                ts,ounce,dollar,premium,theoretical,published_price,published
            )
            VALUES(?,?,?,?,?,?,0)
            """,
            (
                datetime.now(TZ).isoformat(),
                ounce,
                dollar,
                premium,
                theoretical_995(ounce, dollar),
                int(last),
            ),
        )
        con.commit()
        con.close()
        return

    stamp = datetime.now(TZ).strftime("%H:%M")
    text = rate_message(ounce, dollar, premium, price, stamp)
    msg_id = get_setting("rate_message_id")

    if msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=int(msg_id),
                text=text,
                parse_mode="HTML",
            )
        except Exception as e:
            log.warning("Could not edit rate message: %s", e)
            msg = await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=text,
                parse_mode="HTML",
            )
            msg_id = msg.message_id
            set_setting("rate_message_id", msg_id)
    else:
        msg = await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            parse_mode="HTML",
        )
        msg_id = msg.message_id
        set_setting("rate_message_id", msg_id)

    set_setting("last_published", price)
    update_daily(price, int(msg_id))

    con = db()
    con.execute(
        """
        INSERT INTO ticks(
            ts,ounce,dollar,premium,theoretical,published_price,published
        )
        VALUES(?,?,?,?,?,?,1)
        """,
        (
            datetime.now(TZ).isoformat(),
            ounce,
            dollar,
            premium,
            theoretical_995(ounce, dollar),
            price,
        ),
    )
    con.commit()
    con.close()


def translate_to_farsi(text):
    if not text:
        return ""

    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "en",
                "tl": "fa",
                "dt": "t",
                "q": text,
            },
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        return "".join(
            item[0] for item in data[0] if item and item[0]
        )

    except Exception as e:
        log.warning("Translation failed: %s", e)
        return text


async def silver_news_update(context):
    if not GNEWS_API_KEY:
        log.warning(
            "GNEWS_API_KEY is not set; silver news update skipped."
        )
        return

    try:
        response = requests.get(
            "https://gnews.io/api/v4/search",
            params={
                "q": (
                    '"silver" OR "silver price" OR "silver market" '
                    'OR "silver demand" OR "silver supply" '
                    'OR "silver mining" OR "silver production"'
                ),
                "lang": "en",
                "max": 10,
                "sortby": "publishedAt",
                "apikey": GNEWS_API_KEY,
            },
            timeout=20,
        )

        response.raise_for_status()
        data = response.json()

        log.info(
            "GNEWS TEST: status=%s articles=%s",
            response.status_code,
            len(data.get("articles", [])),
        )

        articles = data.get("articles", [])

        if not articles:
            log.info("No new silver news found")
            return

        for article in articles:
            title = str(article.get("title", "")).strip()
            description = str(
                article.get("description", "")
            ).strip()

            if not title:
                continue

            title_fa = translate_to_farsi(title)
            description_fa = (
                translate_to_farsi(description)
                if description
                else ""
            )

            url = str(article.get("url", "")).strip()
            source_data = article.get("source", {})
            source = str(
                source_data.get("name", "Unknown")
            ).strip()

            if not url:
                continue

            news_key = f"silver_{url}"
            last_news = get_setting("last_silver_news")

            if last_news == news_key:
                continue

            message = (
                "ð¥ <b>Ø§Ø®Ø¨Ø§Ø± Ø¬ÙØ§ÙÛ ÙÙØ±Ù</b>\n\n"
                f"ð° <b>{title_fa}</b>\n\n"
            )

            if description_fa:
                message += f"{description_fa}\n\n"

            message += f"ð ÙÙØ¨Ø¹: {source}\n"
            message += (
                f'ð <a href="{url}">ÙØ´Ø§ÙØ¯Ù Ø®Ø¨Ø± Ø§ØµÙÛ</a>\n\n'
            )
            message += "ââââââââââââââ\n"
            message += "ð¥ <b>Yazdandoust Silver</b>"

            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )

            set_setting("last_silver_news", news_key)
            log.info("Silver news sent: %s", title)
            break

    except Exception as e:
        log.exception("Silver news update failed: %s", e)


async def news_update(context):
    if not NEWS_API_TOKEN:
        return

    try:
        response = requests.get(
            "https://api.majidapi.ir/akhbar-dagh",
            params={
                "action": "latest",
                "token": NEWS_API_TOKEN,
            },
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()

        if not isinstance(items, list):
            log.warning("News API returned unexpected data")
            return

        keywords = [
            "Ø§ÛØ±Ø§Ù", "Ø§Ø³Ø±Ø§Ø¦ÛÙ", "Ø¢ÙØ±ÛÚ©Ø§", "Ø¬ÙÚ¯", "Ø­ÙÙÙ",
            "ÙÙØ´Ú©", "Ø¨ÙØ¨Ø§Ø±Ø§Ù", "Ø³ÙØªÚ©Ø§Ù", "Ø§Ø±ØªØ´", "Ø³Ù¾Ø§Ù",
            "Ø¢ØªØ´âØ¨Ø³", "Ø¯Ø±Ú¯ÛØ±Û", "Ù¾ÙÙ¾Ø§Ø¯", "ÙØ°Ø§Ú©Ø±Ø§Øª",
            "ÙØ¨ÙØ§Ù", "ØºØ²Ù", "Ø³ÙØ±ÛÙ", "Ø¹Ø±Ø§Ù", "ÙÙØ³Ø·ÛÙ",
            "ÙØ³ØªÙâØ§Û", "ØªØ£Ø³ÛØ³Ø§Øª", "Ø­ÙÙÙ ÙÙØ§ÛÛ", "Ø¹ÙÙÛØ§Øª",
            "Ú©Ø´ØªÙ", "Ø§ÙÙØ¬Ø§Ø±", "Ù¾Ø¯Ø§ÙÙØ¯", "ØªØ±ÙØ±", "ØªØ­Ø±ÛÙ",
        ]

        relevant_news = []

        for item in items:
            if not isinstance(item, dict):
                continue

            title = str(item.get("title", "")).strip()
            if not title:
                continue

            title_lower = title.lower()

            if any(
                keyword in title_lower
                for keyword in keywords
            ):
                relevant_news.append(item)

        if not relevant_news:
            log.info("No relevant news found")
            return

        relevant_news.sort(
            key=lambda x: (
                bool(x.get("special", False)),
                x.get("id", 0),
            ),
            reverse=True,
        )

        news = relevant_news[0]
        news_id = str(news.get("id", ""))

        if not news_id:
            return

        last_news_id = get_setting("last_news_id")
        if str(last_news_id) == news_id:
            return

        title = str(news.get("title", "")).strip()
        source = str(news.get("source", "")).strip()
        date = str(news.get("date", "")).strip()
        special = bool(news.get("special", False))

        header = (
            "ð¨ <b>Ø®Ø¨Ø± ÙÙØ±Û</b>"
            if special
            else "ð° <b>Ø®Ø¨Ø± Ø¬Ø¯ÛØ¯</b>"
        )

        text = f"{header}\n\n"
        text += f"ð´ <b>{title}</b>\n\n"

        if source:
            text += f"ð ÙÙØ¨Ø¹: {source}\n"

        if date:
            text += f"ð Ø²ÙØ§Ù: {date}\n"

        text += "\nââââââââââââââ\n"
        text += "ð¡ <b>Ø³Ø§ÚÙÙ ÙÙØ±Ù ÛØ²Ø¯Ø§Ù Ø¯ÙØ³Øª</b>"

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            parse_mode="HTML",
        )

        set_setting("last_news_id", news_id)
        log.info("News sent: %s", title)

    except Exception as e:
        log.exception("News update failed: %s", e)


async def manual_publish(update, context):
    if not admin(update):
        return

    if not session_open():
        await update.effective_message.reply_text(
            "â° Ø®Ø§Ø±Ø¬ Ø§Ø² Ø³Ø§Ø¹Øª ÙØ±Ø®âØ¯ÙÛ Û±Û± ØªØ§ Û²Û± ÙØ³ØªÛÙ."
        )
        return

    before = get_setting("last_published")
    await publish_if_needed(context)
    after = get_setting("last_published")

    if after == before:
        await update.effective_message.reply_text(
            "â¹ï¸ ØªØºÛÛØ± Ú©ÙØªØ± Ø§Ø² ÛµÙ¬Û°Û°Û° ØªÙÙØ§Ù Ø¨ÙØ¯Ø "
            "ÙØ±Ø® Ú©Ø§ÙØ§Ù ØªØºÛÛØ± ÙÚ©Ø±Ø¯."
        )
    else:
        await update.effective_message.reply_text(
            f"â ÙØ±Ø® Ú©Ø§ÙØ§Ù Ø¨Ù {fmt(after)} ØªÙÙØ§Ù "
            "Ø¨Ø±ÙØ²Ø±Ø³Ø§ÙÛ Ø´Ø¯."
        )


async def status(update, context):
    if not admin(update):
        return

    row = daily_row()

    if not row:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="ð Ø§ÙØ±ÙØ² ÙÙÙØ² ÙØ±Ø® Ø±Ø³ÙÛ Ø«Ø¨Øª ÙØ´Ø¯Ù.",
        )
        return

    await update.effective_message.reply_text(
        "ð <b>ÙØ¶Ø¹ÛØª Ø§ÙØ±ÙØ²</b>\n\n"
        f"ðº Ø¨ÛØ´ØªØ±ÛÙ: {fmt(row['high_price'])}\n"
        f"ð» Ú©ÙØªØ±ÛÙ: {fmt(row['low_price'])}\n"
        f"ð¹ Ø¢Ø®Ø±ÛÙ: {fmt(row['last_price'])}\n"
        f"ð Ø´Ø±ÙØ¹: {fmt(row['start_price'])}",
        parse_mode="HTML",
    )


async def close_day(context):
    row = daily_row()
    if not row:
        return

    change = row["last_price"] - row["start_price"]
    sign = "+" if change > 0 else ""

    text = (
        "ð <b>Ú¯Ø²Ø§Ø±Ø´ Ù¾Ø§ÛØ§Ù ÙØ¹Ø§ÙÙØ§Øª ÙÙØ±Ù | ÛØ²Ø¯Ø§ÙâØ¯ÙØ³Øª</b>\n\n"
        "ð¥ Ø³Ø§ÚÙÙ ÙÙØ±Ù Û¹Û¹Ûµ\n\n"
        f"ðº Ø¨ÛØ´ØªØ±ÛÙ ÙØ±Ø®: <b>{fmt(row['high_price'])} ØªÙÙØ§Ù</b>\n"
        f"ð» Ú©ÙØªØ±ÛÙ ÙØ±Ø®: <b>{fmt(row['low_price'])} ØªÙÙØ§Ù</b>\n"
        f"ð¹ Ø¢Ø®Ø±ÛÙ ÙØ±Ø®: <b>{fmt(row['last_price'])} ØªÙÙØ§Ù</b>\n"
        f"ð ØªØºÛÛØ± ÙØ³Ø¨Øª Ø¨Ù Ø´Ø±ÙØ¹: "
        f"<b>{sign}{fmt(abs(change))} ØªÙÙØ§Ù</b>\n\n"
        "ð Ù¾Ø§ÛØ§Ù ÙØ¹Ø§ÙÙØ§Øª: Û²Û±:Û°Û°\n\n"
        "<b>YAZDANDOUST SILVER</b>\n"
        "Ø¯ÙÛÙ â¢ Ø³Ø±ÛØ¹ â¢ ÙØ·ÙØ¦Ù"
    )

    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=text,
        parse_mode="HTML",
    )


async def button(update, context):
    q = update.callback_query
    await q.answer()

    if not admin(update):
        return

    if q.data == "help_ounce":
        await q.message.reply_text(
            "Ø¨Ø±Ø§Û ÙØ±ÙØ¯ Ø¯Ø³ØªÛ Ø§ÙØ³:\n/setounce 63.45"
        )
    elif q.data == "help_dollar":
        await q.message.reply_text(
            "Ø¨Ø±Ø§Û ÙØ±ÙØ¯ Ø¯Ø³ØªÛ Ø¯ÙØ§Ø±:\n/setdollar 186000"
        )
    elif q.data == "help_premium":
        await q.message.reply_text(
            "Ù¾Ø±ÙÛÙÙ Ø±Ø§ Ø¨Ù ØªÙÙØ§Ù ÙØ§Ø±Ø¯ Ú©Ù:\n/setpremium 12500"
        )
    elif q.data == "calc":
        await calc(update, context)
    elif q.data == "publish":
        await manual_publish(update, context)
    elif q.data == "status":
        await status(update, context)
    elif q.data == "auto":
        await auto_update(context)
        await q.message.reply_text(
            "ð¤ ÛÚ© Ø¨Ø±ÙØ²Ø±Ø³Ø§ÙÛ Ø®ÙØ¯Ú©Ø§Ø± Ø¢Ø²ÙØ§ÛØ´Û Ø§ÙØ¬Ø§Ù Ø´Ø¯."
        )


async def auto_update(context):
    if not session_open():
        return

    try:
        ounce = fetch_silver_ounce()
        dollar = fetch_iran_dollar_toman()

        if ounce is None or dollar is None:
            return

        set_setting("ounce", ounce)
        set_setting("dollar", dollar)
        await publish_if_needed(context)

    except Exception as e:
        log.exception("Auto update failed: %s", e)


async def error_handler(update, context):
    log.exception("Unhandled error: %s", context.error)


def main():
    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", myid))
    app.add_handler(CommandHandler("setounce", setounce))
    app.add_handler(CommandHandler("setdollar", setdollar))
    app.add_handler(CommandHandler("setpremium", setpremium))
    app.add_handler(CommandHandler("calc", calc))
    app.add_handler(CommandHandler("publish", manual_publish))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button))
    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(
        auto_update,
        interval=1800,
        first=10,
    )

    app.job_queue.run_repeating(
        silver_news_update,
        interval=3600,
        first=30,
    )

    app.job_queue.run_daily(
        close_day,
        time=time(21, 0, tzinfo=TZ),
    )

    app.run_polling()


if __name__ == "__main__":
    main()
