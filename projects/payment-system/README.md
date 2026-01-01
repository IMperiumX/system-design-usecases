# Payment System Implementation

A production-grade payment system implementation based on **System Design Interview Vol 2 - Chapter 11: Payment System**. This project demonstrates key concepts like double-entry accounting, idempotency, PSP integration, and distributed transaction management.

## 📚 What This Teaches

### Core System Design Concepts

- **[[idempotency]]** - Preventing double charges using UUID-based deduplication
- **[[exactly-once-delivery]]** - Combining retry (at-least-once) + idempotency (at-most-once)
- **[[double-entry-accounting]]** - Immutable ledger where every transaction balances to zero
- **[[eventual-consistency]]** - Reconciliation instead of 2PC for distributed state
- **[[saga-pattern]]** - Coordinating multi-service transactions without distributed locks
- **[[PSP-integration]]** - Hosted payment pages, webhooks, and tokenization
- **[[optimistic-locking]]** - Preventing race conditions with database row-level locks

### Real-World Patterns

- **Payment Service Provider (PSP) Integration** - Simulates Stripe/PayPal API
- **Wallet System** - Digital balance management with ACID guarantees
- **Ledger System** - Append-only financial audit trail (like Square's Books)
- **Retry Mechanisms** - Exponential backoff with dead letter queues
- **Webhook Callbacks** - Async payment status notifications

## 🏗️ Architecture

```
┌─────────┐      ┌──────────────────┐      ┌─────────┐
│ Client  │─────▶│ Payment Service  │─────▶│   PSP   │
└─────────┘      └──────────────────┘      └─────────┘
                         │
                         ├─────▶ Wallet Service
                         │
                         └─────▶ Ledger Service
```

### Components

| Component | Purpose | Simulates |
|-----------|---------|-----------|
| **Payment Service** | Orchestrates payment flow | Stripe Payment Intents |
| **PSP Mock** | Simulates third-party payment processor | Stripe API, Braintree |
| **Wallet Service** | Manages account balances | Stripe Connect, PayPal wallet |
| **Ledger Service** | Double-entry accounting | Square's Books |

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 16+
- Redis 7+
- uv (for virtual env management)

### Setup

```bash
# 1. Start infrastructure (Postgres + Redis)
make setup

# 2. Run migrations
make migrate

# 3. Run demo
make demo
```

### Run Development Server

```bash
# Start API server
make run

# Create admin user
python manage.py createsuperuser

# Access admin panel
open http://localhost:8000/admin/
```

## 📖 API Endpoints

### Create Payment

```http
POST /api/v1/payments
Content-Type: application/json

{
  "checkout_id": "checkout_abc123",
  "buyer_info": {
    "user_id": "user_123",
    "email": "buyer@example.com",
    "name": "John Doe"
  },
  "credit_card_info": {
    "token": "tok_visa_4242",
    "last4": "4242"
  },
  "payment_orders": [
    {
      "payment_order_id": "order_xyz789",
      "seller_account": "seller_456",
      "amount": "29.99",
      "currency": "USD"
    }
  ]
}
```

**Response**: `202 Accepted`

```json
{
  "checkout_id": "checkout_abc123",
  "payment_event_status": "PROCESSING",
  "payment_orders": [
    {
      "payment_order_id": "order_xyz789",
      "status": "SUCCESS",
      "amount": "29.99",
      "currency": "USD",
      "wallet_updated": true,
      "ledger_updated": true
    }
  ],
  "created_at": "2026-01-01T12:00:00Z"
}
```

### Get Payment Status

```http
GET /api/v1/payments/{payment_order_id}
```

### View Wallet Balance

```http
GET /api/v1/wallets/{account_id}
```

### View Ledger Entries

```http
GET /api/v1/ledger?account_id={account_id}
```

## 🎯 Demo Script Output

```bash
python scripts/demo.py
```

The demo shows:

1. **Payment Event Creation** - Creating checkout with multiple orders
2. **Payment Execution** - Processing via PSP (90% success rate)
3. **Wallet Updates** - Crediting seller accounts
4. **Ledger Recording** - Double-entry bookkeeping
5. **Balance Verification** - Proving debits = credits
6. **Idempotency Test** - Duplicate requests return same result
7. **Retry Logic** - Handling failed payments

## 🔍 System Design Deep Dive

### Idempotency

**Problem**: What if a user clicks "Pay" twice?

**Solution**: Use `payment_order_id` as idempotency key. Duplicate requests return cached response.

```python
# Database unique constraint enforces idempotency
payment_order_id = models.CharField(max_length=255, primary_key=True)
```

### Double-Entry Accounting

**Principle**: Every transaction creates TWO ledger entries (debit + credit) that sum to zero.

**Example**:
```
Transaction: Buyer pays $10 to Seller

Entry 1: DR buyer  $10.00  (money leaving)
Entry 2: CR seller $10.00  (money entering)

Sum: $10 - $10 = $0 ✓
```

**Benefits**:
- Self-verifying (detect bugs via imbalance)
- Complete audit trail
- Industry standard for 500+ years

### Retry Strategy

**Transient Errors** (retryable):
- Network timeouts
- PSP rate limiting
- Database deadlocks

**Strategy**: Exponential backoff (1s, 2s, 4s, 8s, 16s), max 5 retries

**Permanent Errors** (non-retryable):
- Invalid card
- Insufficient funds
- Fraud detected

**Action**: Mark FAILED, alert user

### At Scale Considerations

| Current (10 TPS) | 100x Growth (1000 TPS) |
|------------------|------------------------|
| Single Postgres | Postgres read replicas + sharding by `seller_id` |
| Synchronous API | Kafka for async wallet/ledger updates |
| No caching | Redis cache for wallet balances |
| Single region | Multi-region deployment with reconciliation |

## 📊 Database Schema

### Payment Order State Machine

```
NOT_STARTED ──▶ EXECUTING ──▶ SUCCESS
                    │
                    └──▶ FAILED ──▶ EXECUTING (retry)
```

### Models

- **PaymentEvent**: Checkout session (aggregate root)
- **PaymentOrder**: Individual payment from buyer to seller
- **WalletAccount**: Account balance in cents (integer for precision)
- **LedgerEntry**: Immutable double-entry record

## 🎓 Interview Prep

### Clarifying Questions to Ask

1. What payment methods do we support? (cards, bank transfers, digital wallets)
2. Do we handle payment processing ourselves or use a PSP?
3. What's the expected scale? (TPS, daily volume)
4. Do we need to support refunds? Chargebacks?
5. What currencies do we need to support?
6. Do we need real-time reconciliation or nightly batch?

### Key Trade-offs

| Decision | Options | Our Choice | Reasoning |
|----------|---------|------------|-----------|
| Store card data | Yes / No | **No** (use PSP hosted pages) | Avoid PCI DSS compliance burden |
| Consistency model | Strong (2PC) / Eventual | **Eventual** (reconciliation) | 2PC doesn't work with external PSPs |
| Database | NoSQL / RDBMS | **RDBMS** (Postgres) | Financial data needs ACID guarantees |
| Retry strategy | Immediate / Exponential backoff | **Exponential backoff** | Prevents thundering herd |

### Follow-up Questions & Answers

**Q: How do you prevent double charging?**
A: Idempotency using `payment_order_id` as unique key. PSP also uses this as their idempotency key.

**Q: What if the ledger update fails but wallet succeeds?**
A: Reconciliation process (nightly) detects mismatches and alerts finance team. We also check `ledger_updated` flag before considering payment complete.

**Q: How do you handle PSP downtime?**
A: Retry with exponential backoff up to 5 times. After that, dead letter queue for manual investigation. Circuit breaker prevents cascading failures.

**Q: How would you scale to 10,000 TPS?**
A:
1. Database sharding by `seller_account`
2. Kafka for async wallet/ledger updates
3. Redis cache for wallet balances (write-through)
4. Read replicas for GET endpoints
5. Multi-region deployment with regional reconciliation

## 📁 Project Structure

```
payment-system/
├── docs/
│   ├── 00-analysis.md       # System requirements & scope
│   ├── 01-architecture.md   # Component design & data flow
│   └── 02-learnings.md      # Interview prep & takeaways
├── payments/
│   ├── models.py            # Django ORM models
│   ├── serializers.py       # DRF serializers
│   ├── views.py             # API viewsets
│   ├── admin.py             # Admin panel config
│   ├── services/
│   │   ├── payment_service.py    # Main orchestrator
│   │   ├── psp_mock.py           # PSP simulator
│   │   ├── wallet_service.py     # Balance management
│   │   └── ledger_service.py     # Double-entry accounting
│   └── urls.py              # API routes
├── scripts/
│   └── demo.py              # Interactive demo
├── docker-compose.yml       # Postgres + Redis
├── requirements.txt         # Python dependencies
├── Makefile                 # Development commands
└── README.md                # This file
```

## 🧪 Testing

```bash
# Run tests
make test

# Check ledger balance
python manage.py shell_plus
>>> from payments.services.ledger_service import LedgerService
>>> LedgerService.verify_books_balance()
{'balanced': True, 'total_debits_cents': 4549, 'total_credits_cents': 4549, 'difference_cents': 0}
```

## 🔗 Related Implementations

- [URL Shortener](../url-shortener/) - Hashing, caching basics
- [Rate Limiter](../rate-limiter/) - Token bucket, sliding window
- [Distributed ID Generator](../id-generator/) - Snowflake algorithm

## 📚 References

- [System Design Interview Vol 2 - Chapter 11](https://www.amazon.com/System-Design-Interview-Insiders-Guide/dp/1736049119)
- [Stripe API Documentation](https://stripe.com/docs/api)
- [Square Books - Immutable Accounting](https://developer.squareup.com/blog/books-an-immutable-double-entry-accounting-database-service/)
- [Double-Entry Bookkeeping](https://en.wikipedia.org/wiki/Double-entry_bookkeeping)

## ⚖️ License

Educational purposes only. Not for production use without proper security audits.
