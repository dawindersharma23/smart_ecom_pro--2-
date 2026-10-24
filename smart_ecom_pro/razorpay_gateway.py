"""Real Razorpay integration (standard checkout). Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET (Razorpay Dashboard -> API Keys; test-mode keys are free).
Flow: server creates an order (amount decided on the SERVER) -> browser opens Razorpay Checkout -> server verifies the HMAC signature before marking the order paid."""
import base64, hashlib, hmac, json, os, urllib.request

KEY_ID = lambda: os.environ.get("RAZORPAY_KEY_ID", "").strip()
KEY_SECRET = lambda: os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
enabled = lambda: bool(KEY_ID() and KEY_SECRET())

def create_order(amount_inr, receipt):
    body = json.dumps({"amount": int(round(amount_inr * 100)), "currency": "INR", "receipt": receipt[:40]}).encode()   # amount in paise
    auth = base64.b64encode(f"{KEY_ID()}:{KEY_SECRET()}".encode()).decode()
    req = urllib.request.Request("https://api.razorpay.com/v1/orders", data=body, headers={"Content-Type": "application/json", "Authorization": "Basic " + auth})
    with urllib.request.urlopen(req, timeout=15) as r: return json.loads(r.read())

def verify_signature(order_id, payment_id, signature):
    exp = hmac.new(KEY_SECRET().encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(exp, str(signature))
