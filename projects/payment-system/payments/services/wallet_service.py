"""
Wallet Service - Manages account balances

System Design Concept:
    Implements [[optimistic-locking]] using Django's select_for_update() to
    prevent race conditions during concurrent balance updates.

Simulates:
    - Stripe Connect balances
    - PayPal wallet
    - Digital wallet systems

At Scale:
    - Cache balances in Redis with write-through policy
    - Use database sharding by account_id
    - Implement event sourcing for complete audit trail
"""

import logging
from typing import Optional
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

from payments.models import WalletAccount, PaymentOrder

logger = logging.getLogger(__name__)


class InsufficientFundsError(Exception):
    """Raised when account has insufficient balance for debit."""
    pass


class WalletService:
    """
    Service for managing wallet account balances.

    System Design Concept:
        Uses database-level locks (SELECT FOR UPDATE) to ensure [[atomicity]]
        of balance updates. This prevents the lost update problem in concurrent
        transactions.

    Thread Safety:
        All public methods use @transaction.atomic to ensure ACID properties.
        select_for_update() acquires row-level lock until transaction commits.
    """

    @staticmethod
    @transaction.atomic
    def get_or_create_account(account_id: str, currency: str = 'USD') -> WalletAccount:
        """
        Get existing wallet account or create new one with zero balance.

        Args:
            account_id: Unique account identifier
            currency: ISO 4217 currency code

        Returns:
            WalletAccount instance
        """
        account, created = WalletAccount.objects.get_or_create(
            account_id=account_id,
            defaults={'currency': currency, 'balance_cents': 0}
        )

        if created:
            logger.info(f"[Wallet] Created new account: {account_id}, currency={currency}")
        else:
            logger.debug(f"[Wallet] Retrieved existing account: {account_id}")

        return account

    @staticmethod
    @transaction.atomic
    def credit_account(account_id: str, amount_cents: int) -> WalletAccount:
        """
        Add funds to account (incoming payment).

        System Design Concept:
            Uses [[optimistic-locking]] via select_for_update() to prevent
            race conditions when multiple transactions credit same account.

        Args:
            account_id: Account to credit
            amount_cents: Amount to add (in cents)

        Returns:
            Updated WalletAccount

        Raises:
            ValueError: If amount_cents is negative
        """
        if amount_cents < 0:
            raise ValueError(f"Credit amount must be positive, got {amount_cents}")

        # Acquire row-level lock to prevent concurrent modifications
        account = WalletAccount.objects.select_for_update().get_or_create(
            account_id=account_id,
            defaults={'balance_cents': 0}
        )[0]

        old_balance = account.balance_cents
        account.credit(amount_cents)

        logger.info(
            f"[Wallet] Credited {account_id}: "
            f"${old_balance / 100:.2f} -> ${account.balance_cents / 100:.2f} "
            f"(+${amount_cents / 100:.2f})"
        )

        return account

    @staticmethod
    @transaction.atomic
    def debit_account(
        account_id: str,
        amount_cents: int,
        allow_negative: bool = True
    ) -> WalletAccount:
        """
        Remove funds from account (outgoing payment).

        Args:
            account_id: Account to debit
            amount_cents: Amount to remove (in cents)
            allow_negative: If False, raise error on insufficient funds

        Returns:
            Updated WalletAccount

        Raises:
            ValueError: If amount_cents is negative
            InsufficientFundsError: If balance insufficient and allow_negative=False
        """
        if amount_cents < 0:
            raise ValueError(f"Debit amount must be positive, got {amount_cents}")

        # Acquire row-level lock
        account = WalletAccount.objects.select_for_update().get_or_create(
            account_id=account_id,
            defaults={'balance_cents': 0}
        )[0]

        if not allow_negative and account.balance_cents < amount_cents:
            raise InsufficientFundsError(
                f"Insufficient funds in {account_id}: "
                f"balance=${account.balance_cents / 100:.2f}, "
                f"required=${amount_cents / 100:.2f}"
            )

        old_balance = account.balance_cents
        account.debit(amount_cents)

        logger.info(
            f"[Wallet] Debited {account_id}: "
            f"${old_balance / 100:.2f} -> ${account.balance_cents / 100:.2f} "
            f"(-${amount_cents / 100:.2f})"
        )

        return account

    @staticmethod
    def get_balance(account_id: str) -> int:
        """
        Get current account balance.

        Args:
            account_id: Account to query

        Returns:
            Balance in cents (0 if account doesn't exist)
        """
        try:
            account = WalletAccount.objects.get(account_id=account_id)
            return account.balance_cents
        except ObjectDoesNotExist:
            logger.warning(f"[Wallet] Account {account_id} not found, returning 0 balance")
            return 0

    @staticmethod
    @transaction.atomic
    def process_payment_order(payment_order: PaymentOrder) -> bool:
        """
        Process wallet update for a successful payment order.

        System Design Concept:
            Implements [[idempotency]] by checking wallet_updated flag.
            This ensures same payment order doesn't credit seller twice.

        Flow:
            1. Check if already processed (idempotency)
            2. Credit seller account
            3. Mark payment_order.wallet_updated = True

        Args:
            payment_order: PaymentOrder to process

        Returns:
            True if processed, False if already processed (idempotent)

        Raises:
            ValueError: If payment order is not SUCCESS status
        """
        if payment_order.status != PaymentOrder.Status.SUCCESS:
            raise ValueError(
                f"Cannot process wallet update for non-SUCCESS payment: "
                f"{payment_order.payment_order_id} has status {payment_order.status}"
            )

        # Idempotency check: skip if already processed
        if payment_order.wallet_updated:
            logger.info(
                f"[Wallet] Payment order {payment_order.payment_order_id} "
                f"already processed (idempotent skip)"
            )
            return False

        # Credit seller with payment amount
        amount_cents = payment_order.amount_in_cents()
        WalletService.credit_account(
            account_id=payment_order.seller_account,
            amount_cents=amount_cents
        )

        # Mark as processed (within same transaction for atomicity)
        payment_order.wallet_updated = True
        payment_order.save(update_fields=['wallet_updated', 'updated_at'])

        logger.info(
            f"[Wallet] Processed payment order {payment_order.payment_order_id}: "
            f"credited {payment_order.seller_account} with ${amount_cents / 100:.2f}"
        )

        return True

    @staticmethod
    def get_account_details(account_id: str) -> Optional[dict]:
        """
        Get account details including balance and metadata.

        Args:
            account_id: Account to query

        Returns:
            Dict with account details or None if not found
        """
        try:
            account = WalletAccount.objects.get(account_id=account_id)
            return {
                'account_id': account.account_id,
                'balance_cents': account.balance_cents,
                'balance_dollars': account.balance_dollars,
                'currency': account.currency,
                'created_at': account.created_at.isoformat(),
                'updated_at': account.updated_at.isoformat()
            }
        except ObjectDoesNotExist:
            return None
