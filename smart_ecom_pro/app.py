import os, re, sqlite3, json, random, csv, io, time, threading, tempfile
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, jsonify, request, session, render_template, Response
from werkzeug.security import generate_password_hash, check_password_hash
import ml, payments, razorpay_gateway as rzp, reviewtools as rt

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
DB = os.environ.get("ECOM_DB", "shop.db")
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

CATALOG = {
    "Electronics": ["Wireless Earbuds", "Bluetooth Speaker", "Smart Watch", "Power Bank", "Gaming Mouse", "Mechanical Keyboard", "HD Webcam", "USB-C Hub"],
    "Fashion": ["Cotton Kurta", "Denim Jacket", "Running Shoes", "Leather Wallet", "Sunglasses", "Hoodie", "Formal Shirt", "Travel Backpack"],
    "Home": ["LED Desk Lamp", "Storage Organizer", "Air Fryer", "Electric Kettle", "Bedsheet Set", "Wall Clock", "Vacuum Cleaner", "Table Fan"],
    "Books": ["Python Crash Course", "Data Science Handbook", "Atomic Habits", "Clean Code", "Database Systems", "Operating System Concepts", "Machine Learning Basics", "Web Development Guide"],
    "Beauty": ["Face Serum", "Sunscreen SPF50", "Hair Oil", "Lip Balm", "Face Wash", "Body Lotion", "Perfume Spray", "Beard Trimmer"]}
CAT_WORDS = {"Electronics": "electronic gadget device battery wireless tech", "Fashion": "wear style clothing fashion comfortable",
             "Home": "home kitchen household decor appliance", "Books": "book learning guide study reading", "Beauty": "beauty skin care personal grooming"}
COST_RANGE = {"Electronics": (400, 4000), "Fashion": (200, 1500), "Home": (200, 2500), "Books": (150, 500), "Beauty": (80, 600)}
NAMES = ["Aarav", "Vivaan", "Aditya", "Diya", "Ananya", "Ishaan", "Kavya", "Riya", "Rohan", "Sneha", "Arjun", "Meera", "Karan", "Pooja", "Neha"]

def seed_demo(c):
    """Demo data: 40 products, 25 customers, ~180 orders (30 days), ~320 reviews analysed by the AI, 45-day price history."""
    rnd = random.Random(11); now = datetime.now(); fmt = "%Y-%m-%d %H:%M:%S"
    c.execute("INSERT INTO users(name,email,pw,role) VALUES(?,?,?,?)", ("Admin", "admin@shop.com", generate_password_hash("admin123"), "admin")) if not c.execute("SELECT 1 FROM users").fetchone() else None
    pw = generate_password_hash("demo123"); uids = []
    for i in range(25):
        uids.append(c.execute("INSERT INTO users(name,email,pw) VALUES(?,?,?)", (f"{NAMES[i % 15]} {i + 1}", f"demo{i + 1}@shop.com", pw)).lastrowid)
    pids, price_of, names = [], {}, {}
    for cat, items in CATALOG.items():
        lo, hi = COST_RANGE[cat]
        for n in items:
            cost = round(rnd.uniform(lo, hi)); price = round(cost * rnd.uniform(1.3, 1.8))
            stock = rnd.randint(8, 19) if rnd.random() < .12 else rnd.randint(30, 250)
            pid = c.execute("INSERT INTO products(name,category,description,price,cost,stock) VALUES(?,?,?,?,?,?)", (n, cat, f"{n.lower()} {CAT_WORDS[cat]}", price, cost, stock)).lastrowid
            v, drift = float(price), rnd.uniform(-.004, .006)
            for d in range(45):
                v *= 1 + drift + rnd.uniform(-.015, .015)
                c.execute("INSERT INTO price_history(product_id,price,day) VALUES(?,?,?)", (pid, round(v, 2), d))
            c.execute("UPDATE products SET price=? WHERE id=?", (round(v, 2), pid))
            pids.append(pid); price_of[pid] = round(v, 2); names[pid] = n
    w = [rnd.random() ** 2 + .05 for _ in pids]
    for _ in range(180):
        t = now - timedelta(days=rnd.randint(0, 29), hours=rnd.randint(0, 23), minutes=rnd.randint(0, 59)); items = {}
        for pid in rnd.choices(pids, w, k=rnd.randint(1, 3)): items[pid] = items.get(pid, 0) + rnd.randint(1, 2)
        oid = c.execute("INSERT INTO orders(user_id,total,created) VALUES(?,?,?)", (rnd.choice(uids), round(sum(price_of[p] * q for p, q in items.items()), 2), t.strftime(fmt))).lastrowid
        for p, q in items.items(): c.execute("INSERT INTO order_items VALUES(?,?,?,?)", (oid, p, q, price_of[p]))
    POS = ml._POS + ["delivery was quick and packaging was good", "price is reasonable for this quality", "seller support was helpful", "build quality is top notch"]
    NEG = ml._NEG + ["delivery was very late", "packaging was damaged", "build quality feels cheap", "seller support was rude", "too expensive for this quality"]
    for _ in range(320):
        pid = rnd.choices(pids, w)[0]; rating = rnd.choices([1, 2, 3, 4, 5], [8, 10, 15, 30, 37])[0]
        pool = POS if rating >= 4 else NEG if rating <= 2 else ml._NEU
        parts = rnd.sample(pool, rnd.randint(1, 3)) + ([rnd.choice(POS)] if rating == 3 else [])
        text = f"{names[pid]}: " + ", ".join(parts).capitalize() + "."
        if rnd.random() < .04: rating = 6 - rating                  # a few mismatching (fake-looking) reviews
        res = ml.analyze_review(text, rating); t = now - timedelta(days=rnd.randint(0, 29), hours=rnd.randint(0, 23))
        c.execute("INSERT INTO reviews(product_id,user_id,rating,text,sentiment,score,aspects,suspicious,flags,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (pid, rnd.choice(uids), rating, text, res["sentiment"], res["score"], json.dumps(res["aspects"]), int(res["suspicious"]), json.dumps(res["flags"]), t.strftime(fmt)))

def init():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, pw TEXT, role TEXT DEFAULT 'customer');
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT, category TEXT, description TEXT, price REAL, cost REAL, stock INT);
    CREATE TABLE IF NOT EXISTS price_history(id INTEGER PRIMARY KEY, product_id INT, price REAL, day INT);
    CREATE TABLE IF NOT EXISTS cart(user_id INT, product_id INT, qty INT, PRIMARY KEY(user_id, product_id));
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, user_id INT, total REAL, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS order_items(order_id INT, product_id INT, qty INT, price REAL);
    CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, product_id INT, user_id INT, rating INT, text TEXT,
        sentiment TEXT, score REAL, aspects TEXT, suspicious INT, flags TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS predictions(id INTEGER PRIMARY KEY, user_id INT, category TEXT, cost REAL, competitor_price REAL, rating REAL,
        demand REAL, stock INT, fair_price REAL, optimal_price REAL, created TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    if not c.execute("SELECT 1 FROM users").fetchone():
        c.execute("INSERT INTO users(name,email,pw,role) VALUES(?,?,?,?)",
                  ("Admin", "admin@shop.com", generate_password_hash("admin123"), "admin"))
    for col, ddl in [("status", "TEXT DEFAULT 'Placed'"), ("payment_method", "TEXT"), ("payment_status", "TEXT DEFAULT 'Pending'"), ("payment_ref", "TEXT")]:
        try: c.execute(f"ALTER TABLE orders ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError: pass                      # column already exists
    try: c.execute("ALTER TABLE products ADD COLUMN competitor_price REAL")
    except sqlite3.OperationalError: pass
    c.execute("CREATE TABLE IF NOT EXISTS training_reviews(id INTEGER PRIMARY KEY, text TEXT UNIQUE, rating REAL, source TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS pay_intents(rzp_order_id TEXT PRIMARY KEY, user_id INT, amount REAL, used INT DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP)")
    c.execute("CREATE TABLE IF NOT EXISTS order_events(order_id INT, status TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)")
    if not c.execute("SELECT 1 FROM products").fetchone(): seed_demo(c)
    c.execute("UPDATE orders SET status=CASE WHEN created < date('now','-5 day') THEN 'Delivered' WHEN created < date('now','-2 day') THEN 'Shipped' ELSE 'Placed' END, payment_status='Paid', payment_method='UPI' WHERE payment_method IS NULL")
    c.commit(); c.close()

def need(role=None):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if "uid" not in session: return jsonify(error="login required"), 401
            if role and session.get("role") != role: return jsonify(error="admin only"), 403
            return f(*a, **k)
        return w
    return deco

def product_rows(c, where="", args=()):
    out = []
    for p in c.execute(f"SELECT * FROM products {where}", args):
        r = c.execute("SELECT AVG(rating) a, COUNT(*) n FROM reviews WHERE product_id=? AND suspicious=0", (p["id"],)).fetchone()
        s = c.execute("SELECT sentiment, COUNT(*) n FROM reviews WHERE product_id=? AND suspicious=0 GROUP BY sentiment", (p["id"],)).fetchall()
        out.append({**dict(p), "avg_rating": round(r["a"], 1) if r["a"] else None, "review_count": r["n"],
                    "sentiment": {x["sentiment"]: x["n"] for x in s}})
    return out

@app.route("/")
def home(): return render_template("index.html", cats=ml.CATEGORIES)

# ---------- auth ----------
@app.post("/api/register")
def register():
    d = request.json; c = db()
    if not d.get("email") or len(d.get("password", "")) < 6: return jsonify(error="valid email and 6+ char password required"), 400
    try:
        c.execute("INSERT INTO users(name,email,pw) VALUES(?,?,?)", (d.get("name", "User"), d["email"].lower(), generate_password_hash(d["password"])))
        c.commit()
    except sqlite3.IntegrityError: return jsonify(error="email already registered"), 409
    return jsonify(ok=True)

@app.post("/api/login")
def login():
    d = request.json; u = db().execute("SELECT * FROM users WHERE email=?", (d.get("email", "").lower(),)).fetchone()
    if not u or not check_password_hash(u["pw"], d.get("password", "")): return jsonify(error="invalid credentials"), 401
    session.update(uid=u["id"], role=u["role"], name=u["name"])
    return jsonify(name=u["name"], role=u["role"])

@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)

@app.get("/api/me")
def me(): return jsonify(name=session.get("name"), role=session.get("role"))

# ---------- catalog ----------
@app.get("/api/products")
def products():
    q, cat, sort = request.args.get("q", ""), request.args.get("category", ""), request.args.get("sort", "")
    rows = product_rows(db(), "WHERE name LIKE ? AND (?='' OR category=?)", (f"%{q}%", cat, cat))
    key = {"price_asc": ("price", False), "price_desc": ("price", True), "rating": ("avg_rating", True)}.get(sort)
    if key: rows.sort(key=lambda r: r[key[0]] or 0, reverse=key[1])
    return jsonify(rows)

@app.get("/api/products/<int:pid>")
def product(pid):
    c = db(); rows = product_rows(c, "WHERE id=?", (pid,))
    if not rows: return jsonify(error="not found"), 404
    hist = [h["price"] for h in c.execute("SELECT price FROM price_history WHERE product_id=? ORDER BY day", (pid,))]
    revs = [dict(r) for r in c.execute("SELECT r.rating,r.text,r.sentiment,r.aspects,r.suspicious,r.flags,u.name FROM reviews r JOIN users u ON u.id=r.user_id WHERE product_id=? ORDER BY r.id DESC LIMIT 10", (pid,))]
    allp = [dict(p) for p in c.execute("SELECT * FROM products")]
    sim = [product_rows(c, "WHERE id=?", (i,))[0] for i in ml.recommend(pid, allp)]
    baskets = [set(map(int, r[0].split(","))) for r in c.execute("SELECT GROUP_CONCAT(product_id) FROM order_items GROUP BY order_id").fetchall()]
    also = [product_rows(c, "WHERE id=?", (i,))[0] for i in ml.also_bought(pid, baskets)]
    return jsonify(product=rows[0], history=hist, forecast=ml.forecast_prices(hist), reviews=revs, similar=sim, also_bought=also)

# ---------- cart & orders ----------
@app.get("/api/cart")
@need()
def cart():
    rows = db().execute("SELECT p.id,p.name,p.price,p.stock,c.qty FROM cart c JOIN products p ON p.id=c.product_id WHERE c.user_id=?", (session["uid"],)).fetchall()
    items = [dict(r) for r in rows]
    return jsonify(items=items, total=round(sum(i["price"] * i["qty"] for i in items), 2))

@app.post("/api/cart")
@need()
def cart_add():
    d = request.json; c = db()
    c.execute("INSERT INTO cart VALUES(?,?,?) ON CONFLICT(user_id,product_id) DO UPDATE SET qty=qty+excluded.qty", (session["uid"], d["product_id"], int(d.get("qty", 1))))
    c.commit(); return jsonify(ok=True)

@app.delete("/api/cart/<int:pid>")
@need()
def cart_del(pid):
    c = db(); c.execute("DELETE FROM cart WHERE user_id=? AND product_id=?", (session["uid"], pid)); c.commit(); return jsonify(ok=True)

def cart_items(c, uid):
    return c.execute("SELECT p.id,p.name,p.price,p.stock,k.qty FROM cart k JOIN products p ON p.id=k.product_id WHERE k.user_id=?", (uid,)).fetchall()

def place_order(c, uid, items, total, pay):
    oid = c.execute("INSERT INTO orders(user_id,total,status,payment_method,payment_status,payment_ref) VALUES(?,?,?,?,?,?)", (uid, total, "Placed", pay["method"], pay["status"], pay["ref"])).lastrowid
    c.execute("INSERT INTO order_events(order_id,status) VALUES(?,?)", (oid, "Placed"))
    for i in items:
        c.execute("INSERT INTO order_items VALUES(?,?,?,?)", (oid, i["id"], i["qty"], i["price"]))
        c.execute("UPDATE products SET stock=stock-? WHERE id=?", (i["qty"], i["id"]))
    c.execute("DELETE FROM cart WHERE user_id=?", (uid,)); c.commit(); return oid

# ---------- REAL payments: Razorpay ----------
@app.get("/api/pay/config")
def pay_config(): return jsonify(mode="razorpay" if rzp.enabled() else "demo")

@app.post("/api/pay/create")
@need()
def pay_create():
    if not rzp.enabled(): return jsonify(error="Razorpay is not configured (set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET)"), 400
    c = db(); items = cart_items(c, session["uid"])
    if not items: return jsonify(error="cart is empty"), 400
    for i in items:
        if i["qty"] > i["stock"]: return jsonify(error=f"only {i['stock']} left for {i['name']}"), 409
    total = round(sum(i["price"] * i["qty"] for i in items), 2)               # amount always computed on the server
    try: o = rzp.create_order(total, f"cart{session['uid']}_{int(time.time())}")
    except Exception as e: return jsonify(error=f"Could not create the Razorpay order: {e}"), 502
    c.execute("INSERT INTO pay_intents(rzp_order_id,user_id,amount) VALUES(?,?,?)", (o["id"], session["uid"], total)); c.commit()
    return jsonify(order_id=o["id"], amount=o["amount"], key_id=rzp.KEY_ID())

@app.post("/api/pay/verify")
@need()
def pay_verify():
    d = request.get_json(silent=True) or {}; c = db(); oid_r, pid = d.get("razorpay_order_id"), d.get("razorpay_payment_id")
    it = c.execute("SELECT * FROM pay_intents WHERE rzp_order_id=? AND user_id=?", (oid_r, session["uid"])).fetchone()
    if not it or it["used"]: return jsonify(error="Invalid or already-used payment"), 400
    if not rzp.verify_signature(oid_r, pid, d.get("razorpay_signature")): return jsonify(error="Payment signature verification failed"), 400
    items = cart_items(c, session["uid"]); total = round(sum(i["price"] * i["qty"] for i in items), 2)
    if not items or abs(total - it["amount"]) > .01 or any(i["qty"] > i["stock"] for i in items):
        return jsonify(error=f"Your cart or stock changed. Payment ({pid}) was received; please contact support for a refund."), 409
    c.execute("UPDATE pay_intents SET used=1 WHERE rzp_order_id=?", (oid_r,))
    oid = place_order(c, session["uid"], items, total, {"method": "Razorpay", "status": "Paid", "ref": pid})
    return jsonify(order_id=oid, total=total, payment_status="Paid", payment_ref=pid)

@app.post("/api/checkout")
@need()
def checkout():
    d = request.get_json(silent=True) or {}; c = db()
    items = c.execute("SELECT p.id,p.name,p.price,p.stock,k.qty FROM cart k JOIN products p ON p.id=k.product_id WHERE k.user_id=?", (session["uid"],)).fetchall()
    if not items: return jsonify(error="cart is empty"), 400
    for i in items:
        if i["qty"] > i["stock"]: return jsonify(error=f"only {i['stock']} left for {i['name']}"), 409
    total = round(sum(i["price"] * i["qty"] for i in items), 2)
    pay = payments.charge(d.get("method", "COD"), total, d.get("details") or {})
    if not pay["ok"]: return jsonify(error=pay["error"]), 402          # payment failed: no order created, cart kept
    oid = place_order(c, session["uid"], items, total, pay)
    return jsonify(order_id=oid, total=total, payment_status=pay["status"], payment_ref=pay["ref"])

STATUSES = ["Placed", "Packed", "Shipped", "Delivered"]

def order_rows(c, where="", args=(), limit=100):
    out = []
    for o in c.execute(f"SELECT o.*, u.email FROM orders o JOIN users u ON u.id=o.user_id {where} ORDER BY o.id DESC LIMIT {int(limit)}", args):
        it = c.execute("SELECT p.name,i.qty,i.price FROM order_items i JOIN products p ON p.id=i.product_id WHERE order_id=?", (o["id"],)).fetchall()
        ev = c.execute("SELECT status, created FROM order_events WHERE order_id=? ORDER BY rowid", (o["id"],)).fetchall()
        out.append({**dict(o), "items": [dict(x) for x in it], "events": [dict(e) for e in ev]})
    return out

@app.get("/api/orders")
@need()
def orders(): return jsonify(order_rows(db(), "WHERE o.user_id=?", (session["uid"],)))

@app.get("/api/admin/orders")
@need("admin")
def admin_orders(): return jsonify(order_rows(db(), limit=60))

@app.put("/api/admin/orders/<int:oid>/status")
@need("admin")
def order_status(oid):
    st = (request.json or {}).get("status"); c = db(); o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o: return jsonify(error="order not found"), 404
    if st not in STATUSES + ["Cancelled"]: return jsonify(error="invalid status"), 400
    if o["status"] in ("Delivered", "Cancelled"): return jsonify(error=f"order already {o['status']}"), 409
    if st != "Cancelled" and STATUSES.index(st) <= STATUSES.index(o["status"]): return jsonify(error="Status can only move forward"), 409
    if st == "Cancelled":
        for i in c.execute("SELECT product_id,qty FROM order_items WHERE order_id=?", (oid,)).fetchall():
            c.execute("UPDATE products SET stock=stock+? WHERE id=?", (i["qty"], i["product_id"]))          # restock
        c.execute("UPDATE orders SET payment_status=CASE WHEN payment_status='Paid' THEN 'Refunded' ELSE payment_status END WHERE id=?", (oid,))
    if st == "Delivered":                                                                                  # COD cash collected
        c.execute("UPDATE orders SET payment_status=CASE WHEN payment_status LIKE 'Pending%' THEN 'Paid' ELSE payment_status END WHERE id=?", (oid,))
    c.execute("UPDATE orders SET status=? WHERE id=?", (st, oid)); c.execute("INSERT INTO order_events(order_id,status) VALUES(?,?)", (oid, st))
    c.commit(); return jsonify(ok=True)

# ---------- reviews / AI ----------
@app.post("/api/analyze")                       # public demo tool
def analyze(): return jsonify(ml.analyze_review(request.json.get("text", ""), request.json.get("rating")))

@app.post("/api/reviews")
@need()
def add_review():
    d = request.json; c = db()
    ex = [r["text"] for r in c.execute("SELECT text FROM reviews WHERE product_id=?", (d["product_id"],))]
    res = ml.analyze_review(d["text"], int(d["rating"]), ex)
    c.execute("INSERT INTO reviews(product_id,user_id,rating,text,sentiment,score,aspects,suspicious,flags) VALUES(?,?,?,?,?,?,?,?,?)",
              (d["product_id"], session["uid"], d["rating"], d["text"], res["sentiment"], res["score"], json.dumps(res["aspects"]), int(res["suspicious"]), json.dumps(res["flags"])))
    c.commit(); return jsonify(res)

# ---------- admin ----------
@app.post("/api/predict_price")
@need("admin")
def predict():
    d = request.json or {}
    try:
        cost, comp = float(d["cost"]), float(d["competitor_price"])
        rating, demand, stock = float(d["rating"]), float(d["demand"]), int(float(d["stock"]))
    except (KeyError, ValueError, TypeError):
        return jsonify(error="Fill in all fields (cost, competitor price, rating, demand, stock) as numbers"), 400
    if d.get("category") not in ml.CATEGORIES or cost <= 0 or comp <= 0 or not 1 <= rating <= 5 or stock < 0:
        return jsonify(error="Cost and competitor price must be above 0, rating 1-5, and stock 0 or more"), 400
    res = ml.predict_price(d["category"], cost, comp, rating, demand, stock)
    c = db(); c.execute("INSERT INTO predictions(user_id,category,cost,competitor_price,rating,demand,stock,fair_price,optimal_price) VALUES(?,?,?,?,?,?,?,?,?)",
                        (session["uid"], d["category"], cost, comp, rating, demand, stock, res["fair_price"], res["profit_optimal_price"])); c.commit()
    return jsonify(res)

@app.put("/api/admin/products/<int:pid>/price")
@need("admin")
def set_price(pid):
    c = db(); p = float(request.json["price"])
    c.execute("UPDATE products SET price=? WHERE id=?", (p, pid))
    day = (c.execute("SELECT MAX(day) m FROM price_history WHERE product_id=?", (pid,)).fetchone()["m"] or 0) + 1
    c.execute("INSERT INTO price_history(product_id,price,day) VALUES(?,?,?)", (pid, p, day)); c.commit(); return jsonify(ok=True)

@app.post("/api/admin/products")
@need("admin")
def add_product():
    d = request.json; c = db()
    cur = c.execute("INSERT INTO products(name,category,description,price,cost,stock) VALUES(?,?,?,?,?,?)",
                    (d["name"], d["category"], d.get("description", ""), d["price"], d["cost"], d["stock"]))
    c.execute("INSERT INTO price_history(product_id,price,day) VALUES(?,?,0)", (cur.lastrowid, d["price"])); c.commit()
    return jsonify(id=cur.lastrowid)

@app.get("/api/admin/stats")
@need("admin")
def stats():
    c = db(); g = lambda q: c.execute(q).fetchone()[0]
    return jsonify(
        revenue=round(g("SELECT COALESCE(SUM(total),0) FROM orders WHERE status!='Cancelled'"), 2), orders=g("SELECT COUNT(*) FROM orders"),
        customers=g("SELECT COUNT(*) FROM users WHERE role='customer'"), suspicious_reviews=g("SELECT COUNT(*) FROM reviews WHERE suspicious=1"),
        sentiment={r["sentiment"]: r["n"] for r in c.execute("SELECT sentiment, COUNT(*) n FROM reviews WHERE suspicious=0 GROUP BY sentiment")},
        top_products=[dict(r) for r in c.execute("SELECT p.name, SUM(i.qty) units FROM order_items i JOIN products p ON p.id=i.product_id GROUP BY p.id ORDER BY units DESC LIMIT 5")],
        low_stock=[dict(r) for r in c.execute("SELECT id,name,stock FROM products WHERE stock<20")],
        revenue_by_day=[dict(r) for r in c.execute("SELECT substr(created,1,10) d, ROUND(SUM(total),2) rev, COUNT(*) n FROM orders GROUP BY d ORDER BY d")],
        category_sales=[dict(r) for r in c.execute("SELECT p.category c, ROUND(SUM(i.qty*i.price),2) rev FROM order_items i JOIN products p ON p.id=i.product_id GROUP BY p.category ORDER BY rev DESC")],
        recent_predictions=[dict(r) for r in c.execute("SELECT category,cost,competitor_price,fair_price,optimal_price,created FROM predictions ORDER BY id DESC LIMIT 8")],
        model_info={"price_r2": ml.PRICE_R2, "sentiment_acc": ml.SENT_ACC})

# ---------- link / bulk review analysis (public) ----------
@app.post("/api/fetch_reviews")
def fetch_reviews():
    url = (request.json or {}).get("url", "").strip()
    if not url: return jsonify(error="Paste a link"), 400
    if "://" not in url: url = "https://" + url
    try: page = rt.fetch_url(url)
    except ValueError as e: return jsonify(error=str(e)), 400
    except Exception as e: return jsonify(error=f"Could not open the page ({e}). The site may be blocking bots; paste or upload the reviews instead."), 502
    ex = rt.extract(page)
    if not ex["reviews"]:
        return jsonify(count=0, title=ex["title"], site_rating=ex["site_rating"], site_count=ex["site_count"], note=rt.NO_REVIEWS)
    return jsonify(rt.summarize(ex["reviews"], ex["title"] or url, f"Source: {url}", ex["site_rating"], ex["site_count"]))

@app.post("/api/search_reviews")
def search_reviews():
    q = ((request.json or {}).get("query") or "").strip()
    if len(q) < 3: return jsonify(error="Enter a product or company name (at least 3 characters)"), 400
    try: rows, src, srat, scnt, tried = rt.search_reviews(q)
    except Exception as e: return jsonify(error=f"Search failed ({e}). Paste a link, or paste/upload the reviews instead."), 502
    if not rows: return jsonify(count=0, title=q, note=f"{tried} pages checked, no reviews found. " + rt.NO_REVIEWS)
    res = rt.summarize(rows, q, f"{len(src)} sites with reviews found (pages from the search results that publish reviews)", srat, scnt)
    res["sources"] = sorted(src.items(), key=lambda kv: -kv[1]); return jsonify(res)

@app.post("/api/analyze_bulk")
def analyze_bulk():
    items = [{"text": x, "rating": None} if isinstance(x, str) else x for x in (request.json or {}).get("reviews", [])]
    if not items: return jsonify(error="No reviews found"), 400
    return jsonify(rt.summarize(items, (request.json or {}).get("title", "Pasted reviews")))

# ---------- CSV export (admin) ----------
EXPORTS = {
    "products": "SELECT id,name,category,description,price,cost,stock FROM products",
    "orders": "SELECT o.id order_id,u.email customer,o.created,p.name product,i.qty,i.price unit_price,i.qty*i.price line_total FROM orders o JOIN users u ON u.id=o.user_id JOIN order_items i ON i.order_id=o.id JOIN products p ON p.id=i.product_id ORDER BY o.id",
    "reviews": "SELECT r.id,p.name product,r.rating,r.text,r.sentiment,r.score,r.aspects,r.suspicious,r.flags,r.created FROM reviews r JOIN products p ON p.id=r.product_id",
    "price_history": "SELECT p.name product,h.day,h.price FROM price_history h JOIN products p ON p.id=h.product_id ORDER BY p.id,h.day",
    "predictions": "SELECT * FROM predictions ORDER BY id DESC"}

@app.get("/api/export/<kind>.csv")
@need("admin")
def export(kind):
    if kind not in EXPORTS: return jsonify(error="unknown export"), 404
    cur = db().execute(EXPORTS[kind]); out = io.StringIO(); out.write("\ufeff"); w = csv.writer(out)
    w.writerow([d[0] for d in cur.description]); w.writerows(cur.fetchall())
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={kind}.csv"})

# ---------- AI pricing optimizer (admin) ----------
def pricing_rows(c):
    sold = {r["product_id"]: r["q"] for r in c.execute("SELECT i.product_id, SUM(i.qty) q FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.created >= date('now','-14 day') GROUP BY i.product_id")}
    mx = max(sold.values(), default=1); rows = []
    for p in product_rows(c):
        real = p.get("competitor_price"); comp = real if real else round(p["price"] * (0.95 + (p["id"] * 37 % 21) / 100), 2)   # admin/CSV price, else simulated
        rating = p["avg_rating"] or 4.0; demand = round(0.1 + 0.9 * sold.get(p["id"], 0) / mx, 2)
        best = ml.predict_price(p["category"], p["cost"], comp, rating, demand, p["stock"])["profit_optimal_price"]
        sug = round(max(min(max(best, p["price"] * .85), p["price"] * 1.15), p["cost"] * 1.05), 2)   # +-15% safety guardrail
        up = ml.profit_at(sug, p["cost"], comp, rating, demand) - ml.profit_at(p["price"], p["cost"], comp, rating, demand)
        rows.append({"id": p["id"], "name": p["name"], "cost": p["cost"], "price": p["price"], "competitor": comp, "competitor_source": "real" if real else "simulated", "demand": demand,
                     "suggested": sug, "change_pct": round((sug - p["price"]) / p["price"] * 100, 1), "uplift": round(up)})
    return rows

@app.get("/api/admin/pricing")
@need("admin")
def pricing():
    rows = pricing_rows(db()); return jsonify(rows=rows, total_uplift=sum(r["uplift"] for r in rows if r["change_pct"]))

@app.post("/api/admin/pricing/apply")
@need("admin")
def pricing_apply():
    c = db(); ids = (request.json or {}).get("ids"); n = 0
    for r in pricing_rows(c):
        if (ids is None or r["id"] in ids) and r["change_pct"]:
            c.execute("UPDATE products SET price=? WHERE id=?", (r["suggested"], r["id"]))
            day = (c.execute("SELECT MAX(day) m FROM price_history WHERE product_id=?", (r["id"],)).fetchone()["m"] or 0) + 1
            c.execute("INSERT INTO price_history(product_id,price,day) VALUES(?,?,?)", (r["id"], r["suggested"], day)); n += 1
    c.commit(); return jsonify(applied=n)

# ---------- Model Lab (real-data model reports) ----------
@app.get("/api/admin/model_report")
@need("admin")
def model_report():
    out = {"source": ml.MODEL_SOURCE, "cats": (ml.REAL.get("price") or {}).get("cats", [])}
    for k in ("sentiment", "price"):
        p = os.path.join(ml.MODELS_DIR, f"{k}_report.json"); out[k] = json.load(open(p)) if os.path.exists(p) and ml.MODEL_SOURCE[k] != "synthetic demo data" else None
    return jsonify(out)

@app.post("/api/admin/real_price")
@need("admin")
def real_price():
    d = request.json or {}
    try: mrp = float(d["mrp"]); est = ml.real_price_estimate(d.get("category", ""), mrp, float(d["rating"]), float(d["n_ratings"]))
    except (KeyError, ValueError, TypeError): return jsonify(error="Enter MRP, rating and ratings count as numbers"), 400
    if est is None: return jsonify(error="The real-data price model is not trained yet. Run in a terminal: python train.py price <csv>"), 400
    return jsonify(estimate=est, discount_pct=round((1 - est / mrp) * 100, 1))

@app.put("/api/admin/products/<int:pid>/competitor")
@need("admin")
def set_competitor(pid):
    v = (request.json or {}).get("price")
    try: v = float(v) if v not in (None, "") else None
    except (TypeError, ValueError): return jsonify(error="Price must be a number"), 400
    if v is not None and v <= 0: return jsonify(error="Price must be greater than 0"), 400
    c = db(); c.execute("UPDATE products SET competitor_price=? WHERE id=?", (v, pid)); c.commit(); return jsonify(ok=True)

@app.post("/api/admin/competitor_csv")
@need("admin")
def competitor_csv():
    c = db(); n = 0; names = {r["name"].lower(): r["id"] for r in c.execute("SELECT id,name FROM products")}
    for r in (request.json or {}).get("rows", []):
        pid = names.get(str(r.get("name", "")).strip().lower()) or (int(r["id"]) if str(r.get("id", "")).isdigit() else None)
        try: v = float(r.get("competitor_price"))
        except (TypeError, ValueError): continue
        if pid and v > 0: c.execute("UPDATE products SET competitor_price=? WHERE id=?", (v, pid)); n += 1
    c.commit(); return jsonify(updated=n)

# ---------- Train models inside the app (admin) ----------
TRAIN = {"state": "idle", "message": "", "task": ""}; _tlock = threading.Lock()

def training_counts(c):
    cnt = {r[0]: r[1] for r in c.execute("SELECT CASE WHEN rating>=4 THEN 'Positive' WHEN rating<=2 THEN 'Negative' ELSE 'Neutral' END l, COUNT(*) FROM training_reviews GROUP BY l")}
    return {"counts": cnt, "total": sum(cnt.values())}

def _train_thread(kind, path):
    import train
    try:
        TRAIN.update(state="running", task=kind, message=f"Training the {kind} model on {os.path.basename(path)} ...")
        rep = train.train_sentiment(path, out=ml.MODELS_DIR) if kind == "sentiment" else train.train_price(path, out=ml.MODELS_DIR)
        ml.load_real_models(); b = rep["comparison"][rep["best_model"]]
        TRAIN.update(state="done", message=f"Done. Best model: {rep['best_model']}, " + (f"accuracy {b['accuracy']}, macro-F1 {b['macro_f1']}" if kind == "sentiment" else f"R2 {b['r2']}, MAE Rs.{b['mae']}") + f", trained on {rep['rows']} rows.")
    except (Exception, SystemExit) as e: TRAIN.update(state="error", message=str(e) or "Training failed")
    finally: _tlock.release()

@app.post("/api/admin/training/add")
@need("admin")
def training_add():
    c = db(); n = 0
    for r in (request.json or {}).get("reviews", [])[:500]:
        t = str(r.get("text", "")).strip()
        try: rt_ = float(r.get("rating"))
        except (TypeError, ValueError): continue
        if len(t) >= 10 and 1 <= rt_ <= 5: n += c.execute("INSERT OR IGNORE INTO training_reviews(text,rating,source) VALUES(?,?,?)", (t[:1500], rt_, "browser import")).rowcount
    c.commit(); return jsonify(added=n, **training_counts(c))

@app.get("/api/admin/training/status")
@need("admin")
def training_status(): return jsonify(train=TRAIN, **training_counts(db()))

@app.post("/api/admin/train")
@need("admin")
def train_start():
    d = request.json or {}; kind = d.get("kind", "sentiment")
    if kind not in ("sentiment", "price"): return jsonify(error="kind must be sentiment or price"), 400
    if not _tlock.acquire(blocking=False): return jsonify(error="A training job is already running"), 409
    try:
        tmp = tempfile.mkdtemp()
        if d.get("csv"):
            if len(d["csv"]) > 25_000_000: raise ValueError("CSV is too large (25 MB max)")
            path = os.path.join(tmp, re.sub(r"[^\w.-]", "_", d.get("filename") or f"{kind}_upload.csv")[:60])
            open(path, "w", encoding="utf-8").write(d["csv"])
        elif kind == "sentiment":
            rows = db().execute("SELECT text, rating FROM training_reviews").fetchall()
            if len(rows) < 200: raise ValueError(f"Only {len(rows)} collected reviews: at least 200 are needed (with both positive and negative ones)")
            path = os.path.join(tmp, "collected_reviews.csv")
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(["Score", "Text"]); w.writerows([(r["rating"], r["text"]) for r in rows])
        else: raise ValueError("Upload a products CSV to train the price model")
    except ValueError as e: _tlock.release(); return jsonify(error=str(e)), 400
    except Exception: _tlock.release(); raise
    TRAIN.update(state="running", task=kind, message="Starting ...")
    threading.Thread(target=_train_thread, args=(kind, path), daemon=True).start()
    return jsonify(started=True)

@app.errorhandler(Exception)
def on_error(e):                                # always answer API errors in JSON, never HTML
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException): return jsonify(error=e.description), e.code
    app.logger.exception(e); return jsonify(error="server error: " + str(e)), 500

init()
if __name__ == "__main__":
    app.run(debug=True)
