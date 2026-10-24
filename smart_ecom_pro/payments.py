"""Demo payment gateway with Razorpay/Stripe-style behaviour (test mode). Swap charge() for a real gateway SDK in production.
Card numbers are validated and NEVER stored; only the last 4 digits are kept."""
import re, uuid
from datetime import datetime

def _luhn(n):
    s = 0
    for i, ch in enumerate(reversed(n)):
        d = int(ch) * (2 if i % 2 else 1); s += d - 9 if d > 9 else d
    return s % 10 == 0

def _fail(msg): return {"ok": False, "error": msg}

def charge(method, amount, details):
    method = (method or "COD").upper(); ref = "pay_" + uuid.uuid4().hex[:14]
    if method == "COD": return {"ok": True, "method": "COD", "status": "Pending (COD)", "ref": ref}
    if method == "UPI":
        vpa = (details.get("vpa") or "").strip()
        if not re.fullmatch(r"[\w.\-]{2,}@[a-zA-Z]{2,}", vpa): return _fail("Enter a valid UPI ID (e.g. name@upi)")
        if vpa.lower().startswith("fail@"): return _fail("UPI payment declined by the bank (test)")
        return {"ok": True, "method": "UPI", "status": "Paid", "ref": ref}
    if method == "CARD":
        n = re.sub(r"\D", "", details.get("number") or ""); exp = (details.get("expiry") or "").strip(); cvv = (details.get("cvv") or "").strip()
        if len(n) != 16 or not _luhn(n): return _fail("Invalid card number")
        if not re.fullmatch(r"(0[1-9]|1[0-2])/\d{2}", exp): return _fail("Enter the expiry as MM/YY")
        now = datetime.now()
        if (2000 + int(exp[3:]), int(exp[:2])) < (now.year, now.month): return _fail("The card has expired")
        if not re.fullmatch(r"\d{3,4}", cvv): return _fail("CVV must be 3-4 digits")
        if n == "4000000000000002": return _fail("Card declined by the bank (test card)")
        return {"ok": True, "method": "CARD ending " + n[-4:], "status": "Paid", "ref": ref}
    return _fail("Unknown payment method")
