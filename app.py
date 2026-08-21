from flask import Flask, jsonify, request, send_from_directory, render_template, session, redirect
from pathlib import Path
import sqlite3, os, secrets

BASE = Path(__file__).resolve().parent
DB = BASE / "store.db"
UPLOADS = BASE / "uploads"
UPLOADS.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("STORE_SECRET_KEY", secrets.token_hex(32))

ADMIN_USER = os.environ.get("STORE_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("STORE_ADMIN_PASSWORD", "change-me")

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        weight REAL DEFAULT 0,
        purity TEXT DEFAULT '',
        brand TEXT DEFAULT '',
        price REAL DEFAULT 0,
        stock INTEGER DEFAULT 0,
        image TEXT DEFAULT '',
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_user_id TEXT DEFAULT '',
        customer_name TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        items_json TEXT NOT NULL,
        total REAL NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    defaults = {
        "product_925_per_gram": "1000000",
        "shot_995_base_per_gram": "0",
        "shot_markup_upto_50": "5",
        "shot_markup_100": "2",
        "shot_markup_over_100": "0",
    }
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (k,v))
    conn.commit()
    conn.close()

def settings():
    conn = db()
    rows = conn.execute("SELECT key,value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def calc_price(row, s):
    category = row["category"]
    if category == "925":
        return round(float(row["weight"]) * float(s["product_925_per_gram"]))
    if category == "shot995":
        base = float(s["shot_995_base_per_gram"])
        w = float(row["weight"])
        markup = float(s["shot_markup_upto_50"] if w <= 50 else s["shot_markup_100"] if w == 100 else s["shot_markup_over_100"])
        return round(w * base * (1 + markup/100))
    return float(row["price"])

@app.get("/")
def home():
    return render_template("index.html", miniapp=False)

@app.get("/miniapp")
def miniapp():
    return render_template("index.html", miniapp=True)

@app.get("/admin")
def admin():
    if not session.get("admin"):
        return redirect("/admin/login")
    return render_template("admin.html")

@app.get("/admin/login")
def admin_login():
    return render_template("login.html")

@app.post("/admin/login")
def admin_login_post():
    data = request.form
    if data.get("username") == ADMIN_USER and data.get("password") == ADMIN_PASSWORD:
        session["admin"] = True
        return redirect("/admin")
    return render_template("login.html", error="اطلاعات ورود صحیح نیست.")

@app.post("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")

@app.get("/api/settings")
def api_settings():
    return jsonify(settings())

@app.get("/api/products")
def api_products():
    conn = db()
    rows = conn.execute("SELECT * FROM products WHERE active=1 ORDER BY id DESC").fetchall()
    conn.close()
    s = settings()
    out = []
    for r in rows:
        x = dict(r)
        x["calculated_price"] = calc_price(r, s)
        out.append(x)
    return jsonify(out)

@app.post("/api/orders")
def create_order():
    data = request.get_json(force=True)
    items = data.get("items", [])
    if not items:
        return jsonify({"error":"سبد خرید خالی است"}), 400
    # Prices are recalculated server-side; client prices are never trusted.
    conn = db()
    s = settings()
    total = 0
    verified = []
    for item in items:
        row = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (item.get("id"),)).fetchone()
        if not row:
            continue
        qty = max(1, int(item.get("qty", 1)))
        unit = calc_price(row, s)
        total += unit * qty
        verified.append({"id": row["id"], "name": row["name"], "qty": qty, "unit_price": unit})
    import json
    cur = conn.execute(
        "INSERT INTO orders(telegram_user_id,customer_name,phone,items_json,total) VALUES(?,?,?,?,?)",
        (str(data.get("telegram_user_id","")), data.get("customer_name",""), data.get("phone",""), json.dumps(verified, ensure_ascii=False), total)
    )
    conn.commit()
    order_id = cur.lastrowid
    conn.close()
    return jsonify({"ok": True, "order_id": order_id, "total": total})

@app.get("/uploads/<path:name>")
def uploads(name):
    return send_from_directory(UPLOADS, name)

@app.get("/api/admin/products")
def admin_products():
    if not session.get("admin"): return jsonify({"error":"unauthorized"}), 401
    conn=db()
    rows=conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()
    s=settings()
    return jsonify([{**dict(r), "calculated_price": calc_price(r,s)} for r in rows])

@app.post("/api/admin/products")
def admin_add_product():
    if not session.get("admin"): return jsonify({"error":"unauthorized"}), 401
    data=request.get_json(force=True)
    required=["category","name"]
    if any(not data.get(k) for k in required):
        return jsonify({"error":"category and name are required"}),400
    conn=db()
    cur=conn.execute("""INSERT INTO products(category,name,description,weight,purity,brand,price,stock,image)
        VALUES(?,?,?,?,?,?,?,?,?)""",
        (data["category"],data["name"],data.get("description",""),float(data.get("weight",0)),
         data.get("purity",""),data.get("brand",""),float(data.get("price",0)),
         int(data.get("stock",0)),data.get("image","")))
    conn.commit(); pid=cur.lastrowid; conn.close()
    return jsonify({"ok":True,"id":pid})

@app.post("/api/admin/settings")
def admin_settings():
    if not session.get("admin"): return jsonify({"error":"unauthorized"}), 401
    data=request.get_json(force=True)
    conn=db()
    for k,v in data.items():
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(k,str(v)))
    conn.commit(); conn.close()
    return jsonify({"ok":True})

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",8000)), debug=True)
