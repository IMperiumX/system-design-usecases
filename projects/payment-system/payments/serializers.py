"""
DRF Serializers for Payment System API

Provides JSON serialization/deserialization for payment models.
"""

from rest_framework import serializers
from payments.models import PaymentEvent, PaymentOrder, WalletAccount, LedgerEntry


class PaymentOrderInputSerializer(serializers.Serializer):
    """Serializer for payment order input in create payment request."""
    payment_order_id = serializers.CharField(max_length=255)
    seller_account = serializers.CharField(max_length=255)
    amount = serializers.CharField(max_length=50)
    currency = serializers.CharField(max_length=3, default='USD')


class CreatePaymentRequestSerializer(serializers.Serializer):
    """
    Serializer for POST /api/v1/payments request.

    Matches API spec from chapter:
    - buyer_info: {user_id, email, name}
    - checkout_id: unique checkout identifier
    - credit_card_info: {token, last4}
    - payment_orders: list of payment orders
    """
    checkout_id = serializers.CharField(max_length=255)
    buyer_info = serializers.JSONField()
    credit_card_info = serializers.JSONField()
    payment_orders = PaymentOrderInputSerializer(many=True)
    seller_info = serializers.JSONField(required=False, allow_null=True)

    def validate_payment_orders(self, value):
        """Ensure at least one payment order."""
        if not value:
            raise serializers.ValidationError("At least one payment order is required")
        return value

    def validate_buyer_info(self, value):
        """Validate buyer_info has required fields."""
        required_fields = ['user_id', 'email']
        for field in required_fields:
            if field not in value:
                raise serializers.ValidationError(f"buyer_info must contain '{field}'")
        return value


class PaymentOrderSerializer(serializers.ModelSerializer):
    """Serializer for PaymentOrder model."""

    class Meta:
        model = PaymentOrder
        fields = [
            'payment_order_id',
            'checkout_id',
            'buyer_account',
            'seller_account',
            'amount',
            'currency',
            'status',
            'psp_token',
            'wallet_updated',
            'ledger_updated',
            'retry_count',
            'error_message',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    checkout_id = serializers.CharField(source='checkout.checkout_id', read_only=True)


class PaymentEventSerializer(serializers.ModelSerializer):
    """Serializer for PaymentEvent model with nested orders."""

    orders = PaymentOrderSerializer(many=True, read_only=True)

    class Meta:
        model = PaymentEvent
        fields = [
            'checkout_id',
            'buyer_info',
            'seller_info',
            'credit_card_info',
            'is_payment_done',
            'orders',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class CreatePaymentResponseSerializer(serializers.Serializer):
    """
    Serializer for POST /api/v1/payments response.

    Returns created payment event with order statuses.
    """
    checkout_id = serializers.CharField()
    payment_event_status = serializers.SerializerMethodField()
    payment_orders = PaymentOrderSerializer(many=True, source='orders')
    created_at = serializers.DateTimeField()

    def get_payment_event_status(self, obj):
        """Return overall payment event status."""
        if obj.is_payment_done:
            return 'COMPLETE'
        return 'PROCESSING'


class WalletAccountSerializer(serializers.ModelSerializer):
    """Serializer for WalletAccount model."""

    balance_dollars = serializers.FloatField(read_only=True)

    class Meta:
        model = WalletAccount
        fields = [
            'account_id',
            'balance_cents',
            'balance_dollars',
            'currency',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['balance_cents', 'balance_dollars', 'created_at', 'updated_at']


class LedgerEntrySerializer(serializers.ModelSerializer):
    """Serializer for LedgerEntry model."""

    amount_dollars = serializers.FloatField(read_only=True)
    entry_type = serializers.SerializerMethodField()

    class Meta:
        model = LedgerEntry
        fields = [
            'entry_id',
            'transaction_id',
            'account_id',
            'debit_cents',
            'credit_cents',
            'amount_dollars',
            'entry_type',
            'currency',
            'description',
            'created_at'
        ]
        read_only_fields = ['entry_id', 'created_at']

    def get_entry_type(self, obj):
        """Return 'debit' or 'credit'."""
        return 'debit' if obj.debit_cents > 0 else 'credit'


class WebhookPaymentStatusSerializer(serializers.Serializer):
    """
    Serializer for PSP webhook callback.

    POST /api/v1/webhooks/payment-status
    """
    token = serializers.CharField()
    status = serializers.ChoiceField(choices=['success', 'failed', 'pending'])
    payment_order_id = serializers.CharField()
    timestamp = serializers.IntegerField()
    signature = serializers.CharField()
    error = serializers.CharField(required=False, allow_null=True)
