"""
Factory for creating rate limiter instances.

System Design Concept:
    This allows the system to dynamically select which rate limiting
    algorithm to use based on the rule configuration. Different endpoints
    or users can use different algorithms optimized for their needs.
"""

from src.models import RateLimitAlgorithm
from src.storage.redis_client import RedisClient
from src.services.rate_limiter_base import RateLimiterBase
from src.services.token_bucket import TokenBucketRateLimiter
from src.services.leaky_bucket import LeakyBucketRateLimiter
from src.services.fixed_window import FixedWindowRateLimiter
from src.services.sliding_window_log import SlidingWindowLogRateLimiter
from src.services.sliding_window_counter import SlidingWindowCounterRateLimiter


class RateLimiterFactory:
    """
    Factory for creating rate limiter instances based on algorithm type.

    This implements the Strategy pattern, allowing different algorithms
    to be swapped based on requirements.
    """

    _limiters: dict[RateLimitAlgorithm, type[RateLimiterBase]] = {
        RateLimitAlgorithm.TOKEN_BUCKET: TokenBucketRateLimiter,
        RateLimitAlgorithm.LEAKY_BUCKET: LeakyBucketRateLimiter,
        RateLimitAlgorithm.FIXED_WINDOW: FixedWindowRateLimiter,
        RateLimitAlgorithm.SLIDING_WINDOW_LOG: SlidingWindowLogRateLimiter,
        RateLimitAlgorithm.SLIDING_WINDOW_COUNTER: SlidingWindowCounterRateLimiter,
    }

    @classmethod
    def create(
        cls, algorithm: RateLimitAlgorithm, redis_client: RedisClient
    ) -> RateLimiterBase:
        """
        Create a rate limiter instance for the specified algorithm.

        Args:
            algorithm: Which algorithm to use
            redis_client: Redis client for storage

        Returns:
            Rate limiter instance

        Raises:
            ValueError: If algorithm is not supported
        """
        limiter_class = cls._limiters.get(algorithm)
        if not limiter_class:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        return limiter_class(redis_client)
