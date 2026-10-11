from django.urls import path

from . import views

urlpatterns = [
    path("pay/<uuid:reference>/", views.pay, name="pay"),
    path("webhook/", views.paymob_webhook, name="paymob_webhook"),
]