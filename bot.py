import os, math, sqlite3, logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

TZ = ZoneInfo("Asia/Tehran")

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_USER_ID = int(os.environ["ADMIN_USER_ID"])
CHANNEL_ID = os.environ["CHANNEL_ID"]

# APIs
METALPRICE_API_KEY = os.getenv("METALPRICE_API_KEY", "")
IRAN_FX_API_KEY = os.getenv("IRAN_FX_API_KEY", "")
NEWS_API_TOKEN = os.getenv("NEWS_API_TOKEN", "")
DB = os.getenv("DB_PATH", "yazdandoust.db")
logging.basicConfig(level=logging.INFO)
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
    row = con.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    con.close()
    return row["value"] if row else default

def set_setting(k, v):
    con = db()
    con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)))
    con.commit()
    con.close()

def fmt(n):
    return f"{int(round(float(n))):,}".replace(",", "٬")

def round_5000(x):
    return int(math.floor((float(x) + 2500) / 5000) * 5000)

def session_open():
    now = datetime.now(TZ).time()
    return time(11, 0) <= now < time(21, 0)

def current_inputs():
    ounce = get_setting("ounce")
    dollar = get_setting("dollar")
    premium = float(get_setting("premium", "0"))
    return (float(ounce) if ounce is not None else None,
            float(dollar) if dollar is not None else None,
            premium)

def theoretical_995(ounce, dollar):
    # USD/oz -> toman/g, then 99.5% purity.
    return (ounce * dollar / 31.1034768) * 0.995

def calculate_price(ounce, dollar, premium):
    return round_5000(theoretical_995(ounce, dollar) + premium)

def fetch_silver_ounce():
    if not METALPRICE_API_KEY:
        return None

    url = "https://api.metalpriceapi.com/v1/latest"

    params = {
        "api_key": METALPRICE_API_KEY,
        "base": "USD",
        "currencies": "XAG"
    }

    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()

    data = r.json()

    if not data.get("success"):
        raise ValueError(f"MetalpriceAPI error: {data}")

    rate = data.get("rates", {}).get("XAG")

    if rate is None:
        raise ValueError(f"XAG rate missing: {data}")

    return 1.0 / float(rate)
def fetch_iran_dollar_toman():
    if not IRAN_FX_API_KEY:
        return None
    # API Developers Iran: free-market currency service.
    r = requests.post(
        "https://api.apidevelopers.ir/v1/exchange-rates",
        json={"apiKey": IRAN_FX_API_KEY},
        timeout=15
    )
    r.raise_for_status()
    data = r.json()
    result = data.get("result", {})
    usd = result.get("usd")
    if not usd:
        raise ValueError("پاسخ سرویس دلار شامل usd نیست.")
    # The service may return buy/sell in IRT; convert rial -> toman if needed.
    value = usd.get("sell") or usd.get("buy")
    unit = str(usd.get("currency", "irt")).lower()
    value = float(value)
    return value / 10 if unit == "irt" else value

def daily_row():
    d = datetime.now(TZ).date().isoformat()
    con = db()
    row = con.execute("SELECT * FROM daily WHERE date=?", (d,)).fetchone()
    con.close()
    return row

def update_daily(price, message_id=None):
    d = datetime.now(TZ).date().isoformat()
    con = db()
    row = con.execute("SELECT * FROM daily WHERE date=?", (d,)).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO daily(date,start_price,high_price,low_price,last_price,message_id) VALUES(?,?,?,?,?,?)",
            (d, price, price, price, price, message_id)
        )
    else:
        con.execute("""
          UPDATE daily SET
            high_price=MAX(high_price, ?),
            low_price=MIN(low_price, ?),
            last_price=?,
            message_id=COALESCE(?, message_id)
          WHERE date=?
        """, (price, price, price, message_id, d))
    con.commit()
    con.close()

def rate_message(ounce, dollar, premium, price, stamp):
    return (
        "🥈 <b>نرخ لحظه‌ای نقره | یزدان‌دوست</b>\n\n"
        "⚪ <b>ساچمه نقره ۹۹۵</b>\n"
        f"<b>{fmt(price)} تومان / گرم</b>\n\n"
        f"🌎 انس نقره: <b>{ounce:.2f} $</b>\n"
        f"💵 دلار آزاد: <b>{fmt(dollar)} تومان</b>\n"
        f"📈 پرمیوم بازار: <b>{fmt(premium)} تومان</b>\n\n"
        f"🕐 آخرین بروزرسانی: <b>{stamp}</b>\n\n"
        "<b>YAZDANDOUST SILVER</b>\n"
        "دقیق • سریع • مطمئن"
    )

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌎 انس دستی", callback_data="help_ounce"),
         InlineKeyboardButton("💵 دلار دستی", callback_data="help_dollar")],
        [InlineKeyboardButton("📈 پرمیوم", callback_data="help_premium")],
        [InlineKeyboardButton("🤖 دریافت خودکار", callback_data="auto")],
        [InlineKeyboardButton("🧮 محاسبه", callback_data="calc"),
         InlineKeyboardButton("📢 انتشار", callback_data="publish")],
        [InlineKeyboardButton("📊 وضعیت امروز", callback_data="status")]
    ])

def admin(update):
    return bool(update.effective_user and update.effective_user.id == ADMIN_USER_ID)

async def start(update, context):
    if not admin(update):
        await update.message.reply_text("این ربات خصوصی است.")
        return
    await update.message.reply_text(
        "⚙️ <b>پنل مدیریت یزدان‌دوست</b>\n\n"
        "قیمت نهایی = قیمت تئوریک ۹۹۵ + پرمیوم دستی\n"
        "انتشار فقط در بازه ۱۱ تا ۲۱ و در تغییرات ۵٬۰۰۰ تومانی انجام می‌شود.",
        parse_mode="HTML", reply_markup=admin_kb()
    )

async def myid(update, context):
    await update.message.reply_text(f"Telegram User ID: {update.effective_user.id}")

async def setounce(update, context):
    if not admin(update): return
    try:
        v = float(context.args[0]); set_setting("ounce", v)
        await update.message.reply_text(f"✅ انس ذخیره شد: {v:.2f}")
    except:
        await update.message.reply_text("فرمت: /setounce 63.45")

async def setdollar(update, context):
    if not admin(update): return
    try:
        v = float(context.args[0]); set_setting("dollar", v)
        await update.message.reply_text(f"✅ دلار ذخیره شد: {fmt(v)} تومان")
    except:
        await update.message.reply_text("فرمت: /setdollar 186000")

async def setpremium(update, context):
    if not admin(update): return
    try:
        v = float(context.args[0]); set_setting("premium", v)
        await update.message.reply_text(f"✅ پرمیوم ذخیره شد: {fmt(v)} تومان")
    except:
        await update.message.reply_text("فرمت: /setpremium 12500")

async def calc(update, context):
    if not admin(update): return
    ounce, dollar, premium = current_inputs()
    if ounce is None or dollar is None:
        await update.message.reply_text("❌ هنوز انس و دلار مشخص نیست.")
        return
    t = theoretical_995(ounce, dollar)
    p = calculate_price(ounce, dollar, premium)
    await update.message.reply_text(
        f"🧮 تئوریک ۹۹۵: <b>{fmt(t)} تومان</b>\n"
        f"📈 پرمیوم: <b>{fmt(premium)}</b>\n"
        f"🥈 نرخ قابل انتشار: <b>{fmt(p)} تومان</b>",
        parse_mode="HTML"
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
        # Store observation, but do not change public rate.
        con = db()
        con.execute("""
          INSERT INTO ticks(ts,ounce,dollar,premium,theoretical,published_price,published)
          VALUES(?,?,?,?,?,?,0)
        """, (datetime.now(TZ).isoformat(), ounce, dollar, premium,
              theoretical_995(ounce, dollar), int(last)))
        con.commit(); con.close()
        return

    stamp = datetime.now(TZ).strftime("%H:%M")
    text = rate_message(ounce, dollar, premium, price, stamp)
    msg_id = get_setting("rate_message_id")
    if msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=CHANNEL_ID, message_id=int(msg_id),
                text=text, parse_mode="HTML"
            )
        except Exception:
            msg = await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML")
            msg_id = msg.message_id
            set_setting("rate_message_id", msg_id)
    else:
        msg = await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML")
        msg_id = msg.message_id
        set_setting("rate_message_id", msg_id)

    set_setting("last_published", price)
    update_daily(price, int(msg_id))
    con = db()
    con.execute("""
      INSERT INTO ticks(ts,ounce,dollar,premium,theoretical,published_price,published)
      VALUES(?,?,?,?,?,?,1)
    """, (datetime.now(TZ).isoformat(), ounce, dollar, premium,
          theoretical_995(ounce, dollar), price))
    con.commit(); con.close()
async def silver_news_update(context):
    if not GNEWS_API_KEY:
        log.warning("GNEWS_API_KEY is not set")
        return

    try:
        response = requests.get(
            "https://gnews.io/api/v4/search",
            params={
                "q": '"silver" OR "silver price" OR "silver market" OR "silver demand" OR "silver supply" OR "silver mining" OR "silver production"',
                "lang": "en",
                "max": 10,
                "sortby": "publishedAt",
                "apikey": GNEWS_API_KEY
            },
            timeout=20
        )

        response.raise_for_status()
        data = response.json()
        log.info("GNEWS TEST: status=%s articles=%s", response.status_code, len(data.get("articles", [])))
        articles = data.get("articles", [])

        if not articles:
            log.info("No new silver news found")
            return

        for article in articles:
            title = str(article.get("title", "")).strip()
            description = str(article.get("description", "")).strip()
            url = str(article.get("url", "")).strip()

            source_data = article.get("source", {})
            source = str(source_data.get("name", "Unknown")).strip()

            if not title or not url:
                continue

            # جلوگیری از ارسال خبر تکراری
            news_key = f"silver_{url}"

            last_news = get_setting("last_silver_news")

            if last_news == news_key:
                continue

            message = (
                "🥈 <b>اخبار جهانی نقره</b>\n\n"
                f"📰 <b>{title}</b>\n\n"
            )

            if description:
                message += f"{description}\n\n"

            message += f"🌍 منبع: {source}\n"
            message += f"🔗 <a href=\"{url}\">مشاهده خبر اصلی</a>\n\n"
            message += "━━━━━━━━━━━━━━\n"
            message += "🥈 <b>Yazdandoust Silver</b>"

            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=False
            )

            set_setting("last_silver_news", news_key)

            log.info("Silver news sent: %s", title)

            # در هر اجرا فقط یک خبر جدید منتشر شود
            break

    except Exception as e:
        log.exception("Silver news update failed: %s", e)
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
        log.exception("auto update failed: %s", e)
async def news_update(context):
    if not NEWS_API_TOKEN:
        return

    try:
        response = requests.get(
            "https://api.majidapi.ir/akhbar-dagh",
            params={
                "action": "latest",
                "token": NEWS_API_TOKEN
            },
            timeout=15
        )

        response.raise_for_status()
        items = response.json()

        if not isinstance(items, list):
            log.warning("News API returned unexpected data")
            return

        # کلمات مرتبط با ایران، جنگ و تحولات منطقه
        keywords = [
            "ایران", "اسرائیل", "آمریکا", "جنگ", "حمله",
            "موشک", "بمباران", "سنتکام", "ارتش", "سپاه",
            "آتش‌بس", "درگیری", "پهپاد", "مذاکرات",
            "لبنان", "غزه", "سوریه", "عراق", "فلسطین",
            "هسته‌ای", "تأسیسات", "حمله هوایی", "عملیات",
            "کشته", "انفجار", "پدافند", "ترور", "تحریم"
        ]

        # خبرهای مرتبط را پیدا کن
        relevant_news = []

        for item in items:
            if not isinstance(item, dict):
                continue

            title = str(item.get("title", "")).strip()

            if not title:
                continue

            title_lower = title.lower()

            if any(keyword in title_lower for keyword in keywords):
                relevant_news.append(item)

        if not relevant_news:
            log.info("No relevant news found")
            return

        # خبرهای مهم‌تر اول
        relevant_news.sort(
            key=lambda x: (
                bool(x.get("special", False)),
                x.get("id", 0)
            ),
            reverse=True
        )

        news = relevant_news[0]

        news_id = str(news.get("id", ""))

        if not news_id:
            return

        # جلوگیری از ارسال دوباره
        last_news_id = get_setting("last_news_id")

        if str(last_news_id) == news_id:
            return

        title = str(news.get("title", "")).strip()
        source = str(news.get("source", "")).strip()
        date = str(news.get("date", "")).strip()
        special = bool(news.get("special", False))

        if special:
            header = "🚨 <b>خبر فوری</b>"
        else:
            header = "📰 <b>خبر جدید</b>"

        text = f"{header}\n\n"
        text += f"🔴 <b>{title}</b>\n\n"

        if source:
            text += f"🗞 منبع: {source}\n"

        if date:
            text += f"🕐 زمان: {date}\n"

        text += "\n━━━━━━━━━━━━━━\n"
        text += "📡 <b>ساچمه نقره یزدان دوست</b>"

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=text,
            parse_mode="HTML"
        )

        set_setting("last_news_id", news_id)

        log.info("News sent: %s", title)

    except Exception as e:
        log.exception("News update failed: %s", e)
async def manual_publish(update, context):
    if not admin(update): return
    if not session_open():
        await update.message.reply_text("⏰ خارج از ساعت نرخ‌دهی ۱۱ تا ۲۱ هستیم.")
        return
    before = get_setting("last_published")
    await publish_if_needed(context)
    after = get_setting("last_published")
    if after == before:
        await update.message.reply_text("ℹ️ تغییر کمتر از ۵٬۰۰۰ تومان بود؛ نرخ کانال تغییر نکرد.")
    else:
        await update.message.reply_text(f"✅ نرخ کانال به {fmt(after)} تومان بروزرسانی شد.")

async def status(update, context):
    if not admin(update): return
    row = daily_row()
    if not row:
        await context.bot.send_message(
    chat_id=update.effective_chat.id,
    text="📊 امروز هنوز نرخ رسمی ثبت نشده."
)
        return
    await update.message.reply_text(
        "📊 <b>وضعیت امروز</b>\n\n"
        f"🔺 بیشترین: {fmt(row['high_price'])}\n"
        f"🔻 کمترین: {fmt(row['low_price'])}\n"
        f"🔹 آخرین: {fmt(row['last_price'])}\n"
        f"📌 شروع: {fmt(row['start_price'])}",
        parse_mode="HTML"
    )

async def close_day(context):
    row = daily_row()
    if not row:
        return
    change = row["last_price"] - row["start_price"]
    sign = "+" if change > 0 else ""
    text = (
        "🏁 <b>گزارش پایان معاملات نقره | یزدان‌دوست</b>\n\n"
        "🥈 ساچمه نقره ۹۹۵\n\n"
        f"🔺 بیشترین نرخ: <b>{fmt(row['high_price'])} تومان</b>\n"
        f"🔻 کمترین نرخ: <b>{fmt(row['low_price'])} تومان</b>\n"
        f"🔹 آخرین نرخ: <b>{fmt(row['last_price'])} تومان</b>\n"
        f"📊 تغییر نسبت به شروع: <b>{sign}{fmt(abs(change))} تومان</b>\n\n"
        "🕘 پایان معاملات: ۲۱:۰۰\n\n"
        "<b>YAZDANDOUST SILVER</b>\n"
        "دقیق • سریع • مطمئن"
    )
    await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML")
    # The daily table is kept for history. The next day's row is created automatically.

async def button(update, context):
    q = update.callback_query
    await q.answer()
    if not admin(update): return
    if q.data == "help_ounce":
        await q.message.reply_text("برای ورود دستی انس:\n/setounce 63.45")
    elif q.data == "help_dollar":
        await q.message.reply_text("برای ورود دستی دلار:\n/setdollar 186000")
    elif q.data == "help_premium":
        await q.message.reply_text("پرمیوم را به تومان وارد کن:\n/setpremium 12500")
    elif q.data == "calc":
        await calc(update, context)
    elif q.data == "publish":
        await manual_publish(update, context)
    elif q.data == "status":
        await status(update, context)
    elif q.data == "auto":
        await auto_update(context)
        await q.message.reply_text("🤖 یک بروزرسانی خودکار آزمایشی انجام شد.")

async def error_handler(update, context):
    log.exception("Unhandled error: %s", context.error)

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
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

    # Check every 5 minutes. The publication rule remains 5,000 تومان.
    app.job_queue.run_repeating(auto_update, interval=1800, first=10)
    app.job_queue.run_repeating(silver_news_update, interval=3600, first=30)
    app.job_queue.run_daily(close_day, time=time(21, 0, tzinfo=TZ))
    app.run_polling()

if __name__ == "__main__":
    main()
