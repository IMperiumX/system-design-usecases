"""
PSP Mock Service - Simulates Payment Service Provider (Stripe/Braintree)

System Design Concept:
    Simulates a third-party PSP API with hosted payment pages, webhooks,
    and idempotency guarantees. This demonstrates the [[PSP-integration]]
    pattern used by real payment systems.

Simulates:
    - Stripe Payment Intents API
    - Braintree Hosted Fields
    - PayPal Checkout

Simplifications:
    - 90% success rate (configurable)
    - No real card processing or bank integration
    - No actual hosted payment page (returns mock URL)
    - Synchronous payment processing (real PSPs are async)

At Scale:
    Real PSPs handle thousands of TPS with:
    - Rate limiting (prevent abuse)
    - Fraud detection (machine learning models)
    - 3D Secure authentication
    - PCI DSS compliance infrastructure
"""

import uuid
import random
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class PaymentStatus(Enum):
    """Payment processing status returned by PSP."""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REQUIRES_ACTION = "requires_action"  # e.g., 3D Secure


@dataclass
class PaymentResult:
    """Result of payment processing."""
    status: PaymentStatus
    token: str
    transaction_id: str
    error_message: Optional[str] = None
    metadata: Optional[Dict] = None


class PSPMockService:
    """
    Mock Payment Service Provider (simulates Stripe/Braintree).

    System Design Concept:
        Demonstrates [[idempotency]] using nonce/token pattern.
        The nonce is client-generated (payment_order_id) and ensures
        duplicate requests return the same token.

    Key Features:
        - Payment registration (returns token for hosted page)
        - Payment processing with configurable success rate
        - Idempotency key handling
        - Webhook simulation (async notification)
    """

    def __init__(self, success_rate: float = 0.9):
        """
        Initialize PSP mock.

        Args:
            success_rate: Probability of successful payment (0.0 to 1.0)
        """
        self.success_rate = success_rate
        # Simulates PSP's internal storage (nonce -> token mapping)
        self._nonce_to_token: Dict[str, str] = {}
        # Simulates payment processing results cache
        self._token_to_result: Dict[str, PaymentResult] = {}

        logger.info(f"PSP Mock initialized with {success_rate * 100}% success rate")

    def register_payment(
        self,
        nonce: str,
        amount: str,
        currency: str,
        buyer_info: Dict,
        redirect_url: str
    ) -> Tuple[str, str]:
        """
        Register a payment and return token for hosted payment page.

        System Design Concept:
            Implements [[idempotency]] - same nonce always returns same token.
            This prevents duplicate payment registrations.

        Flow (from Chapter):
            1. Client calls our payment service
            2. Payment service calls PSP.register_payment(nonce)
            3. PSP returns token
            4. Client uses token to load hosted payment page

        Args:
            nonce: Client-generated unique ID (idempotency key)
            amount: Payment amount as string
            currency: ISO 4217 currency code
            buyer_info: Buyer details (email, name, etc.)
            redirect_url: URL to redirect after payment complete

        Returns:
            Tuple of (token, hosted_page_url)
        """
        # Idempotency check: return cached token if nonce seen before
        if nonce in self._nonce_to_token:
            token = self._nonce_to_token[nonce]
            logger.info(f"[PSP] Duplicate registration for nonce={nonce}, returning cached token={token}")
            return token, self._get_hosted_page_url(token)

        # Generate new token (PSP's internal identifier)
        token = f"tok_{uuid.uuid4().hex[:16]}"
        self._nonce_to_token[nonce] = token

        logger.info(
            f"[PSP] Registered payment: nonce={nonce}, token={token}, "
            f"amount={amount} {currency}, buyer={buyer_info.get('email')}"
        )

        return token, self._get_hosted_page_url(token)

    def process_payment(
        self,
        token: str,
        idempotency_key: str,
        card_info: Optional[Dict] = None
    ) -> PaymentResult:
        """
        Process payment using token from registration.

        System Design Concept:
            Implements [[idempotency]] using idempotency_key.
            Same key returns cached result without reprocessing payment.

        Args:
            token: Token from register_payment()
            idempotency_key: Unique key for this payment attempt (usually payment_order_id)
            card_info: Optional card details (in real system, captured by hosted page)

        Returns:
            PaymentResult with status and details
        """
        # Idempotency check: return cached result if key seen before
        if idempotency_key in self._token_to_result:
            result = self._token_to_result[idempotency_key]
            logger.info(
                f"[PSP] Duplicate payment request for key={idempotency_key}, "
                f"returning cached result={result.status.value}"
            )
            return result

        # Simulate payment processing delay (real PSPs take 200-500ms)
        time.sleep(0.1)

        # Randomly succeed or fail based on success_rate
        success = random.random() < self.success_rate

        if success:
            result = PaymentResult(
                status=PaymentStatus.SUCCESS,
                token=token,
                transaction_id=f"txn_{uuid.uuid4().hex[:16]}",
                metadata={"processor": "psp_mock", "timestamp": time.time()}
            )
            logger.info(f"[PSP] Payment SUCCESS: key={idempotency_key}, token={token}")
        else:
            # Simulate various failure reasons
            error_reasons = [
                "insufficient_funds",
                "card_declined",
                "expired_card",
                "invalid_cvv",
                "fraud_detected"
            ]
            error = random.choice(error_reasons)
            result = PaymentResult(
                status=PaymentStatus.FAILED,
                token=token,
                transaction_id=f"txn_{uuid.uuid4().hex[:16]}",
                error_message=error,
                metadata={"error_code": error}
            )
            logger.warning(f"[PSP] Payment FAILED: key={idempotency_key}, reason={error}")

        # Cache result for idempotency
        self._token_to_result[idempotency_key] = result
        return result

    def get_payment_status(self, token: str) -> Optional[PaymentResult]:
        """
        Query payment status by token.

        Args:
            token: Token from register_payment()

        Returns:
            PaymentResult if found, None otherwise
        """
        # In real PSP, this would query their database
        # We search our cache for any result with matching token
        for result in self._token_to_result.values():
            if result.token == token:
                return result
        return None

    def simulate_webhook(self, token: str, callback_url: str) -> Dict:
        """
        Simulate webhook callback to merchant's server.

        System Design Concept:
            Demonstrates [[webhook-pattern]] for async notifications.
            PSPs use webhooks to notify merchants of payment status changes.

        In Real System:
            - PSP sends HTTPS POST to callback_url
            - Request includes HMAC signature for verification
            - Merchant verifies signature and processes update
            - Returns 200 OK to acknowledge receipt

        Args:
            token: Token from register_payment()
            callback_url: URL to send webhook to

        Returns:
            Webhook payload that would be POSTed
        """
        result = self.get_payment_status(token)
        if not result:
            logger.error(f"[PSP] Cannot send webhook: no payment found for token={token}")
            return {}

        webhook_payload = {
            "event": "payment.succeeded" if result.status == PaymentStatus.SUCCESS else "payment.failed",
            "token": token,
            "status": result.status.value,
            "transaction_id": result.transaction_id,
            "timestamp": int(time.time()),
            "signature": self._generate_webhook_signature(token, result.status.value)
        }

        if result.error_message:
            webhook_payload["error"] = result.error_message

        logger.info(
            f"[PSP] Webhook simulated: token={token}, status={result.status.value}, "
            f"url={callback_url}"
        )

        return webhook_payload

    def _get_hosted_page_url(self, token: str) -> str:
        """Generate mock hosted payment page URL."""
        return f"https://psp-mock.example.com/checkout?token={token}"

    def _generate_webhook_signature(self, token: str, status: str) -> str:
        """
        Generate mock HMAC signature for webhook verification.

        In Real System:
            signature = HMAC-SHA256(webhook_payload, shared_secret)
            Merchant verifies signature to prevent spoofed webhooks.
        """
        # Mock signature (real would use HMAC-SHA256)
        return f"sha256_{uuid.uuid4().hex[:16]}"

    def reset(self):
        """Reset PSP state (useful for testing)."""
        self._nonce_to_token.clear()
        self._token_to_result.clear()
        logger.info("[PSP] State reset")


# Singleton instance for app-wide use
_psp_instance: Optional[PSPMockService] = None


def get_psp_service(success_rate: float = 0.9) -> PSPMockService:
    """
    Get singleton PSP service instance.

    Args:
        success_rate: Payment success probability (0.0 to 1.0)

    Returns:
        PSPMockService instance
    """
    global _psp_instance
    if _psp_instance is None:
        _psp_instance = PSPMockService(success_rate=success_rate)
    return _psp_instance
