"""
Payment Service - Main orchestrator for payment flow

System Design Concept:
    Implements [[saga-pattern]] for distributed transactions.
    Orchestrates payment flow across multiple services (PSP, Wallet, Ledger)
    without using 2PC (two-phase commit).

Simulates:
    - Stripe Payment Intents orchestration
    - PayPal Checkout flow
    - Braintree payment processing

At Scale:
    - Use message queue (Kafka) for async wallet/ledger updates
    - Implement circuit breaker for PSP calls
    - Add distributed tracing (OpenTelemetry)
"""

import logging
import uuid
from typing import Dict, List, Optional
from django.db import transaction
from django.conf import settings
from django.utils import timezone

from payments.models import PaymentEvent, PaymentOrder
from payments.services.psp_mock import get_psp_service, PaymentStatus
from payments.services.wallet_service import WalletService
from payments.services.ledger_service import LedgerService

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """Base exception for payment errors."""
    pass


class PaymentValidationError(PaymentError):
    """Invalid payment request."""
    pass


class PaymentService:
    """
    Main service for orchestrating payment flow.

    System Design Concept:
        Implements [[orchestration-pattern]] coordinating multiple services:
        1. Risk check (fraud detection)
        2. PSP integration (payment processing)
        3. Wallet updates (balance management)
        4. Ledger recording (accounting)

    Thread Safety:
        Uses database transactions for consistency.
        Idempotency keys prevent duplicate processing.
    """

    def __init__(self):
        self.psp = get_psp_service(
            success_rate=getattr(settings, 'PSP_SUCCESS_RATE', 0.9)
        )
        self.wallet_service = WalletService()
        self.ledger_service = LedgerService()
        self.max_retry_attempts = getattr(settings, 'MAX_RETRY_ATTEMPTS', 5)

    @transaction.atomic
    def create_payment_event(
        self,
        checkout_id: str,
        buyer_info: Dict,
        credit_card_info: Dict,
        payment_orders: List[Dict],
        seller_info: Optional[Dict] = None
    ) -> PaymentEvent:
        """
        Create a payment event with multiple payment orders.

        System Design Concept:
            Implements [[idempotency]] using checkout_id as unique key.
            Duplicate requests return the existing payment event.

        Args:
            checkout_id: Unique checkout identifier (idempotency key)
            buyer_info: {user_id, email, name}
            credit_card_info: {token, last4} - tokenized card data
            payment_orders: List of {payment_order_id, seller_account, amount, currency}
            seller_info: Optional seller details

        Returns:
            PaymentEvent instance

        Raises:
            PaymentValidationError: If request is invalid
        """
        # Idempotency check: return existing event if checkout_id exists
        try:
            existing_event = PaymentEvent.objects.get(checkout_id=checkout_id)
            logger.info(
                f"[Payment] Duplicate checkout_id={checkout_id}, "
                f"returning existing event (idempotent)"
            )
            return existing_event
        except PaymentEvent.DoesNotExist:
            pass

        # Validation
        if not payment_orders:
            raise PaymentValidationError("At least one payment order is required")

        # Create payment event
        payment_event = PaymentEvent.objects.create(
            checkout_id=checkout_id,
            buyer_info=buyer_info,
            seller_info=seller_info,
            credit_card_info=credit_card_info,
            is_payment_done=False
        )

        # Create payment orders
        for order_data in payment_orders:
            PaymentOrder.objects.create(
                payment_order_id=order_data['payment_order_id'],
                checkout=payment_event,
                buyer_account=buyer_info.get('user_id', 'unknown'),
                seller_account=order_data['seller_account'],
                amount=str(order_data['amount']),
                currency=order_data.get('currency', 'USD'),
                status=PaymentOrder.Status.NOT_STARTED,
                psp_nonce=order_data['payment_order_id']  # Use as nonce for PSP
            )

        logger.info(
            f"[Payment] Created payment event: checkout_id={checkout_id}, "
            f"orders={len(payment_orders)}, buyer={buyer_info.get('email')}"
        )

        return payment_event

    @transaction.atomic
    def execute_payment_order(self, payment_order_id: str) -> PaymentOrder:
        """
        Execute a single payment order.

        System Design Concept:
            Implements complete payment flow with [[idempotency]]:
            1. Risk check (fraud detection)
            2. Register payment with PSP (get token)
            3. Process payment via PSP
            4. Update wallet (credit seller)
            5. Record in ledger (double-entry)

        Flow:
            NOT_STARTED -> EXECUTING -> SUCCESS/FAILED

        Args:
            payment_order_id: Payment order to execute

        Returns:
            Updated PaymentOrder

        Raises:
            PaymentError: If payment execution fails
        """
        # Get payment order with lock to prevent concurrent execution
        payment_order = PaymentOrder.objects.select_for_update().get(
            payment_order_id=payment_order_id
        )

        # Idempotency: skip if already successful
        if payment_order.status == PaymentOrder.Status.SUCCESS:
            logger.info(
                f"[Payment] Order {payment_order_id} already SUCCESS (idempotent skip)"
            )
            return payment_order

        # Check if retries exhausted
        if payment_order.retry_count >= self.max_retry_attempts:
            logger.error(
                f"[Payment] Order {payment_order_id} exceeded max retries "
                f"({self.max_retry_attempts})"
            )
            payment_order.status = PaymentOrder.Status.FAILED
            payment_order.error_message = "Max retry attempts exceeded"
            payment_order.save()
            return payment_order

        # Update status to EXECUTING
        payment_order.status = PaymentOrder.Status.EXECUTING
        payment_order.save(update_fields=['status', 'updated_at'])

        logger.info(f"[Payment] Executing order {payment_order_id}")

        try:
            # Step 1: Risk check (fraud detection)
            if not self._perform_risk_check(payment_order):
                payment_order.status = PaymentOrder.Status.FAILED
                payment_order.error_message = "Failed risk check"
                payment_order.save()
                logger.warning(f"[Payment] Order {payment_order_id} failed risk check")
                return payment_order

            # Step 2: Register payment with PSP (if not already registered)
            if not payment_order.psp_token:
                token, hosted_url = self._register_with_psp(payment_order)
                payment_order.psp_token = token
                payment_order.save(update_fields=['psp_token', 'updated_at'])
                logger.info(
                    f"[Payment] Registered with PSP: order={payment_order_id}, "
                    f"token={token}"
                )

            # Step 3: Process payment via PSP
            result = self.psp.process_payment(
                token=payment_order.psp_token,
                idempotency_key=payment_order_id,
                card_info=payment_order.checkout.credit_card_info
            )

            if result.status == PaymentStatus.SUCCESS:
                # Payment succeeded
                payment_order.status = PaymentOrder.Status.SUCCESS
                payment_order.error_message = None
                payment_order.save(update_fields=['status', 'error_message', 'updated_at'])

                logger.info(
                    f"[Payment] Order {payment_order_id} SUCCESS: "
                    f"${payment_order.amount} {payment_order.currency}"
                )

                # Step 4: Update wallet (async in production, sync for demo)
                self._update_wallet(payment_order)

                # Step 5: Record in ledger
                self._update_ledger(payment_order)

                # Check if all orders in checkout are complete
                self._check_and_mark_event_complete(payment_order.checkout)

            else:
                # Payment failed
                payment_order.status = PaymentOrder.Status.FAILED
                payment_order.error_message = result.error_message or "Payment declined by PSP"
                payment_order.retry_count += 1
                payment_order.last_retry_at = timezone.now()
                payment_order.save()

                logger.warning(
                    f"[Payment] Order {payment_order_id} FAILED: "
                    f"{result.error_message}, retry={payment_order.retry_count}"
                )

        except Exception as e:
            # Unexpected error (network timeout, database error, etc.)
            logger.exception(f"[Payment] Unexpected error executing order {payment_order_id}")
            payment_order.status = PaymentOrder.Status.FAILED
            payment_order.error_message = f"Internal error: {str(e)}"
            payment_order.retry_count += 1
            payment_order.last_retry_at = timezone.now()
            payment_order.save()

        return payment_order

    def _perform_risk_check(self, payment_order: PaymentOrder) -> bool:
        """
        Perform risk/fraud check.

        System Design Concept:
            In production, this calls third-party fraud detection services
            (Sift, Stripe Radar) to check for:
            - AML/CFT compliance
            - Suspicious transaction patterns
            - Blocklist matching

        Simplification:
            Always returns True for demo purposes.

        Args:
            payment_order: Order to check

        Returns:
            True if risk check passes, False otherwise
        """
        # Mock: always pass risk check
        logger.debug(f"[Payment] Risk check PASSED for order {payment_order.payment_order_id}")
        return True

    def _register_with_psp(self, payment_order: PaymentOrder) -> tuple:
        """
        Register payment with PSP to get token for hosted page.

        Args:
            payment_order: Order to register

        Returns:
            Tuple of (token, hosted_page_url)
        """
        checkout = payment_order.checkout
        token, hosted_url = self.psp.register_payment(
            nonce=payment_order.psp_nonce or payment_order.payment_order_id,
            amount=payment_order.amount,
            currency=payment_order.currency,
            buyer_info=checkout.buyer_info,
            redirect_url=f"http://localhost:8000/payment/callback/{payment_order.payment_order_id}"
        )
        return token, hosted_url

    def _update_wallet(self, payment_order: PaymentOrder) -> None:
        """
        Update seller wallet balance.

        System Design Concept:
            Uses [[idempotency]] - WalletService checks wallet_updated flag.
            In production, this would be async (Celery task or Kafka event).

        Args:
            payment_order: Successful payment order
        """
        try:
            self.wallet_service.process_payment_order(payment_order)
        except Exception as e:
            logger.error(
                f"[Payment] Failed to update wallet for order {payment_order.payment_order_id}: {e}"
            )
            # In production, retry via message queue

    def _update_ledger(self, payment_order: PaymentOrder) -> None:
        """
        Record transaction in ledger.

        System Design Concept:
            Uses [[double-entry-accounting]] and [[idempotency]].
            In production, this would be async.

        Args:
            payment_order: Successful payment order
        """
        try:
            self.ledger_service.record_payment(payment_order)
        except Exception as e:
            logger.error(
                f"[Payment] Failed to update ledger for order {payment_order.payment_order_id}: {e}"
            )
            # In production, retry via message queue

    def _check_and_mark_event_complete(self, payment_event: PaymentEvent) -> None:
        """
        Check if all payment orders are complete and mark event done.

        Args:
            payment_event: Payment event to check
        """
        all_orders = payment_event.orders.all()
        all_complete = all(
            order.status == PaymentOrder.Status.SUCCESS
            for order in all_orders
        )

        if all_complete and not payment_event.is_payment_done:
            payment_event.is_payment_done = True
            payment_event.save(update_fields=['is_payment_done', 'updated_at'])
            logger.info(
                f"[Payment] Event {payment_event.checkout_id} marked COMPLETE"
            )

    def get_payment_status(self, payment_order_id: str) -> Dict:
        """
        Get status of a payment order.

        Args:
            payment_order_id: Order to query

        Returns:
            Dict with payment status details
        """
        try:
            order = PaymentOrder.objects.select_related('checkout').get(
                payment_order_id=payment_order_id
            )

            return {
                'payment_order_id': order.payment_order_id,
                'checkout_id': order.checkout.checkout_id,
                'status': order.status,
                'amount': order.amount,
                'currency': order.currency,
                'buyer_account': order.buyer_account,
                'seller_account': order.seller_account,
                'wallet_updated': order.wallet_updated,
                'ledger_updated': order.ledger_updated,
                'retry_count': order.retry_count,
                'error_message': order.error_message,
                'created_at': order.created_at.isoformat(),
                'updated_at': order.updated_at.isoformat()
            }
        except PaymentOrder.DoesNotExist:
            return {'error': 'Payment order not found'}

    def retry_failed_payment(self, payment_order_id: str) -> PaymentOrder:
        """
        Manually retry a failed payment.

        Args:
            payment_order_id: Order to retry

        Returns:
            Updated PaymentOrder

        Raises:
            PaymentError: If order cannot be retried
        """
        payment_order = PaymentOrder.objects.get(payment_order_id=payment_order_id)

        if not payment_order.can_retry(self.max_retry_attempts):
            raise PaymentError(
                f"Order {payment_order_id} cannot be retried: "
                f"status={payment_order.status}, retries={payment_order.retry_count}"
            )

        logger.info(f"[Payment] Manually retrying order {payment_order_id}")

        # Reset status to allow re-execution
        payment_order.status = PaymentOrder.Status.NOT_STARTED
        payment_order.save(update_fields=['status', 'updated_at'])

        return self.execute_payment_order(payment_order_id)
