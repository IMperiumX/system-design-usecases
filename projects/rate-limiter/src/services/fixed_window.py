"""
Fixed Window Counter Rate Limiting Algorithm

System Design Concept:
    This implements the fixed window counter algorithm described on
    pages 210-231 of the chapter. It's the simplest algorithm but has
    a critical edge case issue.

How It Works (from chapter):
    1. Timeline is divided into fixed-size time windows
    2. Each window has a counter
    3. Each request increments the counter
    4. When counter exceeds threshold, reject new requests
    5. Counter resets when new window starts

The Edge Case Problem (from chapter Figure 4-9):
    A burst of traffic at window edges can allow 2x the limit.

    Example: Limit is 5 requests per minute
    - 2:00:00 to 2:01:00: 5 requests (allowed)
    - 2:01:00 to 2:02:00: 5 requests (allowed)
    - BUT: Between 2:00:30 and 2:01:30 (one minute), 10 requests got through!

    This violates the "5 per minute" guarantee during edge periods.

Simulates:
    Simple rate limiters without sliding window logic

Pros (from chapter):
    - Memory efficient
    - Easy to understand
    - Resetting quota at round minutes fits some use cases

Cons (from chapter):
    - Spike in traffic at edges allows more than quota
    - Not accurate for strict rate limiting

Key Methods:
    - check_rate_limit: Increment counter if under limit
"""

import logging
import time
from src.models import RateLimitRule, RateLimitResult, ClientIdentifier
from src.services.rate_limiter_base import RateLimiterBase

logger = logging.getLogger(__name__)


class FixedWindowRateLimiter(RateLimiterBase):
    """
    Fixed window counter algorithm implementation.

    Algorithm: Simple counter per time window

    WARNING: Has edge case issue documented in chapter (page 223-230)
    where burst traffic at window boundaries can exceed the limit.
    """

    async def check_rate_limit(
        self, client: ClientIdentifier, rule: RateLimitRule
    ) -> RateLimitResult:
        """
        Increment counter for current fixed window.

        Implementation:
            - Generate key based on current time window
            - Use Redis INCR to atomically increment counter
            - Set expiration to window size
            - Check if count exceeds limit

        Edge Case Demonstration:
            If limit is 5/minute and requests come at:
            - :59 second: 5 requests (all allowed)
            - :01 second: 5 requests (all allowed)
            Between :59 and 1:01 (62 seconds), 10 requests succeeded
            even though limit is 5 per 60 seconds!
        """
        window_seconds = rule.get_window_seconds()

        # Calculate current window start time
        # This creates fixed windows: [0-60), [60-120), etc.
        current_window = int(time.time() // window_seconds) * window_seconds

        key = f"{client.get_key(rule)}:window:{current_window}"

        logger.info(
            f"[FIXED_WINDOW] Checking {key} "
            f"(limit={rule.requests_per_unit}/{rule.unit.value})"
        )

        # Use atomic increment with limit check (Lua script)
        allowed, count, ttl = await self.redis.incr_with_limit(
            key, rule.requests_per_unit, window_seconds
        )

        remaining = max(0, rule.requests_per_unit - count)

        if allowed:
            logger.info(
                f"[FIXED_WINDOW] ✓ ALLOWED {key} "
                f"({count}/{rule.requests_per_unit}, window ends in {ttl}s)"
            )

            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=rule.requests_per_unit,
                retry_after=None,
                algorithm="fixed_window"
            )
        else:
            logger.info(
                f"[FIXED_WINDOW] ✗ REJECTED {key} "
                f"({count}/{rule.requests_per_unit}, window resets in {ttl}s)"
            )

            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=rule.requests_per_unit,
                retry_after=self._get_retry_after(ttl),
                algorithm="fixed_window"
            )
