"""
DRF Views for Payment System API

Provides REST API endpoints as defined in the chapter:
- POST /api/v1/payments - Create payment event
- GET /api/v1/payments/:id - Get payment status
- POST /api/v1/webhooks/payment-status - PSP webhook callback
"""

import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404

from payments.models import PaymentEvent, PaymentOrder, WalletAccount, LedgerEntry
from payments.serializers import (
    CreatePaymentRequestSerializer,
    CreatePaymentResponseSerializer,
    PaymentEventSerializer,
    PaymentOrderSerializer,
    WalletAccountSerializer,
    LedgerEntrySerializer,
    WebhookPaymentStatusSerializer
)
from payments.services.payment_service import PaymentService, PaymentError

logger = logging.getLogger(__name__)


class PaymentViewSet(viewsets.ViewSet):
    """
    ViewSet for payment operations.

    Endpoints:
    - POST /api/v1/payments - Create payment event
    - GET /api/v1/payments/:id - Get payment order status
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.payment_service = PaymentService()

    def create(self, request):
        """
        POST /api/v1/payments

        Create a payment event and execute payment orders.

        Request Body:
        {
            "checkout_id": "checkout_abc123",
            "buyer_info": {"user_id": "user_123", "email": "buyer@example.com", "name": "John"},
            "credit_card_info": {"token": "tok_visa_4242", "last4": "4242"},
            "payment_orders": [
                {
                    "payment_order_id": "order_xyz789",
                    "seller_account": "seller_456",
                    "amount": "29.99",
                    "currency": "USD"
                }
            ]
        }

        Returns:
        - 202 Accepted: Payment event created and processing
        - 400 Bad Request: Invalid request data
        - 500 Internal Server Error: Unexpected error
        """
        # Validate request
        serializer = CreatePaymentRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': 'Invalid request', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = serializer.validated_data

        try:
            # Create payment event
            payment_event = self.payment_service.create_payment_event(
                checkout_id=validated_data['checkout_id'],
                buyer_info=validated_data['buyer_info'],
                credit_card_info=validated_data['credit_card_info'],
                payment_orders=validated_data['payment_orders'],
                seller_info=validated_data.get('seller_info')
            )

            # Execute each payment order (sync for demo, would be async in production)
            for order in payment_event.orders.all():
                try:
                    self.payment_service.execute_payment_order(order.payment_order_id)
                except Exception as e:
                    logger.error(f"Failed to execute order {order.payment_order_id}: {e}")
                    # Continue with other orders

            # Refresh from DB to get updated status
            payment_event.refresh_from_db()

            # Return response
            response_serializer = CreatePaymentResponseSerializer(payment_event)
            return Response(
                response_serializer.data,
                status=status.HTTP_202_ACCEPTED
            )

        except PaymentError as e:
            logger.error(f"Payment error: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.exception("Unexpected error creating payment")
            return Response(
                {'error': 'Internal server error'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def retrieve(self, request, pk=None):
        """
        GET /api/v1/payments/:id

        Get payment order status by payment_order_id.

        Returns:
        - 200 OK: Payment order details
        - 404 Not Found: Payment order not found
        """
        payment_order = get_object_or_404(PaymentOrder, payment_order_id=pk)
        serializer = PaymentOrderSerializer(payment_order)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """
        POST /api/v1/payments/:id/retry

        Manually retry a failed payment order.

        Returns:
        - 200 OK: Retry initiated
        - 400 Bad Request: Cannot retry
        - 404 Not Found: Payment order not found
        """
        payment_order = get_object_or_404(PaymentOrder, payment_order_id=pk)

        try:
            updated_order = self.payment_service.retry_failed_payment(pk)
            serializer = PaymentOrderSerializer(updated_order)
            return Response(serializer.data)
        except PaymentError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class WebhookView(APIView):
    """
    API view for PSP webhook callbacks.

    POST /api/v1/webhooks/payment-status
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.payment_service = PaymentService()

    def post(self, request):
        """
        Handle PSP webhook notification.

        Request Body:
        {
            "token": "tok_1234567890abcdef",
            "status": "success",
            "payment_order_id": "order_xyz789",
            "timestamp": 1672531200,
            "signature": "sha256_hmac_signature",
            "error": "optional_error_message"
        }

        System Design Concept:
            In production, MUST verify signature using HMAC-SHA256
            to prevent spoofed webhooks. We skip verification in demo.

        Returns:
        - 200 OK: Webhook processed
        - 400 Bad Request: Invalid webhook data
        """
        serializer = WebhookPaymentStatusSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning(f"Invalid webhook data: {serializer.errors}")
            return Response(
                {'error': 'Invalid webhook data', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        validated_data = serializer.validated_data

        # TODO: Verify webhook signature (critical for production!)
        # if not self._verify_signature(validated_data):
        #     return Response({'error': 'Invalid signature'}, status=403)

        logger.info(
            f"[Webhook] Received: order={validated_data['payment_order_id']}, "
            f"status={validated_data['status']}"
        )

        # Update payment order status based on webhook
        # (In our demo, payment is already processed synchronously, so this is redundant)
        # In production with async PSP, this webhook would trigger payment completion

        return Response({'status': 'ok'}, status=status.HTTP_200_OK)


class WalletViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for wallet accounts.

    Endpoints:
    - GET /api/v1/wallets - List all wallets
    - GET /api/v1/wallets/:id - Get wallet details
    """
    queryset = WalletAccount.objects.all()
    serializer_class = WalletAccountSerializer
    lookup_field = 'account_id'


class LedgerViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for ledger entries.

    Endpoints:
    - GET /api/v1/ledger - List ledger entries
    - GET /api/v1/ledger/:id - Get ledger entry details

    Query Parameters:
    - account_id: Filter by account
    - transaction_id: Filter by transaction
    """
    queryset = LedgerEntry.objects.all().order_by('-created_at')
    serializer_class = LedgerEntrySerializer
    filterset_fields = ['account_id', 'transaction_id']

    def get_queryset(self):
        """Apply filters from query params."""
        queryset = super().get_queryset()

        account_id = self.request.query_params.get('account_id')
        if account_id:
            queryset = queryset.filter(account_id=account_id)

        transaction_id = self.request.query_params.get('transaction_id')
        if transaction_id:
            queryset = queryset.filter(transaction_id=transaction_id)

        return queryset
