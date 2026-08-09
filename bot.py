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
TEMPLATE=os.getenv("TEMPLATE_PATH","template.png")
STATE="state.json"
CHECK=int(os.getenv("CHECK_SECONDS","60"))
TROY=31.1034768
PURITY=.995
GOLD=(239,213,166)
BG=(4,19,14)

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")

def norm(s):
    return (s or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٬","0123456789,")).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٬","0123456789,"))

def num(s):
    m=re.search(r"\d[\d,]*",norm(s).replace("٬",","))
    return int(m.group().replace(",","")) if m else None

def get(url):
    r=requests.get(url,timeout=20,headers={"User-Agent":"Mozilla/5.0"})
    r.raise_for_status()
    return BeautifulSoup(r.text,"html.parser").get_text("\n",strip=True)

def first(patterns,text,cast=num):
    for p in patterns:
        m=re.search(p,norm(text),re.I|re.S)
        if m:
            try:return cast(m.group(1))
            except:pass
    return None

def rates():
    t=get("https://t.me/s/tghsilver")

    ounce=first([
        r"انس(?:\s+نقره)?\s*[:：]?\s*(\d+(?:\.\d+)?)"
    ],t,lambda x:float(x))

    usd=first([
        r"دلار\s*مشهد.{0,80}?([\d,]{5,})",
        r"دلار.{0,80}?([\d,]{5,})"
    ],t)

    if not ounce:
        raise RuntimeError("انس پیدا نشد")

    if not usd:
        raise RuntimeError("دلار مشهد پیدا نشد")

    s=get("https://taghizadegan.com/")

    shot=first([
        r"ساچمه\s+1000\s+گرمی\s+با\s+عیار\s+995.{0,150}?([\d,]{6,})\s*تومان",
        r"نقره\s+ساچمه.{0,180}?995.{0,180}?([\d,]{6,})\s*تومان"
    ],s)

    nadir=first([
        r"شمش\s+1000\s+گرمی\s+999\.9.{0,180}?([\d,]{6,})\s*تومان",
        r"1000\s+گرمی\s+999\.9.{0,180}?([\d,]{6,})\s*تومان"
    ],s)

    if not shot:
        raise RuntimeError("قیمت ساچمه پیدا نشد")

    if not nadir:
        raise RuntimeError("قیمت نادیر پیدا نشد")

    nob=ounce*usd/TROY*PURITY
    market=shot/1000

    return {
        "ounce":ounce,
        "usd":usd,
        "shot":shot,
        "nadir":nadir,
        "nob":round(nob),
        "market":round(market),
        "bubble":round((market/nob-1)*100,2)
    }

FONT="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def font(size):
    if Path(FONT).exists():
        return ImageFont.truetype(FONT,size)
    return ImageFont.load_default()

def fit(draw,text,box,maxsize,minsize=24):
    x1,y1,x2,y2=box
    size=maxsize

    while size>minsize:
        f=font(size)
        b=draw.textbbox((0,0),str(text),font=f)

        if b[2]-b[0] <= (x2-x1-24) and b[3]-b[1] <= (y2-y1-8):
            return f

        size-=2

    return font(minsize)

def put(draw,text,box,maxsize):
    x1,y1,x2,y2=box
    f=fit(draw,str(text),box,maxsize)

    draw.text(
        ((x1+x2)/2,(y1+y2)/2),
        str(text),
        font=f,
        fill=GOLD,
        anchor="mm"
    )

def board(r):
    im=Image.open(TEMPLATE).convert("RGB")
    d=ImageDraw.Draw(im)

    areas={
        "ounce":(600,305,915,360),
        "usd":(590,382,915,440),
        "nob":(590,565,905,625),
        "market":(590,625,905,690),
        "bubble":(600,690,900,750),
        "nadir":(545,785,925,850),
        "date":(625,885,850,930),
        "time":(890,885,1025,930)
    }

    for b in areas.values():
        d.rectangle(b,fill=BG)

    put(d,f"{r['ounce']:.2f}",areas["ounce"],54)
    put(d,f"{r['usd']:,}",areas["usd"],52)
    put(d,f"{r['nob']:,}",areas["nob"],50)
    put(d,f"{r['market']:,}",areas["market"],50)
    put(d,f"{r['bubble']:+.2f}",areas["bubble"],46)
    put(d,f"{r['nadir']:,}",areas["nadir"],48)

    try:
        n=datetime.now(ZoneInfo("Asia/Tehran"))
    except:
        n=datetime.now()

    put(d,n.strftime("%Y/%m/%d"),areas["date"],30)
    put(d,n.strftime("%H:%M"),areas["time"],30)

    out=BytesIO()
    im.save(out,"PNG",optimize=True)
    out.seek(0)

    return out

def send(photo,r):
    cap=f"""نرخ خرید فروش #ساچمه و #شمش
💵 دلار مشهد حدود {r['usd']:,}
✅ خرید بالای ۲ کیلو تماس تلفنی
خرید و فروش انواع شمش های نقره و مستعمل

نرخ خرید فاکتورهای مجموعه همانند همیشه هست"""

    u=f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"

    z=requests.post(
        u,
        data={
            "chat_id":CHANNEL_ID,
            "caption":cap
        },
        files={
            "photo":(
                "rate.png",
                photo,
                "image/png"
            )
        },
        timeout=30
    )

    z.raise_for_status()

def load():
    try:
        return json.loads(Path(STATE).read_text())
    except:
        return None

def save(x):
    Path(STATE).write_text(
        json.dumps(x,ensure_ascii=False)
    )

def main():
    old=load()

    while True:
        try:
            r=rates()
            cur={k:r[k] for k in r}

            if cur!=old:
                send(board(r),r)
                save(cur)
                old=cur
                logging.info("sent: %s",cur)
            else:
                logging.info("no change")

        except Exception as e:
            logging.exception("update failed: %s",e)

        time.sleep(CHECK)

if __name__=="__main__":
    main()
