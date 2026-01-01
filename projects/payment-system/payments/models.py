"""
Payment System Models

System Design Concept:
    These models implement the core entities of a payment system as described in
    "System Design Interview Vol 2 - Chapter 11". The design emphasizes ACID
    transactions, idempotency, and double-entry accounting.

Key Patterns:
    - [[idempotency]]: payment_order_id serves as unique deduplication key
    - [[double-entry-accounting]]: LedgerEntry enforces debit/credit balance
    - [[state-machine]]: PaymentOrder.status tracks execution lifecycle
    - [[aggregate-root]]: PaymentEvent contains multiple PaymentOrders
"""

import uuid
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone


class PaymentEvent(models.Model):
    """
    Payment event representing a single checkout session.

    A payment event may contain multiple payment orders (e.g., buying from
    multiple sellers in a single checkout).

    System Design Concept:
        Acts as [[aggregate-root]] in Domain-Driven Design. The checkout_id
        serves as the idempotency key for the entire payment event.

    At Scale:
        - Index on (is_payment_done, created_at) for monitoring dashboards
        - Partition by created_at for time-series queries
    """
    checkout_id = models.CharField(
        max_length=255,
        primary_key=True,
        help_text="Globally unique checkout identifier (idempotency key)"
    )
    buyer_info = models.JSONField(
        help_text="Buyer details: {user_id, email, name}"
    )
    seller_info = models.JSONField(
        null=True,
        blank=True,
        help_text="Seller details (optional for multi-seller checkouts)"
    )
    credit_card_info = models.JSONField(
        help_text="Tokenized card info: {token, last4} - NEVER store raw card data!"
    )
    is_payment_done = models.BooleanField(
        default=False,
        help_text="True when ALL payment orders under this checkout are complete"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment_events'
        indexes = [
            models.Index(fields=['is_payment_done', 'created_at']),
        ]

    def __str__(self):
        return f"PaymentEvent({self.checkout_id}, done={self.is_payment_done})"


class PaymentOrder(models.Model):
    """
    Individual payment order from buyer to seller.

    System Design Concept:
        Implements [[idempotency]] and [[state-machine]] patterns.
        The payment_order_id is used as:
        1. Primary key in our system
        2. Idempotency key for PSP requests
        3. Nonce for PSP payment registration

    Status Transitions:
        NOT_STARTED -> EXECUTING -> SUCCESS/FAILED
        FAILED can retry -> EXECUTING (up to MAX_RETRY_ATTEMPTS)

    At Scale:
        - Use database sharding by seller_account for load distribution
        - Cache frequently queried orders in Redis
    """

    class Status(models.TextChoices):
        NOT_STARTED = 'NOT_STARTED', 'Not Started'
        EXECUTING = 'EXECUTING', 'Executing'
        SUCCESS = 'SUCCESS', 'Success'
        FAILED = 'FAILED', 'Failed'

    payment_order_id = models.CharField(
        max_length=255,
        primary_key=True,
        help_text="Globally unique payment order ID (idempotency key)"
    )
    checkout = models.ForeignKey(
        PaymentEvent,
        on_delete=models.CASCADE,
        related_name='orders',
        help_text="Parent checkout session"
    )
    buyer_account = models.CharField(
        max_length=255,
        help_text="Buyer's account identifier"
    )
    seller_account = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Seller's account identifier"
    )

    # Financial fields stored as strings to avoid float precision issues
    amount = models.CharField(
        max_length=50,
        help_text="Transaction amount as string (e.g., '29.99') to avoid float errors"
    )
    currency = models.CharField(
        max_length=3,
        default='USD',
        help_text="ISO 4217 currency code (USD, EUR, etc.)"
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NOT_STARTED,
        db_index=True,
        help_text="Current execution status"
    )

    # PSP integration
    psp_token = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Token returned by PSP after payment registration"
    )
    psp_nonce = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Nonce sent to PSP (usually same as payment_order_id)"
    )

    # Downstream service tracking (for idempotent updates)
    wallet_updated = models.BooleanField(
        default=False,
        help_text="True if wallet service has processed this payment"
    )
    ledger_updated = models.BooleanField(
        default=False,
        help_text="True if ledger service has recorded this payment"
    )

    # Retry logic
    retry_count = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Number of retry attempts"
    )
    last_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of last retry attempt"
    )
    error_message = models.TextField(
        null=True,
        blank=True,
        help_text="Error details for failed payments"
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payment_orders'
        indexes = [
            models.Index(fields=['status', 'created_at']),  # Dashboard queries
            models.Index(fields=['seller_account', 'created_at']),  # Seller reports
            models.Index(fields=['buyer_account', 'created_at']),  # Buyer history
        ]

    def __str__(self):
        return f"PaymentOrder({self.payment_order_id}, {self.status}, ${self.amount})"

    def amount_in_cents(self) -> int:
        """Convert string amount to cents (integer) for safe arithmetic."""
        return int(float(self.amount) * 100)

    def can_retry(self, max_attempts: int = 5) -> bool:
        """Check if payment can be retried based on retry count."""
        return self.retry_count < max_attempts and self.status == self.Status.FAILED


class WalletAccount(models.Model):
    """
    Digital wallet account storing user/merchant balances.

    System Design Concept:
        Uses [[optimistic-locking]] via SELECT FOR UPDATE to prevent race
        conditions during concurrent balance updates.

    Simplifications:
        - Balances stored in cents (integer) to avoid float precision errors
        - No overdraft protection (can go negative for demo purposes)
        - Single currency per account

    At Scale:
        - Cache balances in Redis with write-through policy
        - Use database sharding by account_id
        - Implement event sourcing for audit trail
    """
    account_id = models.CharField(
        max_length=255,
        primary_key=True,
        help_text="Unique account identifier (user_id or seller_id)"
    )
    balance_cents = models.BigIntegerField(
        default=0,
        help_text="Account balance in cents (to avoid float precision issues)"
    )
    currency = models.CharField(
        max_length=3,
        default='USD',
        help_text="ISO 4217 currency code"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wallet_accounts'
        constraints = [
            models.CheckConstraint(
                check=models.Q(balance_cents__gte=-10000000),  # -$100k min for demo
                name='balance_not_too_negative'
            )
        ]

    def __str__(self):
        return f"Wallet({self.account_id}, ${self.balance_cents / 100:.2f})"

    @property
    def balance_dollars(self) -> float:
        """Return balance in dollars (for display only, never use for calculations)."""
        return self.balance_cents / 100.0

    def credit(self, amount_cents: int):
        """Add funds to the account (thread-safe when used with SELECT FOR UPDATE)."""
        self.balance_cents += amount_cents
        self.save(update_fields=['balance_cents', 'updated_at'])

    def debit(self, amount_cents: int):
        """Remove funds from the account (thread-safe when used with SELECT FOR UPDATE)."""
        self.balance_cents -= amount_cents
        self.save(update_fields=['balance_cents', 'updated_at'])


class LedgerEntry(models.Model):
    """
    Immutable double-entry accounting ledger.

    System Design Concept:
        Implements [[double-entry-accounting]] principle. Every transaction
        creates TWO entries:
        - One with debit (money leaving account)
        - One with credit (money entering account)

        The sum of ALL debit_cents and credit_cents across ALL entries must
        equal zero. This provides end-to-end traceability.

    Simulates:
        Square's immutable accounting database service:
        https://developer.squareup.com/blog/books-an-immutable-double-entry-accounting-database-service/

    Constraints:
        - Entry must have EITHER debit OR credit (not both, not neither)
        - Entries are append-only (never updated or deleted)
        - transaction_id links debit/credit pairs

    At Scale:
        - Use append-only log (Kafka) for writes
        - Materialized views for balance queries
        - Partition by created_at for time-series queries
    """
    entry_id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Unique ledger entry identifier"
    )
    transaction_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Links debit/credit pair entries (usually payment_order_id)"
    )
    account_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Account being debited or credited"
    )

    # Financial fields (stored in cents)
    debit_cents = models.BigIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Amount debited (money leaving account)"
    )
    credit_cents = models.BigIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Amount credited (money entering account)"
    )
    currency = models.CharField(
        max_length=3,
        default='USD',
        help_text="ISO 4217 currency code"
    )

    # Optional link to payment order (for reconciliation)
    payment_order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='ledger_entries',
        help_text="Associated payment order"
    )

    # Metadata
    description = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Human-readable description of transaction"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ledger_entries'
        verbose_name_plural = 'Ledger entries'
        constraints = [
            # Must have EITHER debit OR credit (not both, not neither)
            models.CheckConstraint(
                check=(
                    models.Q(debit_cents__gt=0, credit_cents=0) |
                    models.Q(debit_cents=0, credit_cents__gt=0)
                ),
                name='entry_must_have_exactly_one_side'
            )
        ]
        indexes = [
            models.Index(fields=['transaction_id', 'created_at']),
            models.Index(fields=['account_id', 'created_at']),
        ]

    def __str__(self):
        if self.debit_cents > 0:
            return f"LedgerEntry(DR {self.account_id} ${self.debit_cents / 100:.2f})"
        else:
            return f"LedgerEntry(CR {self.account_id} ${self.credit_cents / 100:.2f})"

    @property
    def amount_cents(self) -> int:
        """Return the absolute amount (debit or credit)."""
        return max(self.debit_cents, self.credit_cents)

    @property
    def amount_dollars(self) -> float:
        """Return amount in dollars (for display only)."""
        return self.amount_cents / 100.0

    @classmethod
    def create_transaction(cls, transaction_id: str, debit_account: str,
                           credit_account: str, amount_cents: int,
                           payment_order=None, description: str = None):
        """
        Create a double-entry transaction (debit + credit pair).

        Args:
            transaction_id: Unique transaction identifier
            debit_account: Account to debit (money leaving)
            credit_account: Account to credit (money entering)
            amount_cents: Amount in cents
            payment_order: Optional PaymentOrder reference
            description: Optional human-readable description

        Returns:
            Tuple of (debit_entry, credit_entry)
        """
        debit_entry = cls.objects.create(
            transaction_id=transaction_id,
            account_id=debit_account,
            debit_cents=amount_cents,
            credit_cents=0,
            payment_order=payment_order,
            description=description or f"Debit {debit_account}"
        )
        credit_entry = cls.objects.create(
            transaction_id=transaction_id,
            account_id=credit_account,
            debit_cents=0,
            credit_cents=amount_cents,
            payment_order=payment_order,
            description=description or f"Credit {credit_account}"
        )
        return debit_entry, credit_entry
