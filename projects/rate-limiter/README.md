# Rate Limiter - System Design Implementation

> Learning implementation of a distributed rate limiter based on Chapter 4 of "System Design Interview" by Alex Xu

## What This Teaches

This project implements **all 5 rate limiting algorithms** from the chapter with production-ready patterns:

- **Primary Concepts**: Rate limiting algorithms, distributed state management, race condition handling
- **Secondary Concepts**: Redis Lua scripts, FastAPI middleware, time-windowing strategies
- **Real-world Examples**: Amazon/Stripe (token bucket), Shopify (leaky bucket), Cloudflare (sliding window counter)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          CLIENT                                  │
│                            │                                     │
│                            ▼                                     │
│                   ┌────────────────┐                            │
│                   │  Rate Limiter  │ ◄── Middleware intercepts  │
│                   │   Middleware   │     all requests           │
│                   └────────┬───────┘                            │
│                            │                                     │
│            ┌───────────────┼───────────────┐                    │
│            ▼               ▼               ▼                    │
│    ┌──────────────┐ ┌─────────────┐ ┌──────────────┐          │
│    │ Token Bucket │ │Leaky Bucket │ │Fixed Window  │ ...      │
│    │  Algorithm   │ │  Algorithm  │ │  Algorithm   │          │
│    └──────┬───────┘ └──────┬──────┘ └──────┬───────┘          │
│           │                 │                │                  │
│           └─────────────────┼────────────────┘                  │
│                             ▼                                   │
│                      ┌────────────┐                             │
│                      │   Redis    │ ◄── Stores counters,        │
│                      │   Cache    │     timestamps, tokens      │
│                      └────────────┘     Uses Lua scripts        │
│                                          for atomicity          │
│                             │                                   │
│                             ▼                                   │
│                    Allowed? Yes/No                              │
│                             │                                   │
│              ┌──────────────┴──────────────┐                   │
│              ▼                             ▼                   │
│      ┌────────────┐                ┌─────────────┐            │
│      │ Forward to │                │Return HTTP  │            │
│      │API Servers │                │429 + Headers│            │
│      └────────────┘                └─────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Install dependencies

```bash
make install
```

### 2. Start Redis

```bash
make redis-up
```

### 3. Run the interactive demo

```bash
make demo
```

This will showcase all 5 algorithms with visual comparisons!

### 4. Start the API server

```bash
make run
```

Visit http://localhost:8000 to see the API documentation.

### 5. Test different algorithms

```bash
# Test token bucket (allows bursts)
curl http://localhost:8000/simulate/token_bucket

# Test fixed window (has edge case)
curl http://localhost:8000/simulate/fixed_window

# Test sliding window log (most accurate)
curl http://localhost:8000/simulate/sliding_window_log
```

## Components

| Component | Real-World Equivalent | What It Demonstrates |
|-----------|----------------------|---------------------|
| **Token Bucket** | Amazon API Gateway, Stripe | Burst tolerance, refill rate |
| **Leaky Bucket** | Shopify REST API | Fixed processing rate, queue management |
| **Fixed Window** | Simple rate limiters | Edge case problem (2x limit at boundaries) |
| **Sliding Window Log** | Strict rate limiters | Accuracy vs memory trade-off |
| **Sliding Window Counter** | Cloudflare | Hybrid approach (0.003% error, low memory) |
| **Redis + Lua** | Distributed counters | Atomic operations, race condition prevention |
| **FastAPI Middleware** | API Gateway | Request interception, HTTP 429 responses |

## Algorithm Deep Dive

### 1. Token Bucket
**File**: `src/services/token_bucket.py`

**How it works** (Chapter pages 127-137):
- Bucket holds tokens (max capacity)
- Tokens refill at constant rate
- Each request consumes 1 token
- Allows bursts if tokens available

**Pros**:
- ✅ Allows burst traffic
- ✅ Memory efficient (2 values)
- ✅ Industry standard (Amazon, Stripe)

**Cons**:
- ❌ Parameters need tuning

**Code highlights**:
```python
# Lua script atomically:
# 1. Calculates tokens to add based on time elapsed
# 2. Checks if token available
# 3. Consumes token if available
refill_rate = requests_per_unit / window_seconds
allowed, remaining = await redis.token_bucket_check(key, capacity, refill_rate)
```

### 2. Leaky Bucket
**File**: `src/services/leaky_bucket.py`

**How it works** (Chapter pages 177-196):
- Requests added to FIFO queue
- Processed at fixed rate (the "leak")
- Queue has max size

**Pros**:
- ✅ Stable outflow rate
- ✅ Memory efficient

**Cons**:
- ❌ Old requests can block new ones
- ❌ Burst traffic fills queue quickly

**Used by**: Shopify

### 3. Fixed Window Counter
**File**: `src/services/fixed_window.py`

**How it works** (Chapter pages 210-231):
- Timeline divided into fixed windows
- Counter per window
- Resets at window boundary

**The Edge Case Problem** (Figure 4-9):
```
Limit: 5 per minute

Window 1 (2:00:00-2:01:00): ✓✓✓✓✓ (5 requests)
Window 2 (2:01:00-2:02:00): ✓✓✓✓✓ (5 requests)

Between 2:00:30 and 2:01:30 (60 seconds): 10 requests! ⚠️
```

**Pros**:
- ✅ Very simple
- ✅ Memory efficient

**Cons**:
- ❌ Boundary burst allows 2x limit

### 4. Sliding Window Log
**File**: `src/services/sliding_window_log.py`

**How it works** (Chapter pages 244-274):
- Store timestamp for every request
- Remove timestamps older than window
- Count remaining timestamps

**Pros**:
- ✅ Most accurate
- ✅ No edge case issues

**Cons**:
- ❌ High memory (stores all timestamps)
- ❌ Rejected requests still stored temporarily

**Implementation**:
```python
# Uses Redis sorted sets (chapter page 250)
await redis.zadd(log_key, {str(now): now})  # Add timestamp
await redis.zremrangebyscore(log_key, 0, window_start)  # Remove old
count = await redis.zcard(log_key)  # Count current
```

### 5. Sliding Window Counter
**File**: `src/services/sliding_window_counter.py`

**How it works** (Chapter pages 285-308):
- Hybrid of fixed window + sliding window log
- Uses weighted count from 2 windows

**Formula** (from chapter):
```
weighted_count = current_window_count +
                 previous_window_count × overlap_percentage

where overlap = 1 - (time_in_current_window / window_size)
```

**Example** (Chapter Figure 4-11):
```
Limit: 7 per minute
Previous window (1:00-1:01): 5 requests
Current window (1:01-1:02): 3 requests
Request arrives at 1:01:30 (50% into current)

Calculation: 3 + (5 × 0.5) = 5.5 ≈ 5
5 < 7 → ALLOW ✓
```

**Pros**:
- ✅ Good accuracy (Cloudflare: 0.003% error)
- ✅ Memory efficient (2 counters)
- ✅ Smooths traffic spikes

**Cons**:
- ❌ Assumes even request distribution

**Used by**: Cloudflare

## Key Design Decisions

### Race Condition Handling

**Problem** (Chapter page 437-442):
```python
# Without atomicity:
counter = redis.get(key)        # Thread 1: reads 3
counter = redis.get(key)        # Thread 2: reads 3
redis.set(key, counter + 1)     # Thread 1: writes 4
redis.set(key, counter + 1)     # Thread 2: writes 4 (should be 5!)
```

**Solution**: Lua scripts execute atomically on Redis server

```python
# Lua script runs atomically
increment_script = """
local current = tonumber(redis.call('get', key) or '0')
if current < limit then
    local new_count = redis.call('incr', key)
    return {1, new_count}
else
    return {0, current}
end
"""
```

### Distributed Synchronization

**Problem** (Chapter page 449-457):
Multiple rate limiter servers need shared state

**Solution**: Centralized Redis (Figure 4-16)
- Sticky sessions don't scale
- Use Redis as single source of truth
- In production: Redis Cluster with eventual consistency

### HTTP Headers

Following standard from chapter (page 397-402):

```
X-Ratelimit-Remaining: 42      # Requests left in window
X-Ratelimit-Limit: 100         # Total allowed per window
X-Ratelimit-Retry-After: 23    # Seconds until reset
```

## At Scale

How this would change for production:

### Current Implementation (Single Server)
- Single Redis instance
- In-memory rule storage
- No metrics/monitoring
- Simple client identification

### Production Changes

1. **High Availability** (Chapter page 463-471)
   - Redis Cluster or Sentinel
   - Multi-datacenter deployment
   - Edge servers (Cloudflare has 194 locations)

2. **Performance Optimization**
   - Connection pooling
   - Batch operations
   - Eventual consistency model

3. **Monitoring** (Chapter page 477-483)
   - Track algorithm effectiveness
   - Alert on high rejection rates
   - Analyze traffic patterns

4. **Rule Management**
   - YAML configuration files (like Lyft)
   - Hot reload without restart
   - A/B testing different algorithms

5. **Advanced Features**
   - Hard vs soft limits
   - Layer 3 (IP) rate limiting via iptables
   - Request queueing for burst handling
   - Priority tiers for premium users

## Interview Prep

This implementation prepares you for:

### Direct Rate Limiter Questions
1. "Design a rate limiter" ✓
2. "How would you handle burst traffic?" → Token bucket
3. "What's the most accurate algorithm?" → Sliding window log
4. "How do you prevent race conditions?" → Lua scripts
5. "How does Cloudflare's rate limiter work?" → Sliding window counter

### Related Concepts
- Distributed counters
- Time-based expiration
- Redis data structures (sorted sets)
- API middleware patterns
- HTTP status codes (429)
- Fault tolerance (fail open vs fail closed)

### Trade-off Discussions
- Accuracy vs Memory (sliding log vs counter)
- Simplicity vs Correctness (fixed window vs sliding)
- Burst tolerance vs Stability (token vs leaky bucket)
- Consistency vs Availability (strict vs eventual)

## Code Navigation

```
rate-limiter/
├── src/
│   ├── models.py              # Data models (rules, results, clients)
│   ├── config.py              # Settings and environment
│   ├── storage/
│   │   └── redis_client.py    # Redis wrapper with Lua scripts
│   ├── services/
│   │   ├── rate_limiter_base.py         # Common interface
│   │   ├── token_bucket.py              # Algorithm 1
│   │   ├── leaky_bucket.py              # Algorithm 2
│   │   ├── fixed_window.py              # Algorithm 3
│   │   ├── sliding_window_log.py        # Algorithm 4
│   │   ├── sliding_window_counter.py    # Algorithm 5
│   │   ├── rate_limiter_factory.py      # Algorithm selection
│   │   └── rate_limiter_service.py      # Orchestration
│   └── api.py                 # FastAPI app + middleware
├── scripts/
│   └── demo.py                # Interactive demonstration
└── tests/
    └── test_demo.py           # Test suite
```

## Extensions

Ideas to go deeper:

- [ ] **Multi-tier limits**: Free users 100/hour, premium 1000/hour
- [ ] **Distributed tracing**: Track request across rate limiter → API
- [ ] **Admin dashboard**: Real-time metrics and rule management
- [ ] **Geographic routing**: Edge servers in multiple regions
- [ ] **Cost tracking**: Monitor Redis ops, optimize Lua scripts
- [ ] **Request queueing**: Handle rate-limited requests later
- [ ] **Circuit breaker**: Fail open if Redis unavailable
- [ ] **Layer 3 rate limiting**: IP-based via iptables
- [ ] **User exemptions**: Whitelist certain API keys
- [ ] **Dynamic limits**: Adjust based on server load

## Testing

```bash
# Run all tests
make test

# Run specific test
pytest tests/test_demo.py::test_token_bucket_allows_burst -v

# Test with coverage
pytest --cov=src tests/
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service information |
| `/health` | GET | Health check (not rate limited) |
| `/api/data` | GET | Sample endpoint (100/min per IP) |
| `/auth/login` | POST | Sample auth (5/min per user) |
| `/rules` | GET | List active rules |
| `/rules/add` | POST | Add new rule dynamically |
| `/simulate/{algorithm}` | GET | Test specific algorithm |

## Performance Characteristics

Based on chapter analysis and implementation:

| Algorithm | Time Complexity | Space Complexity | Memory (1000 req) |
|-----------|----------------|------------------|-------------------|
| Token Bucket | O(1) | O(1) | ~100 bytes |
| Leaky Bucket | O(1) | O(1) | ~100 bytes |
| Fixed Window | O(1) | O(1) | ~50 bytes |
| Sliding Window Log | O(log N) | O(N) | ~32 KB |
| Sliding Window Counter | O(1) | O(1) | ~100 bytes |

**N** = number of requests in window

## References

From "System Design Interview" by Alex Xu, Chapter 4:

- Token Bucket: Pages 127-137, 149-176
- Leaky Bucket: Pages 177-196
- Fixed Window: Pages 210-243
- Sliding Window Log: Pages 244-274
- Sliding Window Counter: Pages 285-308
- Architecture: Figures 4-2, 4-3, 4-12, 4-13
- Race Conditions: Pages 437-447
- Distributed Environment: Pages 449-462
- HTTP Headers: Pages 397-406

Real-world implementations mentioned:
- [Amazon API Gateway Throttling](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-request-throttling.html)
- [Stripe Rate Limiters](https://stripe.com/blog/rate-limiters)
- [Cloudflare's Implementation](https://blog.cloudflare.com/counting-things-a-lot-of-different-things/)
- [Lyft's Rate Limiter](https://github.com/lyft/ratelimit)

## License

MIT - Educational purposes

---

**Note**: This is a learning implementation optimized for understanding concepts, not production use. For production, consider services like AWS API Gateway, Cloudflare, or Kong.
