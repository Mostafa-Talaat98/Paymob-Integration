import uuid

from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"
        VOIDED = "voided", "Voided"

    # رقمنا إحنا (بنبعته لـ Paymob كمرجع)
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # بيانات المنتج
    description = models.CharField(max_length=255)
    amount_cents = models.PositiveIntegerField()  # بالقروش
    currency = models.CharField(max_length=3, default="EGP")

    # الحالة
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )

    # بيانات Paymob (هتتملى في الخطوات الجاية)
    paymob_order_id = models.BigIntegerField(null=True, blank=True, unique=True)
    paymob_transaction_id = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order {self.reference} - {self.status}"