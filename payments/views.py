import json
import logging

from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Order
from .services.paymob import (
    PaymobError,
    build_billing_data,
    get_iframe_url,
    get_payment_key,
    verify_hmac,
)

logger = logging.getLogger(__name__)


def pay(request, reference):
    order = get_object_or_404(Order, reference=reference)

    # بيانات تجريبية للعميل (هنخليها حقيقية بعدين)
    billing = build_billing_data("Need", "Test", "test@example.com", "01000000000")

    try:
        payment_token = get_payment_key(order, billing)
    except PaymobError:
        logger.exception("Could not create payment key for order %s", order.reference)
        return render(
            request, "payments/pay.html", {"order": order, "error": True}, status=502
        )

    return render(
        request,
        "payments/pay.html",
        {"order": order, "iframe_url": get_iframe_url(payment_token)},
    )


@csrf_exempt
@require_POST
def paymob_webhook(request):
    # 1) نقرأ الـ JSON
    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("invalid json")

    # أي نوع غير TRANSACTION نتجاهله بأمان
    if payload.get("type") != "TRANSACTION":
        return HttpResponse(status=200)

    obj = payload.get("obj") or {}

    # 2) نتحقق من التوقيع
    if not verify_hmac(obj, request.GET.get("hmac")):
        logger.warning("Webhook rejected: bad HMAC")
        return HttpResponseForbidden("invalid signature")

    # 3) ندوّر على الأوردر برقمه عند Paymob
    paymob_order_id = (obj.get("order") or {}).get("id")

    with transaction.atomic():
        order = (
            Order.objects.select_for_update()
            .filter(paymob_order_id=paymob_order_id)
            .first()
        )
        if order is None:
            logger.warning("Webhook for unknown order %s", paymob_order_id)
            return HttpResponse(status=200)

        # 4) نتأكد إن المبلغ مطابق
        if obj.get("amount_cents") != order.amount_cents:
            logger.error("Amount mismatch on order %s", order.reference)
            return HttpResponse(status=200)

        # 5) نحدّث الحالة
        if obj.get("success") is True and not obj.get("pending"):
            if order.status == Order.Status.PENDING:
                order.status = Order.Status.PAID
            order.paymob_transaction_id = obj.get("id")
            order.save(update_fields=["status", "paymob_transaction_id", "updated_at"])
        elif obj.get("success") is False and order.status == Order.Status.PENDING:
            order.status = Order.Status.FAILED
            order.paymob_transaction_id = obj.get("id")
            order.save(update_fields=["status", "paymob_transaction_id", "updated_at"])

    return HttpResponse(status=200)