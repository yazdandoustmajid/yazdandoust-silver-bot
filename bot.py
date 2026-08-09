# -*- coding: utf-8 -*-

import os,re,time,json,logging
from pathlib import Path
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from PIL import Image,ImageDraw,ImageFont

BOT_TOKEN=os.environ["BOT_TOKEN"]
CHANNEL_ID=os.environ["CHANNEL_ID"]
CHECK_SECONDS=int(os.getenv("CHECK_SECONDS","60"))

TGH_URL="https://t.me/s/tghsilver"
SITE_URL="https://taghizadegan.com/"
TEMPLATE_PATH=os.getenv("TEMPLATE_PATH","template.png")
STATE_PATH=os.getenv("STATE_PATH","state.json")

TROY_OUNCE_GRAMS=31.1034768
SILVER_PURITY=0.995

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("yazdandoust")

FA_DIGITS=str.maketrans("۰۱۲۳۴۵۶۷۸۹٬","0123456789,")
AR_DIGITS=str.maketrans("٠١٢٣٤٥٦٧٨٩٬","0123456789,")

def normalize_text(s):
    return (s or "").translate(FA_DIGITS).translate(AR_DIGITS).replace("٬",",")

def money(s):
    s=normalize_text(s).replace(",","").replace(".","")
    m=re.search(r"\d+",s)
    return int(m.group()) if m else None

def fmt(n):
    return "—" if n is None else f"{int(round(n)):,}"

def fmt_decimal(n,digits=2):
    return f"{n:.{digits}f}"

def fetch(url):
    r=requests.get(
        url,
        timeout=20,
        headers={"User-Agent":"Mozilla/5.0 Yazdandoust Silver Rate Bot"}
    )
    r.raise_for_status()
    return r.text

def parse_tgh():
    html=fetch(TGH_URL)
    soup=BeautifulSoup(html,"html.parser")
    text=normalize_text(soup.get_text("\n",strip=True))

    m=re.search(r"انس\s*[:：]?\s*(\d+(?:\.\d+)?)",text)
    ounce=float(m.group(1)) if m else None

    m=re.search(r"دلار\s*تهران\s*حدود\s*([\d,]+)",text)
    usd_tehran=money(m.group(1)) if m else None

    m=re.search(r"دلار\s*مشهد\s*حدود\s*([\d,]+)",text)
    usd_mashhad=money(m.group(1)) if m else None

    if not ounce:
        raise RuntimeError("انس نقره پیدا نشد")

    if not usd_mashhad:
        raise RuntimeError("دلار مشهد پیدا نشد")

    return {
        "ounce":ounce,
        "usd_tehran":usd_tehran,
        "usd_mashhad":usd_mashhad
    }

def parse_site():
    html=fetch(SITE_URL)
    soup=BeautifulSoup(html,"html.parser")
    text=normalize_text(soup.get_text("\n",strip=True))

    shot_995_kg=None
    patterns_995=[
        r"نقره\s+ساچمه\s+1000\s+گرمی\s+با\s+عیار\s+995.*?\n\s*([\d,.]+)\s*تومان",
        r"ساچمه\s+1000\s+گرمی\s+با\s+عیار\s+995.*?\n\s*([\d,.]+)\s*تومان"
    ]

    for p in patterns_995:
        m=re.search(p,text,re.S|re.I)
        if m:
            shot_995_kg=money(m.group(1))
            break

    nadir_kg=None
    patterns_nadir=[
        r"شمش\s+1000\s+گرمی\s+999\.9\s+نادیر.*?\n\s*([\d,.]+)\s*تومان",
        r"1000\s+گرمی\s+999\.9\s+نادیر.*?\n\s*([\d,.]+)\s*تومان"
    ]

    for p in patterns_nadir:
        m=re.search(p,text,re.S|re.I)
        if m:
            nadir_kg=money(m.group(1))
            break

    if not shot_995_kg:
        raise RuntimeError("قیمت ساچمه 995 پیدا نشد")

    if not nadir_kg:
        raise RuntimeError("قیمت شمش نادیر پیدا نشد")

    return {
        "shot_995_kg":shot_995_kg,
        "nadir_kg":nadir_kg
    }

def get_rates():
    tgh=parse_tgh()
    site=parse_site()

    spot_9999=tgh["ounce"]*tgh["usd_mashhad"]/TROY_OUNCE_GRAMS
    no_bubble_995=spot_9999*SILVER_PURITY
    market_995=site["shot_995_kg"]/1000
    bubble_pct=(market_995/no_bubble_995-1)*100

    return {
        **tgh,
        **site,
        "no_bubble_995":round(no_bubble_995),
        "market_995":round(market_995),
        "bubble_pct":round(bubble_pct,2)
    }

def load_font(size,bold=False):
    candidates=[
        "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansArabic-Bold.ttf" if bold else "/usr/share/fonts/opentype/noto/NotoSansArabic-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]

    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p,size)

    return ImageFont.load_default()

def cover(draw,box,fill=(1,18,10)):
    draw.rectangle(box,fill=fill)

def centered(draw,text,box,font,fill=(239,213,166)):
    x1,y1,x2,y2=box
    bb=draw.textbbox((0,0),text,font=font)
    w=bb[2]-bb[0]
    h=bb[3]-bb[1]
    x=(x1+x2-w)/2
    y=(y1+y2-h)/2-bb[1]
    draw.text((x,y),text,font=font,fill=fill)

def make_board(r):
    img=Image.open(TEMPLATE_PATH).convert("RGB")
    draw=ImageDraw.Draw(img)
    gold=(239,213,166)

    areas={
        "ounce":(600,305,915,360),
        "dollar":(590,382,915,440),
        "no_bubble":(590,565,905,625),
        "market":(590,625,905,690),
        "bubble":(600,690,900,750),
        "nadir":(545,785,925,850),
        "date":(625,885,850,930),
        "time":(890,885,1025,930)
    }

    for box in areas.values():
        cover(draw,box)

    f_big=load_font(48)
    f_money=load_font(44)
    f_small=load_font(28)
    f_tiny=load_font(24)

    centered(
        draw,
        f"{r['ounce']:.2f}",
        areas["ounce"],
        f_big,
        gold
    )

    centered(
        draw,
        fmt(r["usd_mashhad"]),
        areas["dollar"],
        f_big,
        gold
    )

    centered(
        draw,
        fmt(r["no_bubble_995"]),
        areas["no_bubble"],
        f_money,
        gold
    )

    centered(
        draw,
        fmt(r["market_995"]),
        areas["market"],
        f_money,
        gold
    )

    centered(
        draw,
        f"{r['bubble_pct']:+.2f}",
        areas["bubble"],
        f_money,
        gold
    )

    centered(
        draw,
        fmt(r["nadir_kg"]),
        areas["nadir"],
        f_money,
        gold
    )

    try:
        now=datetime.now(ZoneInfo("Asia/Tehran"))
    except Exception:
        now=datetime.now()

    date_text=now.strftime("%Y/%m/%d")
    time_text=now.strftime("%H:%M")

    centered(
        draw,
        date_text,
        areas["date"],
        f_small,
        gold
    )

    centered(
        draw,
        time_text,
        areas["time"],
        f_small,
        gold
    )

    output=BytesIO()
    img.save(output,format="PNG",optimize=True)
    output.seek(0)

    return output

CAPTION="""نرخ خرید فروش #ساچمه و #شمش
💵 دلار مشهد حدود {usd}
✅ خرید بالای ۲ کیلو تماس تلفنی
خرید و فروش انواع شمش های نقره و مستعمل

نرخ خرید فاکتورهای مجموعه همانند همیشه هست"""

def telegram_send(photo,caption):
    url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    response=requests.post(
        url,
        data={
            "chat_id":CHANNEL_ID,
            "caption":caption
        },
        files={
            "photo":(
                "yazdandoust-rate.png",
                photo,
                "image/png"
            )
        },
        timeout=30
    )

    if not response.ok:
        raise RuntimeError(
            f"Telegram error: {response.status_code} {response.text}"
        )

    return response.json()

def load_state():
    try:
        return json.loads(
            Path(STATE_PATH).read_text(encoding="utf-8")
        )
    except Exception:
        return None

def save_state(r):
    Path(STATE_PATH).write_text(
        json.dumps(r,ensure_ascii=False),
        encoding="utf-8"
    )

def comparable(r):
    return {
        "ounce":r["ounce"],
        "usd_tehran":r["usd_tehran"],
        "usd_mashhad":r["usd_mashhad"],
        "shot_995_kg":r["shot_995_kg"],
        "nadir_kg":r["nadir_kg"],
        "no_bubble_995":r["no_bubble_995"],
        "market_995":r["market_995"],
        "bubble_pct":r["bubble_pct"]
    }

def main():
    log.info("Yazdandoust rate bot started")
    previous=load_state()

    while True:
        try:
            rates=get_rates()
            current=comparable(rates)

            if previous!=current:
                log.info("Rate changed: %s",current)

                photo=make_board(rates)

                caption=CAPTION.format(
                    usd=fmt(rates["usd_mashhad"])
                )

                telegram_send(photo,caption)

                save_state(current)
                previous=current

            else:
                log.info("No rate change")

        except Exception:
            log.exception("Update failed")

        time.sleep(CHECK_SECONDS)

if __name__=="__main__":
    main()
