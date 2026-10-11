import hashlib
import hmac
import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

AUTH_CACHE_KEY = "paymob:auth_token"
AUTH_TOKEN_TTL = 50 * 60


# ---------- الأخطاء ----------
class PaymobError(Exception):
    """أي خطأ بيخص Paymob."""


class PaymobConnectionError(PaymobError):
    """مشكلة شبكة: timeout أو مفيش اتصال."""


class PaymobAPIError(PaymobError):
    """Paymob ردّت، بس برد غلط."""

    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


# ---------- دالة الإرسال العامة ----------
def paymob_post(path, payload, token=None):
    url = f"{settings.PAYMOB_BASE_URL}/{path.lstrip('/')}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=settings.PAYMOB_TIMEOUT,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        logger.error("Paymob connection failure on %s: %s", path, exc)
        raise PaymobConnectionError(f"Could not reach Paymob ({path})") from exc
    except requests.RequestException as exc:
        raise PaymobError(f"Unexpected error calling Paymob ({path})") from exc

    if not response.ok:
        logger.error(
            "Paymob API error on %s: status=%s body=%s",
            path, response.status_code, response.text[:500],
        )
        raise PaymobAPIError(
            f"Paymob returned {response.status_code} on {path}",
            status_code=response.status_code,
            body=response.text,
        )

    try:
        return response.json()
    except ValueError as exc:
        raise PaymobAPIError("Paymob returned invalid JSON", body=response.text) from exc


# ---------- Step 1: Authentication ----------
def get_auth_token(force_refresh=False):
    if not force_refresh:
        token = cache.get(AUTH_CACHE_KEY)
        if token:
            return token

    data = paymob_post("auth/tokens", {"api_key": settings.PAYMOB_API_KEY})

    token = data.get("token")
    if not token:
        raise PaymobAPIError("Auth response did not contain a token", body=data)

    cache.set(AUTH_CACHE_KEY, token, AUTH_TOKEN_TTL)
    return token


# ---------- Step 2: تسجيل الأوردر ----------
def register_order(order):
    if order.paymob_order_id:
        return order.paymob_order_id

    payload = {
        "auth_token": get_auth_token(),
        "delivery_needed": False,
        "amount_cents": order.amount_cents,
        "currency": order.currency,
        "merchant_order_id": str(order.reference),
        "items": [],
    }

    try:
        data = paymob_post("ecommerce/orders", payload)
    except PaymobAPIError as exc:
        if exc.status_code == 401:
            payload["auth_token"] = get_auth_token(force_refresh=True)
            data = paymob_post("ecommerce/orders", payload)
        else:
            raise

    paymob_order_id = data.get("id")
    if not paymob_order_id:
        raise PaymobAPIError("Order response did not contain an id", body=data)

    order.paymob_order_id = paymob_order_id
    order.save(update_fields=["paymob_order_id", "updated_at"])
    return paymob_order_id


# ---------- Step 3: Payment Key ----------
def build_billing_data(first_name, last_name, email, phone_number):
    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone_number": phone_number,
        "apartment": "NA",
        "floor": "NA",
        "street": "NA",
        "building": "NA",
        "shipping_method": "NA",
        "postal_code": "NA",
        "city": "NA",
        "country": "EG",
        "state": "NA",
    }


def get_payment_key(order, billing_data):
    paymob_order_id = register_order(order)

    payload = {
        "auth_token": get_auth_token(),
        "amount_cents": order.amount_cents,
        "expiration": 3600,
        "order_id": paymob_order_id,
        "billing_data": billing_data,
        "currency": order.currency,
        "integration_id": settings.PAYMOB_INTEGRATION_ID,
    }

    try:
        data = paymob_post("acceptance/payment_keys", payload)
    except PaymobAPIError as exc:
        if exc.status_code == 401:
            payload["auth_token"] = get_auth_token(force_refresh=True)
            data = paymob_post("acceptance/payment_keys", payload)
        else:
            raise

    payment_token = data.get("token")
    if not payment_token:
        raise PaymobAPIError("Payment key response did not contain a token", body=data)

    return payment_token


# ---------- Step 4: رابط الـ iFrame ----------
def get_iframe_url(payment_token):
    return (
        f"{settings.PAYMOB_BASE_URL}/acceptance/iframes/"
        f"{settings.PAYMOB_IFRAME_ID}?payment_token={payment_token}"
    )


# ---------- Step 5: التحقق من الـ HMAC ----------
HMAC_FIELDS = [
    "amount_cents",
    "created_at",
    "currency",
    "error_occured",
    "has_parent_transaction",
    "id",
    "integration_id",
    "is_3d_secure",
    "is_auth",
    "is_capture",
    "is_refunded",
    "is_standalone_payment",
    "is_voided",
    "order.id",
    "owner",
    "pending",
    "source_data.pan",
    "source_data.sub_type",
    "source_data.type",
    "success",
]


def _get_nested(data, dotted_key):
    value = data
    for part in dotted_key.split("."):
        value = value.get(part, "") if isinstance(value, dict) else ""
    return value


def _to_str(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def verify_hmac(obj, received_hmac):
    """بيتحقق إن الـ webhook جاي من Paymob فعلاً."""
    if not received_hmac:
        return False

    message = "".join(_to_str(_get_nested(obj, f)) for f in HMAC_FIELDS)
    expected = hmac.new(
        settings.PAYMOB_HMAC_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected, received_hmac)