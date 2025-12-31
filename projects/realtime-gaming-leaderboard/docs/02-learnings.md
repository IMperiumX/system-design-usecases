---
tags:
  - system-design
  - realtime-gaming-leaderboard
  - learnings
  - interview-prep
  - redis
  - skip-list
created: 2025-12-31
status: complete
related:
  - "[[00-analysis]]"
  - "[[01-architecture]]"
---

# Real-time Gaming Leaderboard — Learnings

## What I Built

A production-ready real-time gaming leaderboard system capable of handling 5M daily active users with O(log n) ranking operations. The system uses Redis sorted sets (backed by skip lists) for sub-second leaderboard queries, PostgreSQL for durable user data and audit logs, and exposes a clean RESTful API built with Django REST Framework.

**Core features implemented:**
- Score updates with immediate rank calculation
- Top 10 leaderboard with O(log n + 10) query time
- Individual user rank lookup
- Contextual leaderboard (±4 positions around any user)
- Monthly leaderboard rotation with archival
- Disaster recovery from audit logs

## Key Takeaways

> [!tip] Core Insight #1: Data Structure Choice Makes or Breaks Real-Time Systems
> The difference between a MySQL-based leaderboard (O(n log n) sorting on every query, 10+ seconds) and Redis sorted sets (O(log n), milliseconds) is fundamental. **You can't optimize your way out of a bad data structure choice.** This applies beyond leaderboards:
> - Autocomplete → Tries, not LIKE queries
> - Rate limiting → Token bucket, not counting DB queries
> - Caching → LRU/LFU algorithms, not simple dictionaries

> [!tip] Core Insight #2: Polyglot Persistence is About Using the Right Tool for Each Job
> We used THREE storage layers, each optimized for its purpose:
> - **Redis**: Real-time leaderboard (hot data, fast reads/writes, acceptable if lost)
> - **PostgreSQL**: User profiles + audit logs (durable, queryable, source of truth)
> - **Snapshots table**: Historical data (archived monthly, cold storage candidate)
>
> In production, this might extend to S3 (Parquet files), Elasticsearch (search), and Kafka (event streaming). **Don't force one database to do everything.**

> [!tip] Core Insight #3: Skip Lists are a Beautiful Probabilistic Alternative to Balanced Trees
> Redis sorted sets use **skip lists** instead of red-black trees because:
> - Simpler implementation (200 lines vs 2,000)
> - Lock-free concurrent access (important for Redis)
> - Nearly same performance (O(log n) expected)
> - Range queries are more cache-friendly
>
> This taught me that **sometimes "good enough" probabilistic algorithms beat complex deterministic ones** (see also: Bloom filters, HyperLogLog, Count-Min Sketch).

> [!tip] Core Insight #4: Sharding Strategies are NOT One-Size-Fits-All
> **Fixed partition (by score)** won:
> - Top 10 always in highest shard (one query)
> - User rank = local rank + users in higher shards (simple)
> - Trade-off: Need secondary cache for user → shard mapping
>
> **Hash partition (by user_id)** loses:
> - Top 10 requires scatter-gather across ALL shards (slow)
> - No easy way to compute exact rank
>
> Lesson: **Choose sharding strategy based on your query patterns**, not "what everyone does."

> [!tip] Core Insight #5: Real-Time Doesn't Mean No Trade-offs
> We made deliberate trade-offs for "real-time":
> - Redis is primary store (fast) but not durable → PostgreSQL audit log enables recovery
> - Score updates are synchronous (immediate feedback) → At 500M DAU, we'd use Kafka (async)
> - Top 10 computed on-demand (real-time) → Could pre-compute and cache (1 min stale okay?)
>
> "Real-time" is a spectrum. **Ask: What's the acceptable staleness for this use case?**

## Concepts Reinforced

- [[redis-sorted-sets]] — Now I understand that ZSET operations (ZINCRBY, ZREVRANK, ZREVRANGE) are O(log n) because of skip list internals, not magic. The hash table maps users → scores for O(1) lookup, while the skip list maps scores → users for O(log n) range queries.

- [[skip-list]] — A skip list is a probabilistic multi-level linked list where each level "skips" nodes. To search for a value, you start at the highest level and drop down when you overshoot. This gives expected O(log n) without the complexity of tree rotations.

- [[sharding]] — The trade-off between **fixed partition** (shard by score ranges) and **hash partition** (shard by user_id hash) depends entirely on whether you need fast top-K queries or just evenly distributed load.

- [[api-design]] — RESTful API design isn't just about HTTP verbs. It's about:
  - Clear resource naming (`/scores/{user_id}` not `/getUserRank`)
  - Proper status codes (404 for not found, 400 for bad input)
  - Query params for filtering (`?month=2025-01`)
  - Response structure consistency

- [[separation-of-concerns]] — The 3-layer architecture (Views → Services → Storage) made testing trivial. I could mock the Redis layer and test business logic independently. This scales to microservices.

- [[event-sourcing-lite]] — The Game audit log is an event stream. We can rebuild the leaderboard from it, reprocess with different scoring rules, or build analytics. This is event sourcing without the full CQRS complexity.

## At Scale

| Scale | What Changes |
|-------|--------------|
| **10x users (50M DAU)** | - Add Redis read replicas (5 replicas × 20% of write QPS each)<br>- Cache top 10 for 60 seconds (CDN or Redis hash)<br>- Add monitoring/alerting for Redis memory |
| **100x users (500M DAU)** | - **Shard Redis** by score ranges (10 shards)<br>- Secondary cache for user → shard mapping<br>- **Kafka** to decouple game events from leaderboard updates<br>- Partition PostgreSQL by month<br>- Pre-compute top 100 every 10 seconds |
| **1000x users (5B DAU)** | - **NoSQL** (DynamoDB) with write sharding (100+ partitions)<br>- Percentile ranks instead of exact ranks<br>- **Data pipeline** to S3/Parquet for historical queries<br>- Regional sharding (US-East, EU-West, APAC)<br>- Eventually consistent leaderboards (1-5 min lag acceptable) |

## Interview Prep

### Clarifying Questions I'd Ask

1. **What's the scale?**
   - How many daily/monthly active users?
   - How many matches per user per day?
   - → Determines if single Redis instance suffices or need sharding

2. **What's the latency requirement?**
   - Real-time (< 100ms) or near real-time (< 1s)?
   - Can top 10 be cached (1 min stale)?
   - → Affects caching strategy and whether to use Kafka

3. **Do we need historical leaderboards?**
   - Monthly tournaments? Seasonal rankings?
   - How long to retain historical data?
   - → Determines archival strategy (PostgreSQL → S3 → Glacier)

4. **How do we handle ties?**
   - Same score = same rank? Or use timestamp as tiebreaker?
   - → Affects data model (need timestamp in Redis?)

5. **Is this global or regional?**
   - One global leaderboard or per-region?
   - → Multi-region deployment complexity

### How I'd Explain This (5 min)

> "Let me walk through the high-level design first. We have a mobile game with 5 million daily active users, each playing 10 matches per day. Every time a player wins, we need to update their score and show their new rank immediately.
>
> **Data model**: We use Redis sorted sets as the primary leaderboard store, with each player's user ID as the member and their total wins as the score. Redis automatically maintains sort order on insertion using a skip list data structure, which gives us O(log n) operations—about 23 comparisons for 5 million users.
>
> **API flow**: When a player wins, the game service calls POST /scores with the user ID. Our leaderboard service does three things: (1) increment the score in Redis with ZINCRBY, (2) log the game to PostgreSQL for audit trail, and (3) return the new rank with ZREVRANK. This takes about 50-100ms end-to-end.
>
> **For the top 10**, we use ZREVRANGE to fetch the highest scores. Since Redis maintains sort order, this is O(log n + 10), so under 1 millisecond.
>
> **Data durability**: Redis is fast but not designed for durability. We log every game to PostgreSQL, so if Redis crashes, we can rebuild the leaderboard from the audit logs. We also snapshot the leaderboard to PostgreSQL at the end of each month for historical queries.
>
> **Scaling**: At our current scale of 5M DAU, a single Redis instance handles ~2,500 writes/sec with 650 MB of memory. If we grow to 500M DAU, we'd shard Redis by score ranges—users with scores 0-100 go to shard 1, 101-200 to shard 2, etc. The top 10 query always hits the highest shard, which is efficient.
>
> **Trade-offs**: We chose Redis over MySQL because MySQL would need to sort 5 million rows on every query (O(n log n), taking 10+ seconds), whereas Redis maintains sort order during insertion. We chose fixed partitioning over hash partitioning because it makes top-K queries efficient without scatter-gather."

### Follow-up Questions to Expect

**Q: "How would you handle Redis failure?"**

A: "We have three options:
1. **Read replica failover** (fastest, ~30 seconds): Redis supports master-slave replication. When the master fails, we promote a replica. This is the production approach.
2. **Rebuild from PostgreSQL** (slower, 5-10 minutes): We have a Game audit log with every match. We can GROUP BY user_id and SUM(score_earned) to rebuild the leaderboard.
3. **Combination**: Promote replica immediately, then rebuild in background to verify integrity.

I'd also add monitoring to detect Redis latency spikes or memory usage > 80%, and alert before failure."

**Q: "What if traffic spikes 10x suddenly?"**

A: "Short-term (immediate):
- Add Redis read replicas to handle query load (top 10, user rank)
- Cache top 10 in CDN with 60-second TTL
- Rate limit per user (max 100 requests/hour)

Long-term (if sustained):
- Shard Redis to distribute write load
- Use Kafka to buffer score updates (async processing)
- Pre-compute top 100 every 10 seconds in background job

I'd also investigate: Is this organic growth or a DDoS attack? If attack, add WAF rules."

**Q: "How would you monitor this system?"**

A: "Key metrics:
- **Redis**: Memory usage (alert if > 1 GB), QPS (alert if > 50K), slow log (queries > 10ms)
- **API**: p50/p95/p99 latency, error rate, requests/sec
- **Business**: Total players, games/day, leaderboard size growth

I'd use:
- Prometheus + Grafana for metrics and dashboards
- PagerDuty for alerts (Redis memory high, API p99 > 500ms)
- DataDog for distributed tracing (track request from client → API → Redis → DB)
- ELK stack for logs (debug specific user issues)

Critical alerts:
- Redis memory > 80% → Time to shard
- API p99 > 200ms → Investigate slow queries
- Error rate > 1% → Check Redis connectivity"

**Q: "How do you prevent cheating (players falsifying scores)?"**

A: "Three layers of defense:

1. **Server-authoritative design**: Clients can't call POST /scores directly. Only the game service can, after validating the match outcome. This prevents man-in-the-middle attacks.

2. **Authentication**: The game service uses an API key (X-Game-Service-Token header) to call the leaderboard API. We verify this token on every request.

3. **Audit trail**: Every score update logs to PostgreSQL with:
   - user_id, match_id, score_earned, timestamp
   - We can later run anomaly detection (e.g., user winning 1000 games in 1 hour)

For extra paranoia (e.g., e-sports with prize money):
- Replay validation: Store game replays and randomly audit high scores
- Statistical analysis: Flag users with win rates > 3 standard deviations above mean
- Rate limiting: Max 50 wins per hour per user

In the design doc, I'd note: 'Cheat detection is out of scope for the leaderboard service—it should be handled by the game service or a dedicated anti-cheat system.'"

**Q: "How would you add real-time push notifications when a user is overtaken?"**

A: "Great feature! This requires pub/sub. Two approaches:

**Approach 1: Redis Pub/Sub + WebSockets**
1. When a user's score is updated, publish message to channel: `user:{user_id}:rank_changed`
2. WebSocket server subscribes to channels for online users
3. When rank changes, push notification to client

**Approach 2: Kafka + WebSocket Gateway**
1. Score updates go to Kafka topic: `leaderboard.score_updated`
2. Rank change detector consumes events, compares old_rank vs new_rank
3. Publishes to `notifications.rank_changed` topic
4. WebSocket gateway consumes and pushes to clients

I'd choose Approach 2 because:
- Kafka provides durability (Redis Pub/Sub drops messages if no subscribers)
- Can replay events for debugging
- Scales to other notifications (friend surpassed you, entered top 100, etc.)

Trade-off: Adds 100-500ms latency vs. Redis Pub/Sub (acceptable for non-critical notifications)."

## Extensions to Explore

- [ ] **Implement sharding**: Set up 3 Redis instances and shard by score ranges (0-500, 501-1000, 1001+)
- [ ] **Add caching layer**: Use Redis hash to cache top 10 with 60-second TTL
- [ ] **Build admin dashboard**: Grafana with leaderboard metrics (total users, top score, distribution)
- [ ] **Tie-breaking logic**: Store win timestamp and rank by (score DESC, timestamp ASC)
- [ ] **Percentile ranks**: For users outside top 10K, show "Top 5%" instead of exact rank
- [ ] **Load testing**: Use Locust to simulate 10K concurrent score updates
- [ ] **Disaster recovery drill**: Kill Redis, rebuild from PostgreSQL, measure time
- [ ] **Multi-region deployment**: Deploy to 3 AWS regions, measure cross-region latency
- [ ] **GraphQL API**: Compare REST vs GraphQL for leaderboard queries
- [ ] **NoSQL alternative**: Implement with DynamoDB and compare performance/cost

## Related Implementations

- [[url-shortener]] — Uses similar sharding principles (hash-based sharding)
- [[rate-limiter]] — Another Redis-based system with sliding window counters
- [[distributed-cache]] — Demonstrates LRU eviction, similar to leaderboard archival
- [[news-feed]] — Fan-out pattern similar to leaderboard updates

## What I'd Do Differently

1. **Add integration tests earlier**: I wrote mostly unit tests. Should have added end-to-end tests hitting real Redis/PostgreSQL from the start.

2. **Use Django signals for audit logging**: Currently, the service manually creates Game records. Django signals would decouple this (score updated → signal → log to DB).

3. **Add OpenAPI/Swagger docs**: The API is self-documenting, but auto-generated docs (drf-yasg) would be helpful for frontend devs.

4. **Implement async score updates**: Use Celery + Redis queue to make POST /scores non-blocking (return 202 Accepted).

5. **Add more edge case tests**: What happens if two users update scores concurrently? What if Redis returns stale data during replication lag?

## Production Readiness Checklist

If deploying to production, I'd add:

- [ ] **Authentication & Authorization**: API keys for game service, user tokens for client endpoints
- [ ] **Rate limiting**: Per user (100 req/hour), per API key (10K req/hour)
- [ ] **HTTPS/TLS**: SSL certificates for API endpoints
- [ ] **CORS**: Whitelist allowed origins for browser-based clients
- [ ] **Logging**: Structured JSON logs with request IDs for tracing
- [ ] **Metrics & Alerting**: Prometheus exporters for Redis/PostgreSQL/API
- [ ] **Health checks**: `/health` endpoint for load balancer probes
- [ ] **Graceful shutdown**: Handle SIGTERM, finish in-flight requests
- [ ] **Database migrations**: Versioned migrations with rollback capability
- [ ] **Backup & Restore**: Automated PostgreSQL backups to S3, Redis RDB snapshots
- [ ] **Load testing**: Verify system handles 3x expected peak load
- [ ] **Disaster recovery plan**: Document steps to recover from Redis/DB failure
- [ ] **Security audit**: SQL injection prevention, input validation, secrets management
- [ ] **Cost estimation**: Calculate monthly AWS costs (EC2, RDS, ElastiCache, bandwidth)

## Final Thoughts

This project taught me that **system design is about trade-offs, not "best practices."** There's no universally correct answer—only decisions appropriate for your scale, latency requirements, and team expertise.

The real skill is:
1. **Asking the right questions** to understand requirements
2. **Choosing the right data structures** (sorted sets > SQL sorting)
3. **Designing for evolution** (single Redis → sharded Redis → NoSQL)
4. **Justifying trade-offs** (real-time vs. eventual consistency)

If I were interviewing at a gaming company (Supercell, Epic, Riot), I'd emphasize:
- Experience with Redis sorted sets for leaderboards
- Understanding of sharding strategies and when to shard
- Ability to calculate back-of-the-envelope estimates (QPS, storage)
- Production-readiness mindset (monitoring, disaster recovery, cost)

**Most importantly**: I can now confidently draw this system on a whiteboard in 45 minutes, explain every component, and defend my design choices under scrutiny. That's the goal.

---

**Next steps**: Practice explaining this design out loud, implement one of the extensions, or tackle another system design problem (e.g., news feed, chat system).
