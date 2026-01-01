---
tags:
  - system-design
  - payment-system
  - analysis
  - financial-systems
created: 2026-01-01
status: in-progress
source: "System Design Interview Vol 2 - Chapter 11: Payment System"
---

# Payment System — Analysis

## Overview

A payment system enables financial transactions by transferring monetary value between parties. This implementation focuses on an e-commerce payment backend (like Amazon's) that handles both **pay-in flow** (customer pays platform) and **pay-out flow** (platform pays seller). The system integrates with third-party Payment Service Providers (PSPs) like Stripe to process payments while maintaining strict reliability, consistency, and security guarantees for ~1M transactions/day (~10 TPS).

## Core Components

| Component | Purpose | Simulates |
|-----------|---------|-----------|
| Payment Service | Orchestrates payment flow, risk checks, coordinates wallet/ledger updates | Stripe/PayPal payment orchestration |
| Payment Executor | Executes individual payment orders via PSP | PSP API integration layer |
| PSP Mock | Simulates third-party payment processor (Stripe, Braintree) | Stripe API, card schemes (Visa/MasterCard) |
| Ledger | Double-entry accounting system for financial records | Immutable financial ledger (Square's approach) |
| Wallet | Tracks merchant/user account balances | Digital wallet service |
| Reconciliation Service | Nightly settlement file comparison to detect inconsistencies | Financial reconciliation system |
| Retry/Dead Letter Queues | Handles transient failures and persistent errors | Kafka-based retry infrastructure (Uber's approach) |

## Concepts Demonstrated

> [!tip] Key Learning Areas
> - [[idempotency]]: Preventing double charges using idempotency keys (UUIDs) and nonce tokens
> - [[exactly-once-delivery]]: Combining at-least-once (retry) + at-most-once (idempotency) semantics
> - [[double-entry-accounting]]: Every transaction debits one account and credits another with same amount
> - [[reconciliation]]: Asynchronous verification between internal services and external PSPs
> - [[eventual-consistency]]: Handling distributed state across payment/wallet/ledger services
> - [[retry-strategies]]: Exponential backoff, retry queues, dead letter queues
> - [[distributed-transactions]]: Managing state across multiple services without 2PC
> - [[PSP-integration]]: Hosted payment pages, webhooks, nonce/token pattern
> - [[acid-transactions]]: Database guarantees for financial data integrity

## Scope Decision

### ✅ Building (MVP)
- **Pay-in flow**: Complete flow from checkout to ledger update
  - Payment Service API (POST /v1/payments, GET /v1/payments/:id)
  - Payment Event and Payment Order models
  - Risk check simulation (mock)
  - Payment execution with PSP integration
  - Wallet balance updates
  - Double-entry ledger recording
- **Idempotency layer**: UUID-based deduplication using database unique constraints
- **Retry mechanism**: Retry queue with exponential backoff
- **Django models**: PaymentEvent, PaymentOrder, LedgerEntry, WalletAccount
- **DRF APIs**: RESTful endpoints with proper serializers
- **Admin panel**: For debugging payment states
- **Demo script**: Simulates complete payment flow with retries

### 🔄 Simulating
- **PSP (Payment Service Provider)**: Mock Stripe-like API with hosted payment page flow
  - Returns nonce/token pairs
  - Simulates payment processing (90% success rate)
  - Webhook callbacks for status updates
- **Risk check service**: Simple mock (always passes for demo)
- **Reconciliation**: Simplified nightly job that compares ledger vs wallet
- **Card schemes (Visa/MasterCard)**: Abstracted away inside PSP mock
- **Distributed message queue**: Use Django-Q or Celery with Redis for async tasks

### ⏭️ Skipping
- **Pay-out flow**: Out of scope (Chapter mentions Tipalti integration, complex regulatory requirements)
- **Multi-currency support**: Assume single currency (USD)
- **Real PSP integration**: No actual Stripe API calls (use mock)
- **PCI DSS compliance**: Not storing real card data (chapter recommends hosted pages)
- **Advanced reconciliation**: No automated mismatch classification/adjustment
- **Multiple PSP failover**: Single PSP mock only
- **Distributed tracing**: No OpenTelemetry/Jaeger
- **Geographic routing**: Single region

## Technology Choices

| Tool | Why |
|------|-----|
| Django 5.0+ | Batteries-included framework, ACID transactions, ORM for relational data, admin panel for debugging payment states |
| Django REST Framework | Clean API design with serializers, viewsets, built-in validation |
| PostgreSQL | ACID compliance critical for financial data, proven stability, mature tooling |
| Redis | Task queue backend (Celery/Django-Q), idempotency key caching |
| Celery/Django-Q | Async task processing for webhooks, reconciliation, retry logic |
| Docker Compose | Local dev environment with Postgres + Redis |

## Trade-offs from Chapter

> [!question] Key Trade-off: Synchronous vs Asynchronous Communication
> **Options**: HTTP sync calls vs Message queue (Kafka/RabbitMQ)
> **Choice**: Hybrid - Synchronous for critical path (payment execution), asynchronous for side effects (wallet/ledger updates, webhooks)
> **Reasoning**: Sync is simpler for MVP, but async prevents cascading failures. For 10 TPS, sync is acceptable. At scale (1000+ TPS), move to full async with Kafka.

> [!question] Key Trade-off: Database Selection
> **Options**: NoSQL (high throughput) vs RDBMS (ACID guarantees)
> **Choice**: PostgreSQL (RDBMS)
> **Reasoning**: Financial systems prioritize correctness over performance. 10 TPS is trivial for Postgres. ACID transactions prevent data loss. Proven stability in finance (5+ years industry usage).

> [!question] Key Trade-off: Storing Credit Card Data
> **Options**: Store encrypted cards internally vs Use PSP hosted pages
> **Choice**: PSP hosted pages (Stripe Checkout)
> **Reasoning**: Avoid PCI DSS compliance burden. PSP handles card data, returns tokens. Our system never sees raw card numbers.

> [!question] Key Trade-off: Retry Strategy
> **Options**: Immediate retry, fixed intervals, exponential backoff, cancel
> **Choice**: Exponential backoff with max 5 retries
> **Reasoning**: Prevents thundering herd. Network issues unlikely to resolve immediately. After 5 failures, route to dead letter queue for manual investigation.

> [!question] Key Trade-off: Consistency Model
> **Options**: Strong consistency (2PC) vs Eventual consistency (reconciliation)
> **Choice**: Eventual consistency with daily reconciliation
> **Reasoning**: 2PC doesn't work with external PSPs. Reconciliation is industry standard (banks send settlement files nightly). Accepts temporary inconsistency for resilience.

## Open Questions
- [ ] Should we implement webhook signature verification (HMAC) for PSP callbacks?
- [ ] How long should idempotency keys be cached? (Chapter doesn't specify, common: 24 hours)
- [ ] Should payment orders have an expiration time? (Common: 15 minutes for checkout sessions)
- [ ] Do we need database read replicas for the 10 TPS load? (Probably not, but good for production discussion)
- [ ] Should we implement circuit breaker for PSP calls? (Useful at scale)

## System Scale Considerations

**Current**: 1M transactions/day = **10 TPS**

- Single Postgres instance handles 10 TPS easily (can do 1000s TPS)
- Focus is on **correctness** not **performance**
- Bottleneck is external PSP latency (200-500ms typical)
- At 100x scale (1000 TPS), need:
  - Read replicas for GET endpoints
  - Kafka for async processing
  - Database sharding by merchant_id
  - Caching layer for wallet balances

## Security Considerations (From Chapter)

| Threat | Mitigation |
|--------|------------|
| Request eavesdropping | HTTPS/TLS for all API calls |
| Data tampering | Request signing, integrity checks |
| Man-in-the-middle | SSL certificate pinning |
| Password storage | bcrypt with salt (for user auth) |
| Card theft | Tokenization (PSP handles cards) |
| DDoS | Rate limiting (10 req/min per user) |
| Fraud | Address verification (AVS), CVV checks (PSP handles) |
| Double payment | Idempotency keys |

## Next Steps

This analysis establishes the foundation. Proceeding to architecture design will define:
- Detailed component interactions (sequence diagrams)
- Database schemas with foreign key relationships
- API request/response formats
- State machine for payment_order_status transitions
- Error handling flows (retry vs dead letter)
