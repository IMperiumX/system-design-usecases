"""
URL Configuration for Payment System API
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from payments.views import (
    PaymentViewSet,
    WebhookView,
    WalletViewSet,
    LedgerViewSet
)

# Create router for ViewSets
router = DefaultRouter()
router.register(r'payments', PaymentViewSet, basename='payment')
router.register(r'wallets', WalletViewSet, basename='wallet')
router.register(r'ledger', LedgerViewSet, basename='ledger')

# URL patterns
urlpatterns = [
    # API v1 routes
    path('api/v1/', include(router.urls)),

    # Webhook endpoint (not part of router)
    path('api/v1/webhooks/payment-status', WebhookView.as_view(), name='webhook-payment-status'),
]
