"""AI layer: price prediction + profit optimisation + forecasting, NLP review analysis, recommender."""
import os, re, json, random, joblib
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, LinearRegression
from sklearn.metrics import r2_score, accuracy_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline

CATEGORIES = ["Electronics", "Fashion", "Home", "Books", "Beauty"]
FEATURES = ["category", "cost", "competitor_price", "rating", "demand", "stock"]

# ================= 1. PRICE PREDICTION (Gradient Boosting) =================
def _price_data(n=8000, seed=42):
    r = np.random.default_rng(seed)
    cat = r.integers(0, 5, n)
    cost = r.uniform(100, 5000, n) * (1 + (cat == 0))
    comp = cost * r.uniform(1.1, 1.8, n)
    rating = r.uniform(2.5, 5, n); demand = r.uniform(0, 1, n); stock = r.integers(5, 500, n)
    price = comp * (0.9 + 0.1 * (rating - 3) + 0.15 * demand - 0.0003 * stock) + r.normal(0, cost * 0.02)
    return np.c_[cat, cost, comp, rating, demand, stock], price

_X, _y = _price_data()
_Xtr, _Xte, _ytr, _yte = train_test_split(_X, _y, test_size=0.2, random_state=1)
price_model = GradientBoostingRegressor(n_estimators=200, max_depth=3, random_state=1).fit(_Xtr, _ytr)
PRICE_R2 = round(r2_score(_yte, price_model.predict(_Xte)), 3)
IMPORTANCE = {f: round(float(i), 3) for f, i in zip(FEATURES, price_model.feature_importances_)}

def optimal_price(cost, comp, rating, demand, elasticity=2.0):
    """Pick the price that maximises profit under a constant-elasticity demand curve."""
    base = 100 * (0.5 + demand) * (rating / 4)
    cand = np.linspace(cost * 1.05, max(comp * 1.4, cost * 1.1), 80)
    units = base * (comp / cand) ** elasticity
    profit = (cand - cost) * units
    i = int(np.argmax(profit))
    curve = {"prices": [round(float(x), 2) for x in cand], "units": [round(float(x), 1) for x in units],
             "profit": [round(float(x), 1) for x in profit]}
    return round(float(cand[i]), 2), round(float(units[i]), 1), round(float(profit[i]), 2), curve

def profit_at(price, cost, comp, rating, demand, elasticity=2.0):
    return (price - cost) * 100 * (0.5 + demand) * (rating / 4) * (comp / price) ** elasticity

def predict_price(category, cost, competitor_price, rating, demand, stock):
    row = [[CATEGORIES.index(category), cost, competitor_price, rating, demand, stock]]
    fair = max(float(price_model.predict(row)[0]), cost * 1.05)
    opt, units, profit, curve = optimal_price(cost, competitor_price, rating, demand)
    return {"fair_price": round(fair, 2), "profit_optimal_price": opt, "expected_units": units,
            "expected_profit": profit, "margin_pct": round((fair - cost) / fair * 100, 1),
            "model_r2": PRICE_R2, "feature_importance": IMPORTANCE, "curve": curve,
            "comparison": {"cost": cost, "competitor": competitor_price, "fair": round(fair, 2), "optimal": opt}}

def forecast_prices(history, days=7):
    """Linear-trend forecast of the next `days` prices from a price history list."""
    if len(history) < 5:
        return {"forecast": [], "trend": "insufficient data"}
    t = np.arange(len(history)).reshape(-1, 1)
    lr = LinearRegression().fit(t, history)
    fut = lr.predict(np.arange(len(history), len(history) + days).reshape(-1, 1))
    slope = lr.coef_[0] / np.mean(history) * 100
    return {"forecast": [round(float(x), 2) for x in fut],
            "trend": "rising" if slope > 0.1 else "falling" if slope < -0.1 else "stable"}

# ================= 2. REVIEW ANALYZER (TF-IDF + Logistic Regression) =================
_POS = ["great quality", "love it", "works perfectly", "totally worth the money", "fast delivery", "excellent product",
        "very happy with this", "highly recommend", "amazing value", "good packaging", "superb build", "satisfied with the purchase",
        "not bad at all", "no complaints", "exceeded my expectations", "good support from seller", "worth the price", "very satisfied with it", "happy with the build", "would recommend this", "really good product", "works great"]
_NEG = ["very poor quality", "waste of money", "stopped working", "arrived damaged", "late delivery", "terrible product",
        "totally disappointed", "not worth it", "cheap material", "defective piece", "worst purchase", "want a refund",
        "not good", "not as described", "never buying again", "rude seller and no support", "not worth the money", "not worth the price", "very disappointed with the build", "not happy with it", "not satisfied", "wouldn't recommend this", "not durable at all", "not great", "does not work properly", "poor build quality", "not recommended", "feels cheap and flimsy"]
_NEU = ["it is okay", "average product", "does the job", "nothing special", "as described", "fine for the price"]

_NEG_RE = re.compile(r"\b(?:not|no|never|hardly|without)\s+(?:(?:very|so|too|really|that|at all)\s+)?([a-z]+)")

def _prep(text):
    t = text.lower().replace("n't", " not").replace("cannot", "can not")
    return _NEG_RE.sub(lambda mo: "neg_" + mo.group(1), t)

def _corpus(n=3000, seed=7):
    rnd = random.Random(seed); X, y = [], []
    for _ in range(n):
        lab = rnd.choice([0, 1, 2]); pool = [_NEG, _POS, _NEU][lab]
        parts = rnd.sample(pool, rnd.randint(1, 3))
        if lab != 2 and rnd.random() < .25: parts.append(rnd.choice(_NEU))
        rnd.shuffle(parts); X.append(", ".join(parts)); y.append(lab)
    return X, y

def train_sentiment(X=None, y=None):
    """Retrain on your own data, e.g. an Amazon/Flipkart reviews CSV (labels: 0 neg, 1 pos, 2 neutral)."""
    if X is None: X, y = _corpus()
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=3)
    m = make_pipeline(TfidfVectorizer(preprocessor=_prep, ngram_range=(1, 3), sublinear_tf=True), LogisticRegression(max_iter=500)).fit(Xtr, ytr)
    return m, round(accuracy_score(yte, m.predict(Xte)), 3)

sent_model, SENT_ACC = train_sentiment()

_LEX_P = set("good great excellent amazing awesome love perfect best nice fast smooth happy superb durable recommend satisfied".split())
_LEX_N = set("bad poor worst terrible awful hate slow broken defective waste fake cheap late damaged disappointed useless refund problem".split())

def _lex(text):
    tk = re.findall(r"[a-z']+", text.lower().replace("n't", " not")); s = 0
    for i, t in enumerate(tk):
        v = 1 if t in _LEX_P else -1 if t in _LEX_N else 0
        if v and any(p in ("not", "no", "never") for p in tk[max(0, i - 2):i]): v = -v
        s += v
    return np.tanh(s / (len(tk) ** .5 + 1e-9)) if tk else 0.0

def _score(text):
    p = dict(zip(sent_model.classes_, sent_model.predict_proba([text])[0]))
    return 0.7 * (p[1] - p[0]) + 0.3 * _lex(text)

def _label(s): return "Positive" if s > 0.2 else "Negative" if s < -0.2 else "Neutral"

ASPECTS = {"quality": ["quality", "build", "material", "durable", "defective", "broken", "working"],
           "delivery": ["delivery", "shipping", "late", "courier", "packaging", "damaged", "arrived"],
           "price": ["price", "value", "worth", "expensive", "cheap", "money"],
           "service": ["service", "support", "refund", "return", "seller"]}

def analyze_review(text, rating=None, existing_texts=()):
    s = _score(text); nm = {0: "Negative", 1: "Positive", 2: "Neutral"}
    pr = dict(zip(sent_model.classes_, sent_model.predict_proba([text])[0])); tk0 = re.findall(r"[a-z']+", text.lower())
    out = {"sentiment": _label(s), "score": round(float(s), 2), "aspects": {}, "aspect_scores": {},
           "probabilities": {nm[int(k)]: round(float(v), 3) for k, v in pr.items()},
           "pos_words": sorted({w for w in tk0 if w in _LEX_P}), "neg_words": sorted({w for w in tk0 if w in _LEX_N})}
    clauses = re.split(r"[.!?;,]| but ", text)
    for a, words in ASPECTS.items():
        hit = [c for c in clauses if any(w in c.lower() for w in words)]
        if hit: sc = _score(" ".join(hit)); out["aspects"][a] = _label(sc); out["aspect_scores"][a] = round(float(sc), 2)
    flags = []; tk = text.lower().split()
    if len(tk) < 4: flags.append("too short")
    if text.count("!") >= 4: flags.append("excess exclamation")
    if tk and len(set(tk)) / len(tk) < .5: flags.append("repetitive words")
    if sum(c.isupper() for c in text) > .5 * max(len(text), 1): flags.append("all caps")
    if existing_texts and len(text) > 15:                       # duplicate / copy-paste detection
        v = TfidfVectorizer().fit(list(existing_texts) + [text])
        sim = cosine_similarity(v.transform([text]), v.transform(list(existing_texts))).max()
        if sim > .9: flags.append("duplicate of existing review")
    if rating is not None and ((rating >= 4 and out["sentiment"] == "Negative") or (rating <= 2 and out["sentiment"] == "Positive")):
        flags.append("rating does not match text")
    out.update(suspicious=bool(flags), flags=flags)
    return out

# ================= 3. RECOMMENDER (content based) =================
def recommend(pid, products, k=3):
    docs = [f"{p['name']} {p['category']} {p['description']}" for p in products]
    ids = [p["id"] for p in products]
    if pid not in ids or len(ids) < 2: return []
    m = TfidfVectorizer(stop_words="english").fit_transform(docs)
    sims = cosine_similarity(m[ids.index(pid)], m)[0]
    order = [i for i in np.argsort(-sims) if ids[i] != pid][:k]
    return [ids[i] for i in order]

def also_bought(pid, baskets, k=3):
    """Item-item collaborative filtering: products bought together with `pid` (cosine on co-purchase counts)."""
    from collections import Counter
    co, n = Counter(), Counter()
    for b in baskets:
        for x in b: n[x] += 1
        if pid in b:
            for x in b:
                if x != pid: co[x] += 1
    return [x for x, _ in sorted(co.items(), key=lambda kv: -kv[1] / (n[pid] * n[kv[0]]) ** .5)[:k]]

# ================= 4. REAL-DATA MODELS (created by train.py, loaded automatically) =================
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
MODEL_SOURCE = {"sentiment": "synthetic demo data", "price": "synthetic demo data"}
REAL = {}; _SYNTH = (sent_model, SENT_ACC)

def load_real_models(d=None):
    global sent_model, SENT_ACC, MODELS_DIR
    MODELS_DIR = d or MODELS_DIR; sent_model, SENT_ACC = _SYNTH; REAL.clear()
    MODEL_SOURCE.update(sentiment="synthetic demo data", price="synthetic demo data")
    j = lambda f: os.path.join(MODELS_DIR, f)
    if os.path.exists(j("sentiment.joblib")) and os.path.exists(j("sentiment_report.json")):
        rep = json.load(open(j("sentiment_report.json"))); sent_model = joblib.load(j("sentiment.joblib"))
        SENT_ACC = rep["comparison"][rep["best_model"]]["accuracy"]; MODEL_SOURCE["sentiment"] = rep["dataset"]
    if os.path.exists(j("price.joblib")) and os.path.exists(j("price_report.json")):
        REAL["price"] = joblib.load(j("price.joblib")); MODEL_SOURCE["price"] = json.load(open(j("price_report.json")))["dataset"]

def real_price_estimate(category, mrp, rating, n_ratings):
    r = REAL.get("price")
    if not r: return None
    ci = r["cats"].index(category) if category in r["cats"] else len(r["cats"])
    row = [ci] + ([float(np.log1p(mrp))] if r["has_mrp"] else []) + [rating, float(np.log1p(n_ratings))]
    return round(float(np.expm1(r["model"].predict([row])[0])), 2)

load_real_models()
