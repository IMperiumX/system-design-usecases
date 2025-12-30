"""
Leaky Bucket Rate Limiting Algorithm

System Design Concept:
    This implements the leaky bucket algorithm described on pages 177-196
    of the chapter. Used by Shopify for e-commerce rate limiting.

    Unlike token bucket which allows bursts, leaky bucket enforces a
    strictly fixed outflow rate, making it ideal when you need stable
    processing rates.

How It Works (from chapter):
    1. Requests arrive and are added to a FIFO queue (the "bucket")
    2. If queue is full, new requests are dropped
    3. Requests are processed from the queue at a fixed rate
    4. The "leak" represents the constant processing rate

Simulates:
    Shopify's rate limiter

Pros (from chapter):
    - Memory efficient (limited queue size)
    - Suitable for use cases needing stable outflow rate

Cons (from chapter):
    - Burst traffic fills queue with old requests
    - Recent requests may be rate limited even if old requests aren't processed
    - Two parameters can be hard to tune

Key Methods:
    - check_rate_limit: Add request to queue if space available
"""

import logging
import time
from src.models import RateLimitRule, RateLimitResult, ClientIdentifier
from src.services.rate_limiter_base import RateLimiterBase

logger = logging.getLogger(__name__)


class LeakyBucketRateLimiter(RateLimiterBase):
    """
    Leaky bucket algorithm implementation.

    Algorithm parameters (from chapter page 189-194):
        - Bucket size: Queue capacity
        - Outflow rate: Fixed processing rate (requests per time unit)

    Simplification:
        Instead of maintaining an actual FIFO queue, we simulate the
        "leak" by tracking when slots become available based on the
        fixed processing rate. This is more efficient for rate limiting.
    """

    async def check_rate_limit(
        self, client: ClientIdentifier, rule: RateLimitRule
    ) -> RateLimitResult:
        """
        Check if request can be added to the leaky bucket queue.

        Implementation:
            - Track number of requests "in queue" using a counter
            - Simulate leak by calculating how many requests have
              "leaked out" since last check based on outflow rate
            - If queue has space, allow request
        """
        key = client.get_key(rule)
        queue_key = f"{key}:queue"
        last_leak_key = f"{key}:last_leak"

        window_seconds = rule.get_window_seconds()
        outflow_rate = rule.requests_per_unit / window_seconds  # requests per second
        queue_size = rule.queue_size or (rule.requests_per_unit * 2)

        now = time.time()

        # Get current queue count and last leak time
        current_count_str = await self.redis.get(queue_key)
        current_count = int(current_count_str) if current_count_str else 0

        last_leak_str = await self.redis.get(last_leak_key)
        last_leak = float(last_leak_str) if last_leak_str else now

        # Calculate how many requests have "leaked out" since last check
        elapsed = now - last_leak
        leaked = int(elapsed * outflow_rate)

        # Update queue count
        current_count = max(0, current_count - leaked)

        logger.info(
            f"[LEAKY_BUCKET] Checking {key} "
            f"(queue={current_count}/{queue_size}, outflow_rate={outflow_rate:.2f}/s)"
        )

        if current_count < queue_size:
            # Queue has space, accept request
            new_count = current_count + 1
            await self.redis.set(queue_key, new_count, ex=window_seconds)
            await self.redis.set(last_leak_key, now, ex=window_seconds)

            remaining = queue_size - new_count

            logger.info(
                f"[LEAKY_BUCKET] ✓ ALLOWED {key} "
                f"(queue: {new_count}/{queue_size}, remaining: {remaining})"
            )

            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=queue_size,
                retry_after=None,
                algorithm="leaky_bucket"
            )
        else:
            # Queue is full, reject request
            retry_after = int(1 / outflow_rate) + 1

            logger.info(
                f"[LEAKY_BUCKET] ✗ REJECTED {key} "
                f"(queue full: {current_count}/{queue_size}, retry in {retry_after}s)"
            )

            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=queue_size,
                retry_after=retry_after,
                algorithm="leaky_bucket"
            )
