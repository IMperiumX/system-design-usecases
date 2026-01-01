---
tags:
  - system-design
  - payment-system
  - learnings
  - interview-prep
created: 2026-01-01
status: complete
---

# Payment System — Learnings

## What I Built

A production-grade e-commerce payment system that orchestrates transactions across multiple services (PSP, wallet, ledger) while guaranteeing exactly-once semantics and financial accuracy through double-entry accounting. The system handles ~10 TPS (1M transactions/day) and demonstrates key patterns like idempotency, eventual consistency, and distributed saga coordination without 2PC.

## Key Takeaways

> [!tip] Core Insight #1: Idempotency is Non-Negotiable in Financial Systems
> **What I learned**: Every payment endpoint MUST be idempotent. Using `payment_order_id` as both primary key and idempotency key prevents double charges even when:
> - User clicks "Pay" multiple times
> - Network timeouts cause client retries
> - Webhooks are delivered twice
>
> **Real-world impact**: Stripe reports that ~2% of payments experience duplicate requests. Without idempotency, this would mean millions in double charges.

> [!tip] Core Insight #2: Double-Entry Accounting Provides Built-in Error Detection
> **What I learned**: The 500-year-old accounting principle still applies to modern systems. Every transaction creates TWO ledger entries (debit + credit) that must sum to zero. Any imbalance indicates a bug.
>
> **Example from implementation**:
> ```python
> # Buyer pays $10 to Seller
> Entry 1: DR buyer  $10.00  # Money leaving
> Entry 2: CR seller $10.00  # Money entering
> Sum: $10 - $10 = $0 ✓       # Self-verifying
> ```
>
> **Real-world impact**: Square's Books service uses this pattern to process billions in transactions. The ledger is append-only (immutable) and provides complete audit trail.

> [!tip] Core Insight #3: Strong Consistency is Impossible with External PSPs
> **What I learned**: You cannot use 2PC (two-phase commit) with third-party PSPs. They don't participate in your distributed transaction protocol. The solution is:
> 1. **Eventual consistency** - Services update asynchronously
> 2. **Reconciliation** - Nightly batch job compares PSP settlement files vs our ledger
> 3. **Idempotency** - Ensures safe retries
>
> **Trade-off**: Accept temporary inconsistency for operational resilience. Reconciliation is the "last line of defense" to catch discrepancies.

> [!tip] Core Insight #4: Retry Logic Requires Exponential Backoff
> **What I learned**: Immediate retries create thundering herd problems. Exponential backoff (1s, 2s, 4s, 8s, 16s) spreads load and gives transient issues time to resolve.
>
> **Classification matters**:
> - **Transient errors** (network timeout) → Retry
> - **Permanent errors** (invalid card) → Don't retry
> - **Unclassified errors** → Retry up to max, then dead letter queue
>
> **Real-world example**: Uber's payment system uses Kafka with exponential backoff for retries, processing 15M+ rides/day reliably.

> [!tip] Core Insight #5: Store Money as Integers (Cents), Never Floats
> **What I learned**: Floating-point arithmetic is non-deterministic across systems. Storing amounts as cents (integers) ensures:
> - Exact precision (no 0.30000000004 errors)
> - Consistent serialization across languages/platforms
> - Simpler SQL aggregations (SUM works correctly)
>
> **Chapter recommendation**: Use strings for transmission (`"29.99"`), convert to integers for storage/computation, only use floats for display.

## Concepts Reinforced

- **[[idempotency]]** — Now I understand the nonce/token pattern from PSPs. The client sends `payment_order_id` as nonce, PSP returns token. Both serve as idempotency keys at different layers.

- **[[exactly-once-delivery]]** — This isn't magic! It's the combination of:
  - **At-least-once**: Retry until success
  - **At-most-once**: Idempotency check prevents duplicates
  - Mathematical proof: at-least-once AND at-most-once = exactly-once

- **[[saga-pattern]]** — Payment flow is a distributed saga coordinating PSP → Wallet → Ledger. Each step is idempotent. If any step fails, we retry (no compensation needed for successful steps because of idempotency).

- **[[optimistic-locking]]** — Using `SELECT FOR UPDATE` in wallet service prevents lost updates when two transactions credit same account concurrently. Row-level lock ensures serializable execution.

- **[[eventual-consistency]]** — The wallet_updated and ledger_updated flags track distributed state. If wallet succeeds but ledger fails, reconciliation detects the mismatch.

## At Scale

| Scale | What Changes | Why |
|-------|--------------|-----|
| **10x (100 TPS)** | Add Redis cache for wallet balances | Reduce database read load |
| | Use Celery for async wallet/ledger updates | Decouple payment execution from side effects |
| | Add database read replicas | Distribute GET request load |
| **100x (1000 TPS)** | Kafka for event streaming | Fully async architecture, better fault isolation |
| | Database sharding by `seller_account` | Horizontal scaling of writes |
| | Circuit breaker for PSP calls | Prevent cascading failures |
| | Multi-region deployment | Reduce latency, improve availability |
| **1000x (10,000 TPS)** | Event sourcing architecture | Store all state changes as events |
| | CQRS (separate read/write models) | Optimize queries independently from writes |
| | Dedicated reconciliation cluster | Handle settlement file processing at scale |
| | Machine learning for fraud detection | Real-time risk scoring instead of simple checks |

### Scaling Decisions

> [!question] When to shard the database?
> **Signal**: Write latency > 100ms or database CPU > 70%
> **Shard key**: `seller_account` (most queries filter by seller)
> **Trade-off**: Lose cross-shard transactions, need distributed transaction coordinator

> [!question] When to switch from sync to async?
> **Signal**: Payment API latency > 500ms due to wallet/ledger updates
> **Implementation**: Kafka topics for `payment.success` events
> **Trade-off**: More complex debugging, eventual consistency window increases

## Interview Prep

### Clarifying Questions I'd Ask

1. **Scale & Performance**
   - "What's the expected transaction volume?" (QPS, daily transactions)
   - "What's the acceptable latency for payment confirmation?"
   - "Do we need to support bursts (e.g., Black Friday traffic)?"

2. **Functional Requirements**
   - "What payment methods?" (cards, bank transfers, digital wallets, cash)
   - "Do we handle payment processing ourselves or use a PSP?"
   - "Do we need to support refunds? Chargebacks? Disputes?"
   - "What about recurring payments or subscriptions?"

3. **Non-Functional Requirements**
   - "What's the consistency requirement?" (strong vs eventual)
   - "How do we handle PSP downtime?"
   - "What currencies do we support?"
   - "Do we need PCI DSS compliance?" (affects card storage decisions)

4. **Scope Clarifications**
   - "Are we building pay-in only, or pay-out as well?"
   - "Do we need reconciliation with PSP settlement files?"
   - "How do we handle multi-currency conversions?"

### How I'd Explain This (5-Minute Whiteboard)

> **Opening**: "I'll design a payment system for an e-commerce platform handling 1M transactions/day. I'll focus on reliability over throughput since 10 TPS is easily handled by a single database."

**1. High-Level Components (1 min)**
```
[Client] → [Payment Service] → [PSP Mock]
              ↓
         [Wallet] + [Ledger]
```

**2. Data Flow (2 min)**

"When a user clicks 'Pay':
1. **Payment Service** receives checkout request with `checkout_id` (idempotency key)
2. **Risk Check** - fraud detection (simplified in our implementation)
3. **PSP Registration** - Get token for hosted payment page
4. **PSP Processing** - User enters card on PSP's page, we get webhook
5. **Wallet Update** - Credit seller account (with row-level lock)
6. **Ledger Recording** - Create debit/credit entries (double-entry)
7. **Completion** - Mark `is_payment_done=true`

Each step is idempotent so retries are safe."

**3. Key Design Decisions (2 min)**

"**Idempotency**: Use `payment_order_id` as primary key. Duplicate requests return cached response.

**Consistency**: Eventual consistency with daily reconciliation. Why? We can't use 2PC with external PSPs.

**Data Model**:
- `PaymentEvent` (checkout session) contains multiple `PaymentOrder`s
- `WalletAccount` stores balances in cents (integer precision)
- `LedgerEntry` is append-only (immutable audit trail)

**Error Handling**: Exponential backoff retry for transient errors. Dead letter queue after 5 failures."

### Follow-up Questions to Expect

**Q: "How do you prevent double charging if a user clicks 'Pay' twice?"**

A: Idempotency using `payment_order_id` as unique key. Here's the flow:

```python
# First click
payment_order = PaymentOrder.objects.create(
    payment_order_id="order_123",  # Primary key
    status="NOT_STARTED"
)
# Processes payment...

# Second click (duplicate)
try:
    PaymentOrder.objects.create(payment_order_id="order_123")
except IntegrityError:  # Duplicate key!
    # Return existing payment status
    return PaymentOrder.objects.get(payment_order_id="order_123")
```

The PSP also uses this ID as their idempotency key, so even if our check fails, PSP prevents duplicate charge.

---

**Q: "What if the wallet update succeeds but the ledger update fails?"**

A: We track this with boolean flags:
- `wallet_updated` = true
- `ledger_updated` = false

This indicates inconsistency. Solutions:

1. **Immediate**: Retry ledger update (idempotent operation)
2. **Eventual**: Reconciliation job detects mismatch and alerts finance team
3. **Prevention**: Use database transaction to update both flags atomically

In our implementation, we log errors and retry via message queue. Reconciliation is the safety net.

---

**Q: "How would you handle PSP downtime?"**

A: Multi-layered approach:

1. **Circuit Breaker**: After 5 consecutive failures, stop sending requests for 60s (prevent cascading failure)
2. **Retry Queue**: Route failed payments to Kafka retry topic with exponential backoff
3. **Fallback PSP**: If primary PSP is down > 5min, route to backup PSP
4. **User Communication**: Return "pending" status, notify user when complete
5. **Monitoring**: Alert on-call if PSP error rate > 1%

Real-world: Stripe has 99.99% uptime SLA, but we still need graceful degradation.

---

**Q: "How does reconciliation work?"**

A: Daily batch process:

```python
# 1. PSP sends settlement file (CSV)
psp_transactions = parse_settlement_file("stripe_2026-01-01.csv")

# 2. Query our ledger for same day
our_transactions = Ledger.objects.filter(date="2026-01-01")

# 3. Compare
for psp_txn in psp_transactions:
    our_txn = find_matching_txn(psp_txn.transaction_id)

    if not our_txn:
        alert("Missing transaction in our ledger")
    elif our_txn.amount != psp_txn.amount:
        alert("Amount mismatch")

# 4. Verify totals
assert sum(psp_transactions.amounts) == sum(our_transactions.amounts)
```

Mismatches are categorized:
- **Auto-fixable**: Known issues with scripted resolution
- **Manual**: Finance team investigates
- **Critical**: Escalate to engineering (indicates bug)

---

**Q: "How would you scale to 10,000 TPS?"**

A: Architectural changes needed:

**1. Database Sharding**
- Shard key: `seller_account` (most queries filter by seller)
- Use consistent hashing for distribution
- Trade-off: Cross-shard queries become expensive

**2. Async Everything**
- Kafka for wallet/ledger updates (remove from critical path)
- Payment service just writes event, workers process
- Reduces p99 latency from 500ms to 50ms

**3. Caching**
- Redis for wallet balances (write-through cache)
- Cache invalidation on payment completion
- Reduces database read load by 80%

**4. Multi-Region**
- Route users to nearest region
- Regional reconciliation with central aggregation
- Trade-off: More complex consistency model

**5. Event Sourcing**
- Store all payment state changes as events
- Rebuild wallet balances from event stream
- Enables time-travel debugging and audit

**Capacity Math**:
- 10,000 TPS = 864M transactions/day
- At $50 average, that's $43B/day processed
- Need 20 database shards (500 TPS each)
- Redis cluster with 50GB memory (100M accounts × 500 bytes)

## Extensions to Explore

- [ ] **Implement Real Stripe Integration** - Replace PSP mock with actual Stripe SDK
- [ ] **Add [[rate-limiting]]** - Prevent payment spam (10 payments/min per user)
- [ ] **Build Refund Flow** - Create offsetting ledger entries for refunds
- [ ] **Implement Reconciliation** - Parse CSV settlement files and detect mismatches
- [ ] **Add Fraud Detection** - Machine learning model for transaction risk scoring
- [ ] **Support Multi-Currency** - Currency conversion with FX rates
- [ ] **Build Pay-out Flow** - Integrate with Tipalti for seller payouts
- [ ] **Add Webhook Signature Verification** - HMAC-SHA256 to prevent spoofed webhooks
- [ ] **Implement Circuit Breaker** - Graceful degradation when PSP is down
- [ ] **Event Sourcing** - Store all state changes as events instead of mutable database rows

## Related Implementations

- **[[rate-limiter]]** — Token bucket algorithm for preventing payment spam
- **[[distributed-id-generator]]** — Generating globally unique `payment_order_id`
- **[[message-queue]]** — Kafka patterns for async wallet/ledger updates
- **[[key-value-store]]** — Caching wallet balances in Redis

## Real-World Examples

### Stripe
- Processes $640B annually (2023)
- Uses Ruby/Scala/Go microservices
- Idempotency keys cached for 24 hours
- Settlement files reconciled nightly
- 99.99% uptime SLA

### PayPal
- Handles 21.3M transactions/day
- Uses Java-based microservices
- Double-entry ledger with eventual consistency
- Multi-datacenter active-active deployment
- Complex fraud detection with ML models

### Square
- "Books" ledger service processes billions in transactions
- Immutable append-only log
- Reconciliation detects $0.01 discrepancies
- Blog post: https://developer.squareup.com/blog/books-an-immutable-double-entry-accounting-database-service/

## Interview Red Flags to Avoid

❌ **Storing money as floats** - Use integers (cents)
❌ **No idempotency** - User clicks "Pay" twice, charged twice
❌ **Synchronous wallet updates** - Blocks payment response
❌ **No reconciliation** - Can't detect data corruption
❌ **Single PSP** - No failover when PSP is down
❌ **Mutable ledger** - Can't audit historical transactions
❌ **Strong consistency assumption** - 2PC doesn't work with PSPs
❌ **No retry limits** - Infinite retry loop crashes system

## Key Metrics to Monitor

| Metric | Threshold | Action |
|--------|-----------|--------|
| Payment success rate | < 95% | Investigate PSP issues |
| Payment latency (p99) | > 2s | Check database performance |
| Ledger imbalance | != 0 | CRITICAL: Data integrity bug |
| Retry queue depth | > 10,000 | Scale workers or investigate systemic failure |
| Reconciliation mismatches | > 10/day | Review with finance team |
| PSP error rate | > 1% | Check PSP status page |
| Duplicate payment attempts | > 5% | Improve client-side UX |

## Resources Used

- [System Design Interview Vol 2 - Chapter 11](https://www.amazon.com/System-Design-Interview-Insiders-Guide/dp/1736049119)
- [Stripe API Documentation](https://stripe.com/docs/api)
- [Square Books: Immutable Accounting](https://developer.squareup.com/blog/books-an-immutable-double-entry-accounting-database-service/)
- [Uber's Payment Platform](https://eng.uber.com/payments-platform/)
- [Double-Entry Bookkeeping (Wikipedia)](https://en.wikipedia.org/wiki/Double-entry_bookkeeping)
- [PCI DSS Compliance Standards](https://www.pcisecuritystandards.org/)

## Final Reflection

Building this payment system reinforced that **financial systems prioritize correctness over performance**. The 10 TPS requirement isn't about optimization—it's about getting idempotency, consistency, and auditability right.

The most valuable lesson: Modern distributed systems still use 500-year-old accounting principles (double-entry) because they work. Don't reinvent fundamental patterns; understand why they exist and apply them correctly.

This implementation is interview-ready. I can now explain payment system trade-offs, justify design decisions, and scale the architecture from 10 TPS to 10,000 TPS with confidence.
