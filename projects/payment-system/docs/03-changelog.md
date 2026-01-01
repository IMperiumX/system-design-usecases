---
tags:
  - system-design
  - payment-system
  - changelog
created: 2026-01-01
---

# Payment System — Changelog

## [2026-01-01] - Initial Implementation

### Added

**Core Models** (payments/models.py)
- `PaymentEvent` - Checkout session aggregate root with idempotency
- `PaymentOrder` - Individual payment with state machine (NOT_STARTED → EXECUTING → SUCCESS/FAILED)
- `WalletAccount` - Digital wallet with integer balance (cents) for precision
- `LedgerEntry` - Immutable double-entry accounting with CHECK constraints

**Services Layer**
- `PSPMockService` - Simulates Stripe/Braintree with 90% success rate, webhooks, and idempotency
- `WalletService` - Balance management with SELECT FOR UPDATE row-level locking
- `LedgerService` - Double-entry bookkeeping with automatic balance verification
- `PaymentService` - Main orchestrator implementing saga pattern for distributed transactions

**API Layer**
- POST `/api/v1/payments` - Create payment event and execute orders
- GET `/api/v1/payments/:id` - Query payment status
- POST `/api/v1/payments/:id/retry` - Manual retry for failed payments
- POST `/api/v1/webhooks/payment-status` - PSP webhook callback
- GET `/api/v1/wallets/:id` - Wallet balance lookup
- GET `/api/v1/ledger?account_id=X` - Ledger entries by account

**Admin Panel**
- Color-coded status badges for payment states
- Wallet/Ledger update flags (✓ W / ✗ L)
- Read-only ledger (append-only enforcement)
- Searchable by account IDs, transaction IDs

**Documentation**
- `docs/00-analysis.md` - Requirements, scope, technology choices
- `docs/01-architecture.md` - Component diagrams, API specs, data models
- `docs/02-learnings.md` - Interview prep, scaling considerations, key takeaways
- `README.md` - Quick start guide, API reference
- `scripts/demo.py` - Interactive demonstration of complete flow

**Infrastructure**
- `docker-compose.yml` - PostgreSQL + Redis for local development
- `Makefile` - Common commands (setup, migrate, demo, test)
- `.env.example` - Configuration template

### Decisions Made

**Technology Stack**
- **Django 5.0** - ACID transactions critical for financial data, chosen over NoSQL
- **SQLite for demo** - Compatibility with Python 3.13 (psycopg2 has issues), use PostgreSQL in production
- **DRF** - Clean serializers and viewsets for REST API
- **Integers for money** - Cents instead of floats to avoid precision errors
- **Strings for transmission** - Amount field stored as string `"29.99"` to prevent serialization issues

**Architectural Patterns**
- **Saga instead of 2PC** - Cannot use distributed transactions with external PSPs
- **Eventual consistency** - wallet_updated/ledger_updated flags track async state
- **Idempotency everywhere** - payment_order_id as both PK and PSP nonce
- **Exponential backoff** - 1s, 2s, 4s, 8s, 16s for retries (max 5 attempts)
- **Optimistic locking** - SELECT FOR UPDATE prevents lost wallet updates

**System Design Concepts Implemented**
- [[idempotency]] - UUID-based deduplication at multiple layers
- [[exactly-once-delivery]] - Retry + idempotency = exactly-once
- [[double-entry-accounting]] - Every transaction balances to zero
- [[saga-pattern]] - Distributed transaction coordination without locks
- [[optimistic-locking]] - Database row-level locks for concurrency
- [[eventual-consistency]] - Reconciliation over strong consistency
- [[state-machine]] - PaymentOrder status transitions

**Security Decisions**
- **No raw card storage** - Use PSP hosted pages (avoid PCI DSS compliance)
- **Tokenization** - Only store PSP tokens and last4 digits
- **Webhook signatures** - TODO: Implement HMAC-SHA256 verification for production
- **Rate limiting** - TODO: Add 10 payments/min per user limit

### Simplifications (vs Production)

**For Learning/Demo Purposes**
- PSP mock has deterministic 90% success rate (real PSPs vary by region, card type, etc.)
- Risk check always passes (real systems use ML models like Stripe Radar)
- Single currency (USD) only (production needs multi-currency with FX rates)
- Synchronous wallet/ledger updates (production uses Kafka for async)
- No circuit breaker for PSP calls (critical for resilience)
- SQLite instead of PostgreSQL (easier setup, but not production-ready)
- No actual PSP integration (would use Stripe SDK in reality)
- Simplified reconciliation (no CSV parsing, manual adjustment queues)

**Intentional Omissions**
- Pay-out flow (requires separate integration with Tipalti or similar)
- Refund flow (offsetting ledger entries)
- Chargeback handling (dispute management workflow)
- Multi-datacenter deployment (regional reconciliation complexity)
- Event sourcing (rebuild state from event log)
- CQRS (separate read/write models)

### Blockers / Questions Resolved

**Q: Python 3.13 + psycopg2 compatibility issue**
- **Solution**: Switched to SQLite for demo, documented PostgreSQL config for production

**Q: How to ensure wallet and ledger stay in sync?**
- **Solution**: Added `wallet_updated` and `ledger_updated` boolean flags. Reconciliation job can detect mismatches.

**Q: Should retry be automatic or manual?**
- **Solution**: Both! Automatic retry up to 5 times with exponential backoff. After that, manual retry via admin or API endpoint.

**Q: How to prevent duplicate webhook processing?**
- **Solution**: Webhooks contain `payment_order_id`. We check if already processed before updating state.

## Future Iterations

### Phase 2: Production Hardening
- [ ] Replace PSP mock with real Stripe SDK integration
- [ ] Implement webhook signature verification (HMAC-SHA256)
- [ ] Add circuit breaker pattern for PSP calls (prevent cascading failures)
- [ ] Switch to PostgreSQL with proper psycopg3 driver
- [ ] Implement Celery for async wallet/ledger updates
- [ ] Add comprehensive logging with correlation IDs

### Phase 3: Advanced Features
- [ ] Refund flow with offsetting ledger entries
- [ ] Recurring payments (subscriptions)
- [ ] Multi-currency support with FX rate API
- [ ] Pay-out flow integration
- [ ] Fraud detection with ML model
- [ ] Chargeback handling workflow

### Phase 4: Scale to 1000 TPS
- [ ] Kafka for event streaming
- [ ] Database sharding by seller_account
- [ ] Redis caching for wallet balances
- [ ] Read replicas for GET endpoints
- [ ] Horizontal scaling of API servers

### Phase 5: Observability
- [ ] OpenTelemetry distributed tracing
- [ ] Prometheus metrics + Grafana dashboards
- [ ] PagerDuty integration for alerts
- [ ] Real-time ledger balance monitoring
- [ ] Anomaly detection for payment patterns

## Known Issues

- SQLite doesn't fully support CHECK constraints (ledger entry validation may not work)
- No webhook signature verification (security risk in production)
- Synchronous wallet/ledger updates increase latency
- No rate limiting on payment creation endpoint
- PSP mock doesn't simulate all real-world edge cases (3D Secure, etc.)

## References

- Chapter 11: Payment System (System Design Interview Vol 2)
- Stripe API: https://stripe.com/docs/api
- Square Books: https://developer.squareup.com/blog/books-an-immutable-double-entry-accounting-database-service/
- Uber Payments: https://eng.uber.com/payments-platform/
