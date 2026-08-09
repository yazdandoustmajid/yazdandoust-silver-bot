import os,re,io,requests
from bs4 import BeautifulSoup
from PIL import Image,ImageDraw,ImageFont
from datetime import datetime
from zoneinfo import ZoneInfo
from telegram import Bot

TOKEN=os.getenv("BOT_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")
FONT=os.getenv("FONT_PATH","DejaVuSans.ttf")
BG=os.getenv("BG_PATH","bg.png")
TZ=ZoneInfo("Asia/Tehran")
SITE="https://taghizadegan.com/"
TG="https://t.me/s/tghsilver"

def fa2en(s):
    return str(s).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٬","0123456789,"))

def num(s):
    s=fa2en(s).replace(",","").replace("٬","")
    x=re.findall(r"\d+(?:\.\d+)?",s)
    return float(x[0]) if x else None

def money(n):
    return f"{int(round(n)):,}"

def page(url):
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0"},timeout=25)
    r.raise_for_status()
    return BeautifulSoup(r.text,"html.parser")

def site_rates():
    s=page(SITE)
    text=s.get_text(" ",strip=True)
    out={}
    pats=[
        ("nadir",r"شمش 1000 گرمی 999\.9 نادیر\s+.*?(\d[\d\.]+)\s*تومان"),
        ("shot995_100",r"نقره ساچمه 100 گرمی با عیار 995\s+.*?(\d[\d\.]+)\s*تومان"),
        ("shot995_1000",r"نقره ساچمه 1000 گرمی با عیار 995\s+.*?(\d[\d\.]+)\s*تومان"),
        ("shot999_100",r"نقره ساچمه 100 گرمی با عیار 999\.9\s+.*?(\d[\d\.]+)\s*تومان")
    ]
    for k,p in pats:
        m=re.search(p,text,re.S)
        if m: out[k]=num(m.group(1))
    return out

def tg_rate():
    s=page(TG)
    posts=s.select(".tgme_widget_message")
    for p in reversed(posts):
        t=p.get_text(" ",strip=True)
        if "انس:" not in t or "دلارمشهد" not in t:
            continue
        mo=re.search(r"انس\s*[:：]\s*([0-9۰-۹]+(?:\.[0-9]+)?)",t)
        md=re.search(r"دلارمشهد\s*(?:حدود)?\s*([0-9۰-۹,٬]+)",t)
        if mo and md:
            return {"ounce":num(mo.group(1)),"usd_mashhad":num(md.group(1))}
    raise RuntimeError("نرخ انس و دلار مشهد از کانال تقی زادگان پیدا نشد")

def font(size):
    for p in [FONT,"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:return ImageFont.truetype(p,size)
        except:pass
    return ImageFont.load_default()

def center(draw,text,box,f,fill):
    x1,y1,x2,y2=box
    b=draw.textbbox((0,0),text,font=f)
    x=(x1+x2-(b[2]-b[0]))/2
    y=(y1+y2-(b[3]-b[1]))/2-b[1]
    draw.text((x,y),text,font=f,fill=fill)

def make_image(r):
    if os.path.exists(BG):
        img=Image.open(BG).convert("RGB")
    else:
        img=Image.new("RGB",(1080,1350),(20,45,35))
    d=ImageDraw.Draw(img)
    gold=(230,210,165)
    white=(245,245,245)
    f1=font(52)
    f2=font(40)
    f3=font(30)
    now=datetime.now(TZ)
    center(d,f"{r['ounce']:.2f}",(500,300,1010,380),f1,white)
    center(d,money(r["usd_mashhad"]),(500,400,1010,480),f1,white)
    center(d,money(r["shot_buy"]),(500,560,1010,640),f2,white)
    center(d,money(r["shot_sell"]),(500,650,1010,730),f2,white)
    center(d,money(r["nadir"]),(500,750,1010,830),f2,white)
    center(d,now.strftime("%Y/%m/%d"),(500,1050,1010,1110),f3,gold)
    center(d,now.strftime("%H:%M"),(500,1120,1010,1180),f3,gold)
    b=io.BytesIO()
    img.save(b,"PNG")
    b.seek(0)
    return b

def caption(r):
    return (
        "نرخ خرید فروش #ساچمه و #شمش\n"
        f"💵 دلار مشهد حدود {money(r['usd_mashhad'])}\n"
        "✅ خرید بالای ۲ کیلو تماس تلفنی\n"
        "خرید و فروش انواع شمش های نقره و مستعمل\n\n"
        "نرخ خرید فاکتورهای مجموعه همانند همیشه هست"
    )

def rates():
    tg=tg_rate()
    st=site_rates()
    if "shot995_1000" not in st:
        raise RuntimeError("قیمت ساچمه ۹۹۵ در سایت تقی زادگان پیدا نشد")
    if "nadir" not in st:
        raise RuntimeError("قیمت شمش نادیر در سایت تقی زادگان پیدا نشد")
    shot_sell=st["shot995_1000"]/1000
    shot_buy=st.get("shot995_1000",0)/1000
    return {
        "ounce":tg["ounce"],
        "usd_mashhad":tg["usd_mashhad"],
        "shot_buy":shot_buy,
        "shot_sell":shot_sell,
        "nadir":st["nadir"]
    }

def main():
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("BOT_TOKEN یا CHAT_ID تنظیم نشده")
    r=rates()
    img=make_image(r)
    Bot(TOKEN).send_photo(
        chat_id=CHAT_ID,
        photo=img,
        caption=caption(r)
    )
    print("OK",r)

if __name__=="__main__":
    main()
