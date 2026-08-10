# -*- coding: utf-8 -*-
import asyncio,json,logging,os,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import cv2,numpy as np,requests
from bs4 import BeautifulSoup
from PIL import Image,ImageDraw,ImageFont
from telethon import TelegramClient,events
from telethon.sessions import StringSession
BASE=Path(__file__).resolve().parent
TEMPLATE=BASE/"board_only_preview.png"
STATE=BASE/"state.json"
OUTPUT=BASE/"latest_price.jpg"
API_ID=os.getenv("API_ID","").strip()
API_HASH=os.getenv("API_HASH","").strip()
BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
SOURCE_SESSION=os.getenv("SOURCE_SESSION","").strip()
SOURCE_CHANNEL=os.getenv("SOURCE_CHANNEL","tghsilver").strip()
TARGET_CHANNEL=os.getenv("TARGET_CHANNEL","").strip()
WEBSITE_URL=os.getenv("WEBSITE_URL","https://taghizadegan.com").strip()
PHONE="09152449600"
TELEGRAM_ID="@MajidYazdandoust"
MITHQAL_GRAMS=4.6083
TEHRAN_TZ=ZoneInfo("Asia/Tehran")
logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(message)s")
log=logging.getLogger("YAZDANDOUST")
PERSIAN_DIGITS="۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS="٠١٢٣٤٥٦٧٨٩"
ENGLISH_DIGITS="0123456789"
DIGIT_TABLE=str.maketrans(PERSIAN_DIGITS+ARABIC_DIGITS,ENGLISH_DIGITS+ENGLISH_DIGITS)
def normalize_digits(text):
    return (text or "").translate(DIGIT_TABLE)
def clean_text(text):
    text=normalize_digits(text).replace("٬",",").replace("٫",".").replace("\u200c"," ")
    return re.sub(r"\s+"," ",text).strip()
def integer_value(text):
    text=normalize_digits(text).replace(",","").replace("٬","").replace(" ","")
    text=re.sub(r"[^\d]","",text)
    return int(text) if text else None
def decimal_value(text):
    text=normalize_digits(text).replace(",","").replace("٬","").replace("٫",".")
    text=re.sub(r"[^\d.]","",text)
    try:
        return float(text) if text else None
    except:
        return None
def format_price(value):
    return f"{int(round(value)):,}"
def tehran_now():
    return datetime.now(TEHRAN_TZ)
def gregorian_to_jalali(gy,gm,gd):
    g_d_m=[0,31,59,90,120,151,181,212,243,273,304,334]
    gy2=gy+1 if gm>2 else gy
    days=355666+365*gy+((gy2+3)//4)-((gy2+99)//100)+((gy2+399)//400)+gd+g_d_m[gm-1]
    jy=-1595+33*(days//12053)
    days%=12053
    jy+=4*(days//1461)
    days%=1461
    if days>365:
        jy+=(days-1)//365
        days=(days-1)%365
    if days<186:
        jm=1+days//31
        jd=1+days%31
    else:
        jm=7+(days-186)//30
        jd=1+(days-186)%30
    return jy,jm,jd
def persian_date_now():
    n=tehran_now()
    y,m,d=gregorian_to_jalali(n.year,n.month,n.day)
    return f"{y:04d}/{m:02d}/{d:02d}"
def parse_rate_message(text):
    if not text:
        return None
    text=clean_text(text)
    compact=text.replace(" ","")
    if "انس" not in compact:
        return None
    if "دلارتهران" not in compact:
        return None
    if "جدولنرخ" not in compact and "نرخخریدفروش" not in compact:
        return None
    ounce_match=re.search(r"انس\s*:?\s*(\d+(?:[.,]\d+)?)",text)
    tehran_match=re.search(r"دلار\s*تهران\s*(?:حدود)?\s*:?\s*([\d,]+)",text)
    if not ounce_match or not tehran_match:
        return None
    ounce=decimal_value(ounce_match.group(1))
    tehran=integer_value(tehran_match.group(1))
    if ounce is None or tehran is None:
        return None
    if not 20<=ounce<=150:
        return None
    if not 50000<=tehran<=2000000:
        return None
    return {
        "ounce":ounce,
        "tehran":tehran,
        "date":persian_date_now(),
        "time":tehran_now().strftime("%H:%M")
    }
def find_product_price(page_text,product_names):
    text=clean_text(page_text)
    for product_name in product_names:
        position=text.find(clean_text(product_name))
        if position<0:
            continue
        area=text[position:position+1200]
        matches=re.findall(r"([\d,.٬]{6,})\s*تومان",area)
        for match in matches:
            value=integer_value(match)
            if value is not None and 1000000<=value<=10000000000:
                return value
    return None
def fetch_website_prices_sync():
    response=requests.get(
        WEBSITE_URL,
        headers={
            "User-Agent":
            "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) "
            "AppleWebKit/605.1.15 Version/26.0 Mobile/15E148 Safari/604.1"
        },
        timeout=30
    )
    response.raise_for_status()
    soup=BeautifulSoup(response.text,"html.parser")
    page_text=soup.get_text(" ",strip=True)
    shot=find_product_price(
        page_text,
        [
            "نقره ساچمه 1000 گرمی با عیار 995",
            "نقره ساچمه 1000 گرمی با عیار ۹۹۵",
            "نقره ساچمه ۱۰۰۰ گرمی با عیار 995",
            "نقره ساچمه ۱۰۰۰ گرمی با عیار ۹۹۵"
        ]
    )
    nader=find_product_price(
        page_text,
        [
            "شمش 1000 گرمی 999.9 نادیر",
            "شمش 1000 گرمی ۹۹۹.۹ نادیر",
            "شمش ۱۰۰۰ گرمی 999.9 نادیر",
            "شمش ۱۰۰۰ گرمی ۹۹۹.۹ نادیر"
        ]
    )
    if shot is None:
        raise RuntimeError("قیمت ساچمه 995 در سایت تقی زادگان پیدا نشد.")
    if nader is None:
        raise RuntimeError("قیمت شمش نادیر 999.9 در سایت تقی زادگان پیدا نشد.")
    shot_g=shot/1000
    nader_g=nader/1000
    mithqal=round((shot_g*MITHQAL_GRAMS)/100)*100
    return {
        "shot_995":int(round(shot_g)),
        "nader_9999":int(round(nader_g)),
        "mithqal_995":int(mithqal)
    }
async def get_website_prices():
    last_error=None
    for attempt in range(4):
        try:
            return await asyncio.to_thread(fetch_website_prices_sync)
        except Exception as error:
            last_error=error
            log.warning(
                "Website attempt %s failed: %s",
                attempt+1,
                error
            )
            await asyncio.sleep(5)
    raise RuntimeError(f"خطا در دریافت قیمت سایت: {last_error}")
def get_font(size):
    paths=[
        BASE/"Vazirmatn-Bold.ttf",
        BASE/"Vazir-Bold.ttf",
        BASE/"IRANSans-Bold.ttf",
        BASE/"B Nazanin Bold.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")
    ]
    for path in paths:
        if Path(path).exists():
            try:
                return ImageFont.truetype(str(path),size)
            except Exception:
                pass
    return ImageFont.load_default()
NUMBER_BOXES=[
    (570,435,850,510),
    (570,550,850,635),
    (570,665,850,750),
    (570,785,850,870),
    (570,900,850,990)
]
def load_clean_template():
    if not TEMPLATE.exists():
        raise FileNotFoundError(
            "فایل board_only_preview.png کنار bot.py پیدا نشد."
        )
    original=cv2.imread(str(TEMPLATE))
    if original is None:
        raise RuntimeError("خواندن فایل قالب امکان‌پذیر نیست.")
    h,w=original.shape[:2]
    if w!=1086 or h!=1035:
        raise RuntimeError(
            "ابعاد board_only_preview.png باید دقیقاً 1086x1035 باشد."
        )
    cleaned=original.copy()
    for x1,y1,x2,y2 in NUMBER_BOXES:
        left=max(0,x1-8)
        right=min(w,x1+8)
        band=original[y1:y2+1,left:right+1]
        row_average=band.mean(
            axis=1,
            keepdims=True
        ).astype(np.float32)
        row_average=cv2.GaussianBlur(
            row_average,
            (1,15),
            0
        )
        fill=np.repeat(
            row_average,
            x2-x1+1,
            axis=1
        )
        cleaned[y1:y2+1,x1:x2+1]=fill.astype(np.uint8)
    return Image.fromarray(
        cv2.cvtColor(
            cleaned,
            cv2.COLOR_BGR2RGB
        )
    )
def draw_centered(
    draw,
    box,
    text,
    font,
    color=(232,207,161),
    stroke=1
):
    x1,y1,x2,y2=box
    bbox=draw.textbbox(
        (0,0),
        text,
        font=font,
        stroke_width=stroke
    )
    tw=bbox[2]-bbox[0]
    th=bbox[3]-bbox[1]
    x=x1+(x2-x1-tw)/2-bbox[0]
    y=y1+(y2-y1-th)/2-bbox[1]
    draw.text(
        (x,y),
        text,
        font=font,
        fill=color,
        stroke_width=stroke,
        stroke_fill=color
    )
def create_board(rate,products):
    image=load_clean_template()
    draw=ImageDraw.Draw(image)
    values=[
        f"{rate['ounce']:.2f}",
        format_price(rate["tehran"]),
        format_price(products["shot_995"]),
        format_price(products["nader_9999"]),
        format_price(products["mithqal_995"])
    ]
    for box,value in zip(NUMBER_BOXES,values):
        size=43 if len(value)<=7 else 40
        draw_centered(
            draw,
            box,
            value,
            get_font(size),
            stroke=1
        )
    image.save(
        OUTPUT,
        "JPEG",
        quality=98,
        optimize=True,
        progressive=True
    )
    return OUTPUT
def make_caption(rate):
    return (
        f"📅 تاریخ: {rate['date']}\n"
        f"🕐 ساعت ایران: {rate['time']}\n\n"
        f"📞 {PHONE}\n\n"
        "✅ خرید بالای ۲ کیلو تماس تلفنی جهت استعلام نرخ\n\n"
        "🔹 خرید و فروش انواع شمش‌های معتبر (قانونی)\n"
        "🔹 خرید مستعمل نقره\n"
        "🔹 نرخ خرید فاکتورهای مجموعه همانند همیشه هست\n\n"
        "💬 برای خرید یا هرگونه سؤال:\n"
        f"{TELEGRAM_ID}"
    )
def load_state():
    if not STATE.exists():
        return {}
    try:
        return json.loads(
            STATE.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return {}
def save_state(state):
    STATE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )
async def send_or_edit(
    bot_client,
    target,
    image,
    caption
):
    state=load_state()
    message_id=state.get("message_id")
    if message_id:
        try:
            await bot_client.edit_message(
                target,
                int(message_id),
                file=str(image),
                caption=caption
            )
            return int(message_id)
        except Exception as error:
            log.warning(
                "Saved message edit failed: %s",
                error
            )
    sent=await bot_client.send_file(
        target,
        str(image),
        caption=caption
    )
    return int(sent.id)
UPDATE_LOCK=asyncio.Lock()
async def process_rate_message(
    message,
    bot_client,
    target
):
    rate=parse_rate_message(
        message.raw_text or ""
    )
    if not rate:
        return
    async with UPDATE_LOCK:
        log.info(
            "RATE FOUND | OUNCE=%s | TEHRAN=%s",
            rate["ounce"],
            rate["tehran"]
        )
        products=await get_website_prices()
        signature=json.dumps(
            {
                "ounce":rate["ounce"],
                "tehran":rate["tehran"],
                "shot_995":products["shot_995"],
                "nader_9999":products["nader_9999"],
                "mithqal_995":products["mithqal_995"]
            },
            sort_keys=True,
            ensure_ascii=False
        )
        state=load_state()
        if state.get("signature")==signature:
            log.info("NO PRICE CHANGE")
            return
        image=create_board(
            rate,
            products
        )
        caption=make_caption(
            rate
        )
        message_id=await send_or_edit(
            bot_client,
            target,
            image,
            caption
        )
        save_state(
            {
                "signature":signature,
                "message_id":message_id,
                "source_message_id":message.id,
                "date":rate["date"],
                "time":rate["time"]
            }
        )
        log.info(
            "YAZDANDOUST BOARD UPDATED | MESSAGE=%s",
            message_id
        )
async def main():
    missing=[
        name
        for name,value in [
            ("API_ID",API_ID),
            ("API_HASH",API_HASH),
            ("BOT_TOKEN",BOT_TOKEN),
            ("TARGET_CHANNEL",TARGET_CHANNEL)
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(
            "این متغیرها تنظیم نشده‌اند: "
            + ", ".join(missing)
        )
    if not TEMPLATE.exists():
        raise RuntimeError(
            "فایل board_only_preview.png باید کنار bot.py باشد."
        )
    try:
        api_id=int(API_ID)
    except ValueError:
        raise RuntimeError(
            "API_ID باید فقط عدد باشد."
        )
    if SOURCE_SESSION:
        source_client=TelegramClient(
            StringSession(SOURCE_SESSION),
            api_id,
            API_HASH,
            sequential_updates=True,
            auto_reconnect=True,
            connection_retries=10,
            retry_delay=5
        )
    else:
        source_client=TelegramClient(
            str(BASE/"source"),
            api_id,
            API_HASH,
            sequential_updates=True,
            auto_reconnect=True,
            connection_retries=10,
            retry_delay=5
        )
    bot_client=TelegramClient(
        str(BASE/"bot"),
        api_id,
        API_HASH,
        sequential_updates=True,
        auto_reconnect=True,
        connection_retries=10,
        retry_delay=5
    )
    await source_client.start()
    await bot_client.start(
        bot_token=BOT_TOKEN
    )
    source_entity=await source_client.get_entity(
        SOURCE_CHANNEL
    )
    target_entity=await bot_client.get_entity(
        TARGET_CHANNEL
    )
    log.info(
        "SOURCE CONNECTED: @%s",
        SOURCE_CHANNEL
    )
    log.info(
        "TARGET CONNECTED: %s",
        TARGET_CHANNEL
    )
    async for message in source_client.iter_messages(
        source_entity,
        limit=100
    ):
        if parse_rate_message(
            message.raw_text or ""
        ):
            try:
                await process_rate_message(
                    message,
                    bot_client,
                    target_entity
                )
            except Exception:
                log.exception(
                    "INITIAL UPDATE FAILED"
                )
            break
    @source_client.on(
        events.NewMessage(
            chats=source_entity
        )
    )
    async def new_rate(event):
        try:
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
        "LIVE RATE UPDATE ENABLED"
    )
    log.info(
        "DOLLAR = TEHRAN ONLY"
    )
    log.info(
        "IRAN TIMEZONE = Asia/Tehran"
    )
    log.info(
        "BOT DOES NOT USE TELEGRAM HISTORY API"
    )
    log.info(
        "===================================="
    )
    await source_client.run_until_disconnected()
if __name__=="__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info(
            "BOT STOPPED"
        )
    except Exception:
        log.exception(
            "FATAL ERROR"
        )
