"""
Ledger Service - Double-entry accounting system

System Design Concept:
    Implements [[double-entry-accounting]] where every transaction creates
    TWO immutable entries (debit + credit) that must sum to zero.

Simulates:
    Square's immutable accounting database:
    https://developer.squareup.com/blog/books-an-immutable-double-entry-accounting-database-service/

At Scale:
    - Use append-only log (Kafka) for writes
    - Materialized views for balance aggregation
    - Partition by date for time-series queries
    - Implement CQRS (separate read/write models)
"""

import logging
from typing import List, Tuple, Optional
from django.db import transaction
from django.db.models import Sum, Q

from payments.models import LedgerEntry, PaymentOrder

logger = logging.getLogger(__name__)


class LedgerService:
    """
    Service for recording financial transactions using double-entry accounting.

    System Design Concept:
        [[double-entry-accounting]]: Every transaction creates TWO entries:
        - Debit (DR): Money leaving an account
        - Credit (CR): Money entering an account

        The fundamental equation: SUM(debits) - SUM(credits) = 0

        This provides:
        - End-to-end traceability
        - Built-in error detection (unbalanced books indicate bug)
        - Complete audit trail

    Immutability:
        Ledger entries are NEVER updated or deleted. Corrections are made
        by creating offsetting entries (reversals).
    """

    @staticmethod
    @transaction.atomic
    def record_payment(payment_order: PaymentOrder) -> Tuple[LedgerEntry, LedgerEntry]:
        """
        Record a payment transaction in the ledger.

        System Design Concept:
            Implements [[idempotency]] by checking ledger_updated flag.
            Creates double-entry (debit buyer, credit seller).

        Args:
            payment_order: Successful PaymentOrder to record

        Returns:
            Tuple of (debit_entry, credit_entry)

        Raises:
            ValueError: If payment order is not SUCCESS or already recorded
        """
        if payment_order.status != PaymentOrder.Status.SUCCESS:
            raise ValueError(
                f"Cannot record non-SUCCESS payment: "
                f"{payment_order.payment_order_id} has status {payment_order.status}"
            )

        # Idempotency check: skip if already recorded
        if payment_order.ledger_updated:
            logger.info(
                f"[Ledger] Payment {payment_order.payment_order_id} "
                f"already recorded (idempotent skip)"
            )
            # Return existing entries
            entries = list(payment_order.ledger_entries.all())
            if len(entries) == 2:
                return entries[0], entries[1]
            else:
                logger.warning(
                    f"[Ledger] Expected 2 entries for {payment_order.payment_order_id}, "
                    f"found {len(entries)}"
                )
                return entries[0], entries[0] if entries else (None, None)

        amount_cents = payment_order.amount_in_cents()

        # Create double-entry transaction
        debit_entry, credit_entry = LedgerEntry.create_transaction(
            transaction_id=payment_order.payment_order_id,
            debit_account=payment_order.buyer_account,
            credit_account=payment_order.seller_account,
            amount_cents=amount_cents,
            payment_order=payment_order,
            description=f"Payment {payment_order.payment_order_id}: "
                        f"{payment_order.buyer_account} → {payment_order.seller_account}"
        )

        # Mark payment order as recorded (within same transaction)
        payment_order.ledger_updated = True
        payment_order.save(update_fields=['ledger_updated', 'updated_at'])

        logger.info(
            f"[Ledger] Recorded payment {payment_order.payment_order_id}: "
            f"DR {payment_order.buyer_account} / CR {payment_order.seller_account} "
            f"${amount_cents / 100:.2f}"
        )

        return debit_entry, credit_entry

    @staticmethod
    @transaction.atomic
    def record_refund(
        original_payment_order: PaymentOrder,
        refund_transaction_id: str
    ) -> Tuple[LedgerEntry, LedgerEntry]:
        """
        Record a refund (reversal of original payment).

        System Design Concept:
            Refunds create NEW entries (not deleting original ones).
            This maintains immutability of the ledger.

        Args:
            original_payment_order: Original payment to refund
            refund_transaction_id: Unique ID for refund transaction

        Returns:
            Tuple of (debit_entry, credit_entry) for refund
        """
        if not original_payment_order.ledger_updated:
            raise ValueError(
                f"Cannot refund payment {original_payment_order.payment_order_id} "
                f"that hasn't been recorded in ledger"
            )

        amount_cents = original_payment_order.amount_in_cents()

        # Refund reverses original: debit seller, credit buyer
        debit_entry, credit_entry = LedgerEntry.create_transaction(
            transaction_id=refund_transaction_id,
            debit_account=original_payment_order.seller_account,  # Reversed
            credit_account=original_payment_order.buyer_account,  # Reversed
            amount_cents=amount_cents,
            payment_order=None,  # Refunds don't link to payment order
            description=f"Refund of {original_payment_order.payment_order_id}"
        )

        logger.info(
            f"[Ledger] Recorded refund {refund_transaction_id}: "
            f"DR {original_payment_order.seller_account} / "
            f"CR {original_payment_order.buyer_account} ${amount_cents / 100:.2f}"
        )

        return debit_entry, credit_entry

    @staticmethod
    def get_account_balance(account_id: str) -> int:
        """
        Calculate account balance from ledger entries.

        Formula:
            balance = SUM(credits) - SUM(debits)

        Args:
            account_id: Account to calculate balance for

        Returns:
            Balance in cents
        """
        aggregates = LedgerEntry.objects.filter(
            account_id=account_id
        ).aggregate(
            total_credits=Sum('credit_cents'),
            total_debits=Sum('debit_cents')
        )

        credits = aggregates['total_credits'] or 0
        debits = aggregates['total_debits'] or 0
        balance = credits - debits

        logger.debug(
            f"[Ledger] Balance for {account_id}: "
            f"${balance / 100:.2f} (CR ${credits / 100:.2f} - DR ${debits / 100:.2f})"
        )

        return balance

    @staticmethod
    def get_transaction_entries(transaction_id: str) -> List[LedgerEntry]:
        """
        Get all ledger entries for a transaction.

        Args:
            transaction_id: Transaction to query

        Returns:
            List of LedgerEntry objects (should be 2 for normal transactions)
        """
        entries = list(
            LedgerEntry.objects.filter(
                transaction_id=transaction_id
            ).order_by('created_at')
        )

        logger.debug(
            f"[Ledger] Found {len(entries)} entries for transaction {transaction_id}"
        )

        return entries

    @staticmethod
    def verify_books_balance() -> dict:
        """
        Verify that all ledger entries balance (sum to zero).

        System Design Concept:
            The [[double-entry-accounting]] principle guarantees:
            SUM(all debits) - SUM(all credits) = 0

            Any non-zero result indicates a data integrity issue.

        Returns:
            Dict with verification results
        """
        aggregates = LedgerEntry.objects.aggregate(
            total_debits=Sum('debit_cents'),
            total_credits=Sum('credit_cents')
        )

        total_debits = aggregates['total_debits'] or 0
        total_credits = aggregates['total_credits'] or 0
        difference = total_debits - total_credits

        balanced = (difference == 0)

        result = {
            'balanced': balanced,
            'total_debits_cents': total_debits,
            'total_credits_cents': total_credits,
            'difference_cents': difference,
            'total_entries': LedgerEntry.objects.count()
        }

        if balanced:
            logger.info(
                f"[Ledger] Books are balanced: "
                f"DR ${total_debits / 100:.2f} = CR ${total_credits / 100:.2f}"
            )
        else:
            logger.error(
                f"[Ledger] ⚠️ BOOKS OUT OF BALANCE! "
                f"DR ${total_debits / 100:.2f} - CR ${total_credits / 100:.2f} = "
                f"${difference / 100:.2f}"
            )

        return result

    @staticmethod
    def get_account_statement(
        account_id: str,
        limit: int = 100
    ) -> List[dict]:
        """
        Get account statement (transaction history).

        Args:
            account_id: Account to get statement for
            limit: Maximum number of entries to return

        Returns:
            List of dicts with entry details and running balance
        """
        entries = LedgerEntry.objects.filter(
            account_id=account_id
        ).order_by('-created_at')[:limit]

        statement = []
        for entry in entries:
            statement.append({
                'date': entry.created_at.isoformat(),
                'transaction_id': entry.transaction_id,
                'description': entry.description,
                'debit_cents': entry.debit_cents,
                'credit_cents': entry.credit_cents,
                'amount_dollars': entry.amount_dollars,
                'type': 'debit' if entry.debit_cents > 0 else 'credit'
            })

        return statement
