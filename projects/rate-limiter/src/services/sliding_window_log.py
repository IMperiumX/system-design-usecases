"""
Sliding Window Log Rate Limiting Algorithm

System Design Concept:
    This implements the sliding window log algorithm described on pages
    244-274 of the chapter. It fixes the edge case problem of fixed
    window counters by tracking individual request timestamps.

How It Works (from chapter Figure 4-10):
    1. Keep timestamps of all requests in a log (Redis sorted set)
    2. When new request arrives:
       a. Remove outdated timestamps (older than window start)
       b. Add new request timestamp to log
       c. Count timestamps in log
       d. If count ≤ limit, allow; otherwise reject

Example from chapter (limit = 2/minute):
    - 1:00:01 → Log: [1:00:01] → Count: 1 → ALLOW
    - 1:00:30 → Log: [1:00:01, 1:00:30] → Count: 2 → ALLOW
    - 1:00:50 → Log: [1:00:01, 1:00:30, 1:00:50] → Count: 3 → REJECT
    - 1:01:40 → Remove [1:00:01, 1:00:30] → Log: [1:00:50] → Count: 1 → ALLOW

Simulates:
    High-accuracy rate limiters where strict limits are required

Pros (from chapter):
    - Very accurate: rate limit is enforced in ANY rolling window
    - No edge case issues unlike fixed window

Cons (from chapter):
    - Consumes a lot of memory (stores timestamp for every request)
    - Even rejected requests' timestamps might be stored temporarily

Key Methods:
    - check_rate_limit: Maintain sorted set of timestamps
"""

import logging
import time
from src.models import RateLimitRule, RateLimitResult, ClientIdentifier
from src.services.rate_limiter_base import RateLimiterBase

logger = logging.getLogger(__name__)


class SlidingWindowLogRateLimiter(RateLimiterBase):
    """
    Sliding window log algorithm implementation.

    Uses Redis sorted sets (mentioned on page 250) to store timestamps.
    The score in the sorted set is the Unix timestamp.

    Trade-off:
        Most accurate algorithm but highest memory usage because
        we store a timestamp for every request in the window.
    """

    async def check_rate_limit(
        self, client: ClientIdentifier, rule: RateLimitRule
    ) -> RateLimitResult:
        """
        Check rate limit using sliding window of request timestamps.

        Implementation:
            1. Current time defines the sliding window end
            2. Window start = current time - window size
            3. Remove timestamps older than window start
            4. Count remaining timestamps
            5. If under limit, add new timestamp and allow
        """
        key = client.get_key(rule)
        log_key = f"{key}:log"

        window_seconds = rule.get_window_seconds()
        now = time.time()
        window_start = now - window_seconds

        logger.info(
            f"[SLIDING_LOG] Checking {key} "
            f"(limit={rule.requests_per_unit}/{rule.unit.value})"
        )

        # Remove outdated timestamps (older than window start)
        await self.redis.zremrangebyscore(log_key, 0, window_start)

        # Count current requests in the sliding window
        current_count = await self.redis.zcard(log_key)

        logger.debug(
            f"[SLIDING_LOG] Current window has {current_count} requests "
            f"(window: {window_start:.2f} to {now:.2f})"
        )

        if current_count < rule.requests_per_unit:
            # Under limit, add new timestamp to log
            await self.redis.zadd(log_key, {str(now): now})

            # Set expiration on the log (cleanup old logs)
            await self.redis.expire(log_key, window_seconds)

            remaining = rule.requests_per_unit - current_count - 1

            logger.info(
                f"[SLIDING_LOG] ✓ ALLOWED {key} "
                f"({current_count + 1}/{rule.requests_per_unit} in rolling window)"
            )

            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=rule.requests_per_unit,
                retry_after=None,
                algorithm="sliding_window_log"
            )
        else:
            # Over limit, reject request
            # Note: We DON'T add the timestamp of rejected requests
            # (though chapter mentions some implementations do)

            logger.info(
                f"[SLIDING_LOG] ✗ REJECTED {key} "
                f"({current_count}/{rule.requests_per_unit} in rolling window)"
            )

            # Calculate retry_after: time until oldest request falls out of window
            # For simplicity, we estimate based on average spacing
            retry_after = int(window_seconds / rule.requests_per_unit) + 1

            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=rule.requests_per_unit,
                retry_after=retry_after,
                algorithm="sliding_window_log"
            )
