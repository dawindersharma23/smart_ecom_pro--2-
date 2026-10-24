"""Fetch reviews from a product/company link + summarise any list of reviews."""
import os, re, json, html, socket, ipaddress, urllib.request, urllib.parse
import concurrent.futures as cf
from collections import Counter
from html.parser import HTMLParser
import ml

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# ---------- safe fetching (blocks localhost / private networks = SSRF protection) ----------
def _safe(url):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Only http/https links are allowed")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError("Could not resolve this link's domain (check the link and your internet connection)")
    for i in infos:
        try: ok = ipaddress.ip_address(i[4][0]).is_global
        except ValueError: ok = False
        if not ok: raise ValueError("Private or local addresses are not allowed")
    return url

class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _safe(newurl)                                   # re-check every redirect hop
        return super().redirect_request(req, fp, code, msg, headers, newurl)

_opener = urllib.request.build_opener(_Redirect)

def fetch_url(url):
    _safe(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en-IN,en;q=0.9"})
    with _opener.open(req, timeout=12) as r:
        ctype = r.headers.get("Content-Type", ""); data = r.read(2_000_000)
    m = re.search(r"charset=([\w-]+)", ctype)
    try: return data.decode(m.group(1) if m else "utf-8", "replace")
    except LookupError: return data.decode("utf-8", "replace")

# ---------- extraction ----------
ENTITY = {"Product", "Organization", "LocalBusiness", "Store", "SoftwareApplication", "Course", "Book", "Restaurant", "Service"}
KEYS = ["reviewbody", "review-text", "review-body", "reviewtext", "review_text", "review-content", "review__text", "review-comment", "user-review"]
VOID = {"br", "img", "input", "meta", "link", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}

class _Parser(HTMLParser):
    def __init__(s):
        super().__init__(); s.cur = None; s.depth = 0; s.out = []; s.title = ""; s.in_title = False; s.skip = 0
    def handle_starttag(s, tag, attrs):
        a = dict(attrs)
        if tag == "title": s.in_title = True
        if tag in ("script", "style"): s.skip += 1
        if tag in VOID: return
        if s.cur is not None: s.depth += 1
        else:
            sig = " ".join([a.get("itemprop") or "", a.get("class") or "", a.get("data-hook") or ""]).lower()
            if any(k in sig for k in KEYS): s.cur = []; s.depth = 0
    def handle_endtag(s, tag):
        if tag == "title": s.in_title = False
        if tag in ("script", "style"): s.skip = max(0, s.skip - 1)
        if tag in VOID: return
        if s.cur is not None:
            if s.depth == 0:
                t = " ".join("".join(s.cur).split())
                if len(t) >= 15: s.out.append(t)
                s.cur = None
            else: s.depth -= 1
    def handle_data(s, d):
        if s.in_title: s.title += d
        if s.cur is not None and not s.skip: s.cur.append(d)

def _walk(o, out):
    if isinstance(o, list):
        for x in o: _walk(x, out)
    elif isinstance(o, dict):
        t = o.get("@type"); t = t if isinstance(t, list) else [t]
        if "Review" in t: out["reviews"].append(o)
        if any(x in ENTITY for x in t if isinstance(x, str)): out.setdefault("entity", o)
        for v in o.values(): _walk(v, out)

def _num(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def extract(page):
    out = {"reviews": []}
    for blob in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        try: _walk(json.loads(blob.strip()), out)
        except ValueError: pass
    rows, seen = [], set()
    for r in out["reviews"]:
        text = html.unescape(str(r.get("reviewBody") or r.get("description") or "")).strip()
        rt = r.get("reviewRating"); rating = _num(rt.get("ratingValue")) if isinstance(rt, dict) else _num(rt)
        if len(text) >= 5 and text.lower() not in seen:
            seen.add(text.lower()); rows.append({"text": text, "rating": rating})
    p = _Parser(); 
    try: p.feed(page)
    except Exception: pass
    for t in p.out:
        t = html.unescape(t)
        if t.lower() not in seen: seen.add(t.lower()); rows.append({"text": t, "rating": None})
    ent = out.get("entity") or {}; agg = ent.get("aggregateRating") if isinstance(ent, dict) else None
    agg = agg if isinstance(agg, dict) else {}
    return {"title": html.unescape(str(ent.get("name") or p.title or "")).strip()[:120],
            "site_rating": _num(agg.get("ratingValue")), "site_count": agg.get("reviewCount") or agg.get("ratingCount"),
            "reviews": rows[:150]}

# ---------- summary ----------
STOP = set("this that with have from they were been very just also your what when which their there than then them about would could really one the and for was are but not you all can had has its too out get got".split())

ADV = {"quality": ("There are quality complaints: check the specs and warranty carefully.", "Tighten quality control and supplier checks; inspect for defective pieces."),
       "delivery": ("Buyers report late delivery or damaged packaging: check the estimated date and the seller's rating.", "Improve the courier partner and packaging, and set realistic delivery estimates."),
       "price": ("Many buyers find it expensive: compare prices of alternatives.", "Rethink value for money: adjust the price or offer a bundle/discount."),
       "service": ("There are seller-support complaints: read the return/refund policy first.", "Speed up support response time and the refund process.")}

def suggestions(s):
    n = s["count"]
    if not n: return []
    pos = s["sentiment"].get("Positive", 0) / n; neg = s["sentiment"].get("Negative", 0) / n; sus = s["suspicious"] / n; out = []
    B = lambda t: out.append({"for": "buyer", "text": t}); S = lambda t: out.append({"for": "seller", "text": t})
    if pos >= .7 and sus <= .2: B("👍 Reviews are mostly positive; buying looks safe.")
    elif neg >= .4: B("⚠️ 40%+ of reviews are negative: check the return policy and warranty before buying, or look at alternatives.")
    else: B("🤔 Reviews are mixed: read the negative ones and see whether the complaints matter for your use.")
    if sus > .3: B("🕵️ 30%+ of reviews look suspicious: don't rely on the star rating alone; read the detailed reviews.")
    for a, d in s["aspects"].items():
        t = sum(d.values())
        if a in ADV and t >= 2 and d.get("Negative", 0) / t >= .4: B("📌 " + ADV[a][0]); S("🔧 " + ADV[a][1])
        elif t >= 3 and d.get("Positive", 0) / t >= .7: S(f"✅ '{a}' is a strength; highlight it in your marketing.")
    if s.get("complaint_words") and neg >= .15: S("🗣️ These words keep appearing in negative reviews: " + ", ".join(w for w, _ in s["complaint_words"][:5]) + ". Fix these first.")
    if s.get("site_rating") and s.get("avg_rating") and abs(s["site_rating"] - s["avg_rating"]) >= .7: B(f"ℹ️ The site's rating ({s['site_rating']}) and the average of the extracted reviews ({s['avg_rating']}) differ: the sample may be small or biased.")
    if n < 10: B(f"ℹ️ Only {n} reviews found, so the result is not reliable.")
    return out

def extras(res, s):
    words = lambda lab: Counter(w for r in res if r["sentiment"] == lab for w in re.findall(r"[a-z]{4,}", r["text"].lower()) if w not in STOP).most_common(8)
    d = {"complaint_words": words("Negative"), "praise_words": words("Positive")}
    return {**d, "suggestions": suggestions({**s, **d})}

# ---------- product NAME -> review pages ----------
SKIP_HOSTS = ("google.", "bing.", "duckduckgo.", "youtube.", "facebook.", "instagram.", "twitter.", "x.com", "wikipedia.", "pinterest.")

def _ddg_links(page): return [urllib.parse.unquote(u) for u in re.findall(r"uddg=([^&\"']+)", page)]

def _clean(urls, n=6):
    seen, out = set(), []
    for u in urls:
        host = urllib.parse.urlparse(u).hostname or ""
        if u.startswith("http") and not any(s in host for s in SKIP_HOSTS) and u not in seen: seen.add(u); out.append(u)
    return out[:n]

def find_pages(query):
    q = urllib.parse.quote_plus(query + " reviews"); key = os.environ.get("BRAVE_API_KEY", "").strip()
    if key:   # official Brave Search API (free tier key): set BRAVE_API_KEY
        req = urllib.request.Request(f"https://api.search.brave.com/res/v1/web/search?q={q}&count=10", headers={"X-Subscription-Token": key, "Accept": "application/json", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=12) as r: return _clean([x["url"] for x in json.loads(r.read()).get("web", {}).get("results", [])])
    return _clean(_ddg_links(fetch_url("https://html.duckduckgo.com/html/?q=" + q)))      # keyless fallback (fragile)

def search_reviews(query):
    urls = find_pages(query)
    def one(u):
        try: return u, extract(fetch_url(u))
        except Exception: return u, None
    with cf.ThreadPoolExecutor(5) as ex: results = list(ex.map(one, urls))
    rows, src, seen, srat, scnt = [], Counter(), set(), None, None
    for u, e in results:
        if not e or not e["reviews"]: continue
        host = (urllib.parse.urlparse(u).hostname or "").replace("www.", "")
        for rv in e["reviews"]:
            if rv["text"].lower() not in seen: seen.add(rv["text"].lower()); rows.append(rv); src[host] += 1
        if srat is None and e["site_rating"]: srat, scnt = e["site_rating"], e["site_count"]
    return rows[:150], dict(src), srat, scnt, len(urls)

def summarize(items, title="Reviews", note="", site_rating=None, site_count=None):
    res, tally = [], {}
    for it in items[:150]:
        text = (it.get("text") or "").strip()
        if not text: continue
        rt = it.get("rating")
        a = ml.analyze_review(text, rt if isinstance(rt, (int, float)) and 1 <= rt <= 5 else None)
        res.append({"text": text, "rating": rt, **a})
    n = len(res)
    sent = Counter(r["sentiment"] for r in res)
    for r in res:
        for asp, lab in r["aspects"].items(): tally.setdefault(asp, Counter())[lab] += 1
    words = Counter(w for r in res for w in re.findall(r"[a-z]{4,}", r["text"].lower()) if w not in STOP)
    rated = [r["rating"] for r in res if isinstance(r["rating"], (int, float))]
    hist = {str(k): sum(1 for x in rated if round(x) == k) for k in (5, 4, 3, 2, 1)}
    sus = sum(r["suspicious"] for r in res)
    pos = sent["Positive"] / n * 100 if n else 0
    verdict = ("Mostly positive: buyers generally satisfied" if pos >= 70 else "Mixed reviews: some buyers are happy, some are not" if pos >= 45 else "Mostly negative: think twice before buying")
    if n and sus / n > .3: verdict += " (⚠ 30%+ of reviews look suspicious)"
    out = {"title": title, "note": note, "count": n, "verdict": verdict if n else "", "sentiment": dict(sent),
            "avg_score": round(sum(r["score"] for r in res) / n, 2) if n else 0,
            "avg_rating": round(sum(rated) / len(rated), 2) if rated else None, "rating_hist": hist,
            "aspects": {k: dict(v) for k, v in tally.items()}, "top_words": words.most_common(10),
            "suspicious": sus, "site_rating": site_rating, "site_count": site_count, "reviews": res}
    out.update(extras(res, out)); return out

NO_REVIEWS = ("No reviews were found on this page. Big sites (Amazon, Flipkart, etc.) block bots and load reviews with JavaScript. "
              "Paste the reviews below or upload a CSV/TXT file; that always works.")
