import os, tempfile
os.environ["ECOM_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
import app as A, ml

def client(): return A.app.test_client()

def test_sentiment_negation_and_aspects():
    assert ml.analyze_review("Not good at all, waste of money")["sentiment"] == "Negative"
    r = ml.analyze_review("Great quality but late delivery")
    assert r["aspects"]["delivery"] == "Negative"

def test_fake_detection():
    assert ml.analyze_review("GREAT!!!!!")["suspicious"]
    assert "rating does not match text" in ml.analyze_review("worst purchase ever, totally disappointed", rating=5)["flags"]

def test_price_and_forecast():
    r = ml.predict_price("Electronics", 1000, 1500, 4.2, .8, 50)
    assert r["fair_price"] > 1000 and r["profit_optimal_price"] > 1000
    assert ml.forecast_prices(list(range(100, 130)))["trend"] == "rising"

def test_full_shopping_flow():
    c = client()
    assert c.post("/api/register", json={"name": "Ravi", "email": "r@x.com", "password": "secret1"}).status_code == 200
    assert c.get("/api/cart").status_code == 401
    c.post("/api/login", json={"email": "r@x.com", "password": "secret1"})
    c.post("/api/cart", json={"product_id": 1, "qty": 2})
    o = c.post("/api/checkout").get_json(); assert o["total"] > 0
    assert c.post("/api/reviews", json={"product_id": 1, "rating": 5, "text": "Excellent earbuds, great sound and fast delivery"}).get_json()["sentiment"] == "Positive"
    assert c.get("/api/products/1").get_json()["similar"]
    assert c.get("/api/admin/stats").status_code == 403

def test_admin():
    c = client(); c.post("/api/login", json={"email": "admin@shop.com", "password": "admin123"})
    s = c.get("/api/admin/stats").get_json(); assert s["orders"] >= 1
    assert "fair_price" in c.post("/api/predict_price", json={"category": "Home", "cost": 300, "competitor_price": 600, "rating": 4, "demand": .5, "stock": 100}).get_json()

def test_predict_validation():
    c = client(); c.post("/api/login", json={"email": "admin@shop.com", "password": "admin123"})
    ok = {"category": "Home", "cost": "300", "competitor_price": "600", "rating": "4", "demand": "0.5", "stock": "50"}
    assert c.post("/api/predict_price", json={**ok, "stock": "50.5"}).status_code == 200
    r = c.post("/api/predict_price", json={**ok, "cost": ""})
    assert r.status_code == 400 and "error" in r.get_json()

SAMPLE = """<html><head><title>Cool Phone</title><script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Cool Phone",
"aggregateRating":{"@type":"AggregateRating","ratingValue":"4.3","reviewCount":"120"},"review":[
{"@type":"Review","reviewRating":{"ratingValue":5},"author":{"name":"Raj"},"reviewBody":"Excellent phone, great battery and fast delivery"},
{"@type":"Review","reviewRating":{"ratingValue":1},"author":"Sam","reviewBody":"Worst purchase, stopped working after a week"}]}</script></head>
<body><div itemprop="reviewBody">Not worth the money, very disappointed with the build</div></body></html>"""

def test_prediction_has_chart_data():
    r = ml.predict_price("Home", 300, 600, 4, .5, 100)
    assert len(r["curve"]["prices"]) == len(r["curve"]["profit"]) == 80 and r["comparison"]["optimal"] == r["profit_optimal_price"]

def test_link_review_extraction_and_api(monkeypatch=None):
    import reviewtools as rt
    ex = rt.extract(SAMPLE)
    assert len(ex["reviews"]) == 3 and ex["site_rating"] == 4.3 and ex["title"] == "Cool Phone"
    old = rt.fetch_url; rt.fetch_url = lambda u: SAMPLE
    try:
        r = client().post("/api/fetch_reviews", json={"url": "shop.example.com/p/1"}).get_json()
    finally: rt.fetch_url = old
    assert r["count"] == 3 and r["sentiment"].get("Negative", 0) >= 2 and "reviews" in r

def test_no_reviews_page_gives_helpful_note():
    import reviewtools as rt
    old = rt.fetch_url; rt.fetch_url = lambda u: "<html><body>hello</body></html>"
    try: r = client().post("/api/fetch_reviews", json={"url": "https://example.com"}).get_json()
    finally: rt.fetch_url = old
    assert r["count"] == 0 and "paste" in r["note"].lower()

def test_ssrf_blocked():
    import reviewtools as rt
    for bad in ["http://127.0.0.1:5000/", "http://localhost/", "http://192.168.1.1/", "http://169.254.169.254/", "file:///etc/passwd"]:
        try: rt.fetch_url(bad); assert False, bad
        except ValueError: pass
    assert client().post("/api/fetch_reviews", json={"url": "http://127.0.0.1:5000"}).status_code == 400

def test_bulk_and_exports():
    c = client()
    r = c.post("/api/analyze_bulk", json={"reviews": ["Great product, love it", {"text": "Terrible, waste of money", "rating": 1}]}).get_json()
    assert r["count"] == 2 and r["rating_hist"]["1"] == 1
    assert c.get("/api/export/products.csv").status_code in (401, 403)
    c.post("/api/login", json={"email": "admin@shop.com", "password": "admin123"})
    for k in ["products", "orders", "reviews", "price_history", "predictions"]:
        resp = c.get(f"/api/export/{k}.csv"); assert resp.status_code == 200 and "text/csv" in resp.mimetype
    assert len(c.get("/api/export/products.csv").get_data(as_text=True).splitlines()) > 40

def test_demo_data_is_rich():
    s = client(); s.post("/api/login", json={"email": "admin@shop.com", "password": "admin123"})
    st = s.get("/api/admin/stats").get_json()
    assert st["orders"] >= 100 and len(st["revenue_by_day"]) >= 20 and len(st["category_sales"]) == 5

def test_pricing_optimizer():
    c = client(); c.post("/api/login", json={"email": "admin@shop.com", "password": "admin123"})
    r = c.get("/api/admin/pricing").get_json()
    assert len(r["rows"]) >= 40 and all(abs(x["change_pct"]) <= 15.1 and x["suggested"] >= x["cost"] for x in r["rows"])
    assert c.post("/api/admin/pricing/apply", json={"ids": [1]}).get_json()["applied"] in (0, 1)
    assert client().get("/api/admin/pricing").status_code == 401

def test_train_on_csv_and_model_lab():
    """Pipeline test on GENERATED csv files shaped like Kaggle datasets (not real data)."""
    import csv, tempfile, random, json, train
    d = tempfile.mkdtemp(); X, y = ml._corpus(900)
    with open(f"{d}/reviews.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["Id", "Score", "Text"])
        for i, (t, l) in enumerate(zip(X, y)): w.writerow([i, {1: 5, 0: 1, 2: 3}[l], t])
    rnd = random.Random(3)
    with open(f"{d}/products.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["name", "main_category", "ratings", "no_of_ratings", "discount_price", "actual_price"])
        for i in range(900):
            mrp = rnd.uniform(500, 20000); rt = rnd.uniform(3, 5)
            w.writerow([f"p{i}", rnd.choice(["tv", "shoes", "bags"]), "Get" if i % 50 == 0 else round(rt, 1), f"{rnd.randint(5, 5000):,}", f"\u20b9{mrp * (0.5 + 0.08 * (rt - 3)):,.0f}", f"\u20b9{mrp:,.0f}"])
    try:
        s = train.train_sentiment(f"{d}/reviews.csv", out=d); p = train.train_price(f"{d}/products.csv", out=d)
        assert s["best_model"] in s["comparison"] and len(s["confusion"]) == 3 and p["comparison"][p["best_model"]]["r2"] > .5
        ml.load_real_models(d); assert ml.MODEL_SOURCE["sentiment"] == "reviews.csv"
        assert ml.analyze_review("Terrible, waste of money")["sentiment"] == "Negative"
        c = client(); c.post("/api/login", json={"email": "admin@shop.com", "password": "admin123"})
        rep = c.get("/api/admin/model_report").get_json(); assert rep["sentiment"] and rep["price"] and rep["cats"]
        e = c.post("/api/admin/real_price", json={"category": rep["cats"][0], "mrp": 5000, "rating": 4.2, "n_ratings": 300}).get_json()
        assert 0 < e["estimate"] < 5000
        if os.environ.get("DUMP_LAB"): json.dump({"rep": rep, "est": e}, open("/tmp/fx_lab.json", "w"))
    finally: ml.load_real_models(tempfile.mkdtemp())
    assert ml.MODEL_SOURCE["sentiment"] == "synthetic demo data" and client().get("/api/admin/model_report").status_code == 401

def test_payments_and_order_tracking():
    import payments
    assert payments.charge("CARD", 100, {"number": "4242 4242 4242 4242", "expiry": "12/40", "cvv": "123"})["ok"]
    for bad in [{"number": "4242424242424241", "expiry": "12/40", "cvv": "123"}, {"number": "4000000000000002", "expiry": "12/40", "cvv": "123"},
                {"number": "4242424242424242", "expiry": "01/20", "cvv": "123"}]:
        assert not payments.charge("CARD", 100, bad)["ok"]
    assert payments.charge("UPI", 1, {"vpa": "ab@upi"})["ok"] and not payments.charge("UPI", 1, {"vpa": "fail@upi"})["ok"]
    c = client(); c.post("/api/register", json={"name": "P", "email": "pay@x.com", "password": "secret1"}); c.post("/api/login", json={"email": "pay@x.com", "password": "secret1"})
    c.post("/api/cart", json={"product_id": 2, "qty": 1})
    r = c.post("/api/checkout", json={"method": "CARD", "details": {"number": "4000000000000002", "expiry": "12/40", "cvv": "123"}})
    assert r.status_code == 402 and c.get("/api/cart").get_json()["items"] and not c.get("/api/orders").get_json()      # failed payment keeps cart, no order
    r = c.post("/api/checkout", json={"method": "UPI", "details": {"vpa": "me@upi"}}).get_json(); oid = r["order_id"]
    assert r["payment_status"] == "Paid" and c.get("/api/orders").get_json()[0]["status"] == "Placed"
    a = client(); a.post("/api/login", json={"email": "admin@shop.com", "password": "admin123"})
    stock = lambda: a.get("/api/products/2").get_json()["product"]["stock"]; s0 = stock()
    assert c.put(f"/api/admin/orders/{oid}/status", json={"status": "Packed"}).status_code == 403
    for st in ["Packed", "Shipped"]: assert a.put(f"/api/admin/orders/{oid}/status", json={"status": st}).status_code == 200
    assert a.put(f"/api/admin/orders/{oid}/status", json={"status": "Placed"}).status_code == 409
    assert a.put(f"/api/admin/orders/{oid}/status", json={"status": "Cancelled"}).status_code == 200 and stock() == s0 + 1   # restocked
    o = c.get("/api/orders").get_json()[0]; assert o["status"] == "Cancelled" and o["payment_status"] == "Refunded" and len(o["events"]) == 4

def test_also_bought_and_competitor_prices():
    assert ml.also_bought(1, [{1, 2}, {1, 2, 3}, {3, 4}]) [0] == 2
    a = client(); a.post("/api/login", json={"email": "admin@shop.com", "password": "admin123"})
    assert "also_bought" in a.get("/api/products/1").get_json()
    assert a.put("/api/admin/products/1/competitor", json={"price": 2100}).status_code == 200 and a.put("/api/admin/products/1/competitor", json={"price": -5}).status_code == 400
    assert a.post("/api/admin/competitor_csv", json={"rows": [{"name": "smart watch", "competitor_price": "3300"}, {"name": "nope", "competitor_price": "1"}]}).get_json()["updated"] == 1
    rows = {r["id"]: r for r in a.get("/api/admin/pricing").get_json()["rows"]}
    assert rows[1]["competitor"] == 2100 and rows[1]["competitor_source"] == "real" and rows[2]["competitor_source"] == "simulated"

def test_razorpay_flow_and_security():
    import hmac, hashlib, razorpay_gateway as rzp
    os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"] = "rzp_test_x", "sec123"
    sig = lambda o, p: hmac.new(b"sec123", f"{o}|{p}".encode(), hashlib.sha256).hexdigest()
    old = rzp.create_order; rzp.create_order = lambda amt, rec: {"id": "order_T1", "amount": int(round(amt * 100))}
    try:
        c = client(); c.post("/api/register", json={"name": "R", "email": "rz@x.com", "password": "secret1"}); c.post("/api/login", json={"email": "rz@x.com", "password": "secret1"})
        assert c.get("/api/pay/config").get_json()["mode"] == "razorpay"
        c.post("/api/cart", json={"product_id": 3, "qty": 1}); o = c.post("/api/pay/create").get_json(); assert o["order_id"] == "order_T1" and o["amount"] > 0
        bad = c.post("/api/pay/verify", json={"razorpay_order_id": "order_T1", "razorpay_payment_id": "pay_1", "razorpay_signature": "forged"})
        assert bad.status_code == 400 and not c.get("/api/orders").get_json()                       # forged signature -> no order
        ok = c.post("/api/pay/verify", json={"razorpay_order_id": "order_T1", "razorpay_payment_id": "pay_1", "razorpay_signature": sig("order_T1", "pay_1")}).get_json()
        assert ok["payment_status"] == "Paid" and c.get("/api/orders").get_json()[0]["payment_method"] == "Razorpay"
        assert c.post("/api/pay/verify", json={"razorpay_order_id": "order_T1", "razorpay_payment_id": "pay_1", "razorpay_signature": sig("order_T1", "pay_1")}).status_code == 400   # replay blocked
        other = client(); other.post("/api/login", json={"email": "demo1@shop.com", "password": "demo123"})
        assert other.post("/api/pay/verify", json={"razorpay_order_id": "order_T1", "razorpay_payment_id": "pay_1", "razorpay_signature": sig("order_T1", "pay_1")}).status_code == 400  # other user blocked
    finally:
        rzp.create_order = old; os.environ.pop("RAZORPAY_KEY_ID"); os.environ.pop("RAZORPAY_KEY_SECRET")
    assert client().get("/api/pay/config").get_json()["mode"] == "demo"

def test_name_search_suggestions_and_sources():
    import reviewtools as rt
    assert rt._clean(rt._ddg_links('<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fshop.example.com%2Fp%2F1&rut=x">a</a><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.youtube.com%2Fw">b</a>')) == ["https://shop.example.com/p/1"]
    old = (rt.find_pages, rt.fetch_url); rt.find_pages = lambda q: ["https://shop.example.com/p/1", "https://other.example.org/x"]; rt.fetch_url = lambda u: SAMPLE
    try: r = client().post("/api/search_reviews", json={"query": "Cool Phone"}).get_json()
    finally: rt.find_pages, rt.fetch_url = old
    assert r["count"] == 3 and r["sources"][0][0] == "shop.example.com" and r["suggestions"] and "complaint_words" in r
    s = rt.summarize([{"text": "Delivery was very late and packaging damaged", "rating": 1}] * 4 + [{"text": "Great quality, love it, works perfectly", "rating": 5}] * 2)
    assert {x["for"] for x in s["suggestions"]} == {"buyer", "seller"} and any("Delivery" in x["text"] or "delivery" in x["text"] for x in s["suggestions"])
    assert client().post("/api/search_reviews", json={"query": "x"}).status_code == 400

def test_single_review_chart_fields():
    r = ml.analyze_review("Great quality but late delivery", 4)
    assert abs(sum(r["probabilities"].values()) - 1) < .01 and r["aspect_scores"]["delivery"] < 0 < r["aspect_scores"]["quality"] and "great" in r["pos_words"] and "late" in r["neg_words"]

def test_collect_and_train_inside_app():
    import tempfile, time
    ml.MODELS_DIR = tempfile.mkdtemp(); X, y = ml._corpus(2500); seen, rows = set(), []
    for t_, l in zip(X, y):
        if t_ not in seen and l != 2: seen.add(t_); rows.append({"text": t_, "rating": 5 if l == 1 else 1})
    c = client(); assert c.post("/api/admin/training/add", json={"reviews": rows[:5]}).status_code == 401
    c.post("/api/login", json={"email": "admin@shop.com", "password": "admin123"})
    assert c.post("/api/admin/train", json={"kind": "sentiment"}).status_code == 400               # too few reviews yet
    for i in range(0, 600, 300): r = c.post("/api/admin/training/add", json={"reviews": rows[i:i + 300]}).get_json()
    assert r["total"] >= 300 and set(r["counts"]) == {"Positive", "Negative"}
    try:
        assert c.post("/api/admin/train", json={"kind": "sentiment"}).get_json()["started"]
        for _ in range(120):
            s = c.get("/api/admin/training/status").get_json()["train"]
            if s["state"] != "running": break
            time.sleep(.5)
        assert s["state"] == "done", s
        assert ml.MODEL_SOURCE["sentiment"] == "collected_reviews.csv" and ml.analyze_review("Terrible, waste of money")["sentiment"] == "Negative"
        assert c.get("/api/admin/model_report").get_json()["sentiment"]["rows"] >= 300
    finally: ml.load_real_models(tempfile.mkdtemp())
    assert c.post("/api/admin/train", json={"kind": "price"}).status_code == 400
