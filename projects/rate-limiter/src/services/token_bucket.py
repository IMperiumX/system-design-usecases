"""
Token Bucket Rate Limiting Algorithm

System Design Concept:
    This implements the token bucket algorithm described on pages 127-137
    of the chapter. It's widely used by companies like Amazon and Stripe
    because it allows burst traffic while maintaining average rate limits.

How It Works (from chapter):
    1. Bucket has a fixed capacity of tokens
    2. Tokens are added at a constant rate (refill rate)
    3. When bucket is full, new tokens overflow and are lost
    4. Each request consumes one token
    5. Request proceeds if tokens are available
    6. Request is rejected if no tokens available

Simulates:
    Amazon API Gateway or Stripe's rate limiter

Pros (from chapter):
    - Easy to implement
    - Memory efficient
    - Allows bursts of traffic for short periods

Cons (from chapter):
    - Two parameters (bucket size, refill rate) can be challenging to tune

Key Methods:
    - check_rate_limit: Atomically check and consume token if available
"""

import logging
import time
from src.models import RateLimitRule, RateLimitResult, ClientIdentifier
from src.services.rate_limiter_base import RateLimiterBase

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter(RateLimiterBase):
    """
    Token bucket algorithm implementation.

    Algorithm parameters (from chapter page 149-152):
        - Bucket size: Maximum number of tokens allowed
        - Refill rate: Number of tokens added per second

    Example from chapter:
        Bucket size = 4, refill rate = 4 per minute
        -> Can handle bursts of 4 requests instantly
        -> Sustained rate of ~1 request per 15 seconds
    """

    async def check_rate_limit(
        self, client: ClientIdentifier, rule: RateLimitRule
    ) -> RateLimitResult:
        """
        Check token bucket and consume one token if available.

        Implementation details:
            - Uses Redis to store current token count and last refill time
            - Calculates tokens to add based on time elapsed
            - Atomic operation via Lua script prevents race conditions
        """
        key = client.get_key(rule)

        # Calculate refill rate in tokens per second
        window_seconds = rule.get_window_seconds()
        refill_rate = rule.requests_per_unit / window_seconds
        capacity = rule.bucket_size or rule.requests_per_unit

        logger.info(
            f"[TOKEN_BUCKET] Checking {key} "
            f"(capacity={capacity}, refill_rate={refill_rate:.2f}/s)"
        )

        # Use Lua script for atomic token consumption
        allowed, remaining = await self.redis.token_bucket_check(
            key, capacity, refill_rate
        )

        if allowed:
            logger.info(
                f"[TOKEN_BUCKET] ✓ ALLOWED {key} "
                f"(remaining tokens: {remaining}/{capacity})"
            )
            return RateLimitResult(
                allowed=True,
                remaining=remaining,
                limit=capacity,
                retry_after=None,
                algorithm="token_bucket"
            )
        else:
            # Calculate retry after based on refill rate
            # Client needs to wait for at least 1 token to be added
            retry_after = int(1 / refill_rate) + 1

            logger.info(
                f"[TOKEN_BUCKET] ✗ REJECTED {key} "
                f"(no tokens available, retry in {retry_after}s)"
            )

            return RateLimitResult(
                allowed=False,
                remaining=0,
                limit=capacity,
                retry_after=retry_after,
                algorithm="token_bucket"
            )
