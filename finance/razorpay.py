"""Minimal Razorpay client: create orders and verify signatures (https://razorpay.com/docs/api/)."""

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from decimal import Decimal

from django.conf import settings

API = "https://api.razorpay.com/v1"


class GatewayError(Exception):
    pass


def enabled():
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def to_paise(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))


def create_order(amount: Decimal, receipt: str, notes: dict) -> dict:
    payload = json.dumps({"amount": to_paise(amount), "currency": "INR", "receipt": receipt[:40], "notes": notes}).encode()
    credentials = base64.b64encode(f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode()).decode()
    request = urllib.request.Request(
        f"{API}/orders",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Basic {credentials}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="ignore")[:300]
        raise GatewayError(f"Razorpay rejected the order ({error.code}): {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise GatewayError("Razorpay could not be reached.") from error


def _sign(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def valid_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    expected = _sign(settings.RAZORPAY_KEY_SECRET, f"{order_id}|{payment_id}".encode())
    return hmac.compare_digest(expected, signature or "")


def valid_webhook_signature(body: bytes, signature: str) -> bool:
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    return hmac.compare_digest(_sign(settings.RAZORPAY_WEBHOOK_SECRET, body), signature or "")
