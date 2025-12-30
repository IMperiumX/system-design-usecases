"""
Sliding Window Counter Rate Limiting Algorithm

System Design Concept:
    This implements the sliding window counter algorithm described on
    pages 285-308 of the chapter. It's a hybrid approach combining
    fixed window counter and sliding window log.

    Cloudflare uses this algorithm and found only 0.003% error rate
    among 400 million requests (mentioned on page 320-321).

How It Works (from chapter Figure 4-11):
    Uses weighted count from current and previous windows.

    Formula:
        requests_in_rolling_window =
            current_window_count +
            previous_window_count × overlap_percentage

    Example from chapter:
        - Limit: 7 requests/minute
        - Previous minute (1:00-1:01): 5 requests
        - Current minute (1:01-1:02): 3 requests
        - New request at 1:01:30 (50% into current minute)
        - Calculation: 3 + 5 × 0.5 = 5.5 ≈ 6 requests
        - 6 < 7, so ALLOW

Simulates:
    Cloudflare's rate limiter

Pros (from chapter):
    - Smooths out traffic spikes
    - Memory efficient (only 2 counters)
    - Good approximation of sliding window

Cons (from chapter):
    - Not perfectly accurate (assumes even distribution in windows)
    - Cloudflare data: 0.003% error rate (very low in practice)

Key Methods:
    - check_rate_limit: Calculate weighted count from two windows
"""

import logging
import time
from src.models import RateLimitRule, RateLimitResult, ClientIdentifier
from src.services.rate_limiter_base import RateLimiterBase

logger = logging.getLogger(__name__)


class SlidingWindowCounterRateLimiter(RateLimiterBase):
    """
    Sliding window counter algorithm implementation.

    This is a hybrid approach that provides good accuracy with
    low memory overhead. Only tracks two window counters instead
    of individual timestamps.

    Algorithm: Weight previous window based on overlap percentage
    """

    async def check_rate_limit(
        self, client: ClientIdentifier, rule: RateLimitRule
    ) -> RateLimitResult:
        """
        Check rate limit using weighted sliding window approach.

        Implementation:
            1. Calculate current and previous window keys
            2. Get counts from both windows
            3. Calculate overlap percentage
            4. Apply formula: current + previous × overlap
            5. Check if weighted sum exceeds limit
        """
        window_seconds = rule.get_window_seconds()
        now = time.time()

        # Calculate current and previous window boundaries
        current_window_start = int(now // window_seconds) * window_seconds
        previous_window_start = current_window_start - window_seconds

        # Calculate how far we are into the current window (0.0 to 1.0)
        elapsed_in_current = now - current_window_start
        progress = elapsed_in_current / window_seconds

        # Overlap with previous window (1.0 to 0.0 as time progresses)
        previous_weight = 1.0 - progress

        base_key = client.get_key(rule)
        current_key = f"{base_key}:window:{current_window_start}"
        previous_key = f"{base_key}:window:{previous_window_start}"

        logger.info(
            f"[SLIDING_COUNTER] Checking {base_key} "
            f"(progress={progress:.2%}, prev_weight={previous_weight:.2%})"
        )

        # Get counts from both windows
        current_count_str = await self.redis.get(current_key)
        current_count = int(current_count_str) if current_count_str else 0

        previous_count_str = await self.redis.get(previous_key)
        previous_count = int(previous_count_str) if previous_count_str else 0

        # Calculate weighted request count (formula from chapter)
        weighted_count = current_count + (previous_count * previous_weight)

        logger.debug(
            f"[SLIDING_COUNTER] Windows: "
            f"previous={previous_count}, current={current_count}, "
            f"weighted={weighted_count:.2f}"
        )

        # Check against limit
        # Following chapter example, we round down the weighted count
        estimated_count = int(weighted_count)

        if estimated_count < rule.requests_per_unit:
            # Under limit, increment current window counter
            new_count = await self.redis.incr(current_key)

            # Set expiration on current window
            await self.redis.expire(current_key, window_seconds * 2)

            # Recalculate weighted count after increment
            weighted_count = new_count + (previous_count * previous_weight)
            estimated_count = int(weighted_count)
            remaining = max(0, rule.requests_per_unit - estimated_count)

            logger.info(
                f"[SLIDING_COUNTER] ✓ ALLOWED {base_key} "
                f"(estimated: {estimated_count}/{rule.requests_per_unit})"
            )

            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=rule.requests_per_unit,
                retry_after=None,
                algorithm="sliding_window_counter"
            )
        else:
            # Over limit, reject request
            ttl = await self.redis.ttl(current_key)
            if ttl < 0:
                ttl = window_seconds

            logger.info(
                f"[SLIDING_COUNTER] ✗ REJECTED {base_key} "
                f"(estimated: {estimated_count}/{rule.requests_per_unit}, "
                f"window resets in {ttl}s)"
            )

            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=rule.requests_per_unit,
                retry_after=self._get_retry_after(ttl),
                algorithm="sliding_window_counter"
            )
