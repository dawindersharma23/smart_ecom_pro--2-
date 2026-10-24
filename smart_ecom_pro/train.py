"""Train the AI models on REAL datasets (CSV).
   python train.py sentiment data/Reviews.csv      # reviews: text column + rating/label column
   python train.py price data/products.csv         # products: selling price, MRP, rating, no. of ratings, category
Columns are auto-detected (Amazon Fine Food Reviews / Amazon & Flipkart product datasets style); override: --text COL --label COL"""
import csv, json, os, random, re, joblib, numpy as np
from collections import Counter
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, mean_absolute_error, precision_recall_fscore_support, r2_score
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import make_pipeline
import ml

OUT = ml.MODELS_DIR; csv.field_size_limit(10 ** 7)
TEXT = ["text", "reviewtext", "review", "content", "comment", "body", "reviewbody", "reviews", "summary"]
RATING = ["score", "rating", "stars", "overall", "reviewrating", "ratings", "rate"]; LABEL = ["sentiment", "label", "class", "polarity"]
PRICE = ["discountprice", "saleprice", "sellingprice", "offerprice", "price"]; MRP = ["actualprice", "mrp", "originalprice", "listprice"]
RAT = ["ratings", "rating", "stars", "averagerating"]; CNT = ["noofratings", "ratingcount", "reviewcount", "numratings", "reviews", "ratingscount"]
CATS = ["maincategory", "category", "subcategory"]

def _find(cols, names):
    norm = {re.sub(r"[^a-z]", "", c.lower()): c for c in cols}
    return next((norm[n] for n in names if n in norm), None)

def _num(s):
    x = re.sub(r"[^\d.]", "", str(s or "")); return float(x) if x and x != "." else None

def load_reviews(path, text_col=None, label_col=None, cap=120000):
    rows, seen, rnd = [], 0, random.Random(1)
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rd = csv.DictReader(f); cols = rd.fieldnames or []
        tc = text_col or _find(cols, TEXT); rc = label_col or _find(cols, RATING + LABEL)
        if not tc or not rc: raise SystemExit(f"Could not detect the columns. The file has: {cols}. Pass them with --text and --label.")
        is_rating = _find([rc], RATING) is not None
        for r in rd:
            t = (r.get(tc) or "").strip(); v = (r.get(rc) or "").strip().lower()
            if len(t) < 5: continue
            if is_rating:
                x = _num(v); y = None if x is None else 1 if x >= 4 else 0 if x <= 2 else 2
            else: y = {"positive": 1, "pos": 1, "1": 1, "negative": 0, "neg": 0, "0": 0, "neutral": 2, "neu": 2, "2": 2}.get(v)
            if y is None: continue
            seen += 1; item = (t[:1000], y)
            if len(rows) < cap: rows.append(item)
            else:
                j = rnd.randrange(seen)                      # reservoir sampling keeps memory small for huge files
                if j < cap: rows[j] = item
    return rows

def train_sentiment(path, text_col=None, label_col=None, out=OUT):
    rows = load_reviews(path, text_col, label_col); X = [r[0] for r in rows]; y = [r[1] for r in rows]
    if len(rows) < 200 or not {0, 1} <= set(y): raise SystemExit("At least 200 reviews are needed, including both positive and negative ones")
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=.2, random_state=1, stratify=y)
    cands = {"LogisticRegression": LogisticRegression(max_iter=300, C=3, class_weight="balanced"), "MultinomialNB": MultinomialNB(alpha=.5)}
    res, best = {}, None
    for n, clf in cands.items():
        p = make_pipeline(TfidfVectorizer(preprocessor=ml._prep, ngram_range=(1, 2), min_df=2, max_features=200000, sublinear_tf=True), clf).fit(Xtr, ytr)
        pr = p.predict(Xte); f1 = f1_score(yte, pr, average="macro")
        res[n] = {"accuracy": round(accuracy_score(yte, pr), 4), "macro_f1": round(f1, 4)}
        if not best or f1 > best[0]: best = (f1, n, p, pr)
    _, name, pipe, pr = best; labels = sorted(set(y)); nm = {0: "Negative", 1: "Positive", 2: "Neutral"}
    a, b, c, d = precision_recall_fscore_support(yte, pr, labels=labels, zero_division=0)
    rep = {"task": "sentiment", "dataset": os.path.basename(path), "rows": len(rows), "train": len(Xtr), "test": len(Xte), "best_model": name,
           "comparison": res, "classes": [nm[l] for l in labels], "confusion": confusion_matrix(yte, pr, labels=labels).tolist(),
           "class_balance": {nm[l]: y.count(l) for l in labels},
           "per_class": [{"class": nm[l], "precision": round(float(p_), 3), "recall": round(float(r_), 3), "f1": round(float(f_), 3), "support": int(s_)} for l, p_, r_, f_, s_ in zip(labels, a, b, c, d)]}
    os.makedirs(out, exist_ok=True); joblib.dump(pipe, os.path.join(out, "sentiment.joblib")); json.dump(rep, open(os.path.join(out, "sentiment_report.json"), "w"), indent=1)
    return rep

def train_price(path, out=OUT):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        rd = csv.DictReader(f); cols = rd.fieldnames or []
        cp, cm, cr, cn, cc = (_find(cols, n) for n in (PRICE, MRP, RAT, CNT, CATS))
        if not cp: raise SystemExit(f"No price column found. The file has: {cols}")
        rows = []
        for r in rd:
            p = _num(r.get(cp)); mrp = _num(r.get(cm)) if cm else None
            if not p or p <= 0 or (cm and (not mrp or mrp <= 0)): continue
            rows.append(((r.get(cc) or "other").strip() if cc else "other", mrp, _num(r.get(cr)) if cr else None, _num(r.get(cn)) or 0, p))
    if len(rows) < 200: raise SystemExit("At least 200 valid products are needed")
    med = float(np.median([r[2] for r in rows if r[2] is not None] or [4.0])); has_mrp = bool(cm)
    top = [c for c, _ in Counter(r[0] for r in rows).most_common(25)]
    feats = ["category"] + (["log_mrp"] if has_mrp else []) + ["rating", "log_ratings"]
    X = np.array([[top.index(r[0]) if r[0] in top else len(top)] + ([np.log1p(r[1])] if has_mrp else []) + [r[2] if r[2] is not None else med, np.log1p(r[3])] for r in rows])
    y = np.array([r[4] for r in rows])
    if len(rows) > 80000: i = np.random.default_rng(1).choice(len(rows), 80000, replace=False); X, y = X[i], y[i]
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=.2, random_state=1)
    cands = {"LinearRegression": LinearRegression(), "RandomForest": RandomForestRegressor(100, max_depth=14, n_jobs=-1, random_state=1),
             "GradientBoosting": GradientBoostingRegressor(n_estimators=150, max_depth=4, random_state=1)}
    res, best = {}, None
    for n, mdl in cands.items():
        mdl.fit(Xtr, np.log1p(ytr)); pr = np.expm1(mdl.predict(Xte)); r2 = r2_score(yte, pr)
        res[n] = {"r2": round(float(r2), 4), "mae": round(float(mean_absolute_error(yte, pr)), 2)}
        if not best or r2 > best[0]: best = (r2, n, mdl, pr)
    _, name, mdl, pr = best; sel = np.random.default_rng(2).choice(len(yte), min(250, len(yte)), replace=False)
    imp = getattr(mdl, "feature_importances_", None)
    rep = {"task": "price", "dataset": os.path.basename(path), "rows": len(rows), "train": len(Xtr), "test": len(Xte), "best_model": name, "comparison": res,
           "importance": {f: round(float(v), 3) for f, v in zip(feats, imp)} if imp is not None else None,
           "scatter": [[round(float(yte[i])), round(float(pr[i]))] for i in sel]}
    os.makedirs(out, exist_ok=True); joblib.dump({"model": mdl, "cats": top, "has_mrp": has_mrp}, os.path.join(out, "price.joblib"))
    json.dump(rep, open(os.path.join(out, "price_report.json"), "w"), indent=1); return rep

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("task", choices=["sentiment", "price"]); ap.add_argument("csv"); ap.add_argument("--text"); ap.add_argument("--label")
    a = ap.parse_args(); rep = train_sentiment(a.csv, a.text, a.label) if a.task == "sentiment" else train_price(a.csv)
    print(json.dumps({k: v for k, v in rep.items() if k not in ("scatter", "confusion")}, indent=1)); print("Saved in models/  ->  restart the app (python app.py)")
