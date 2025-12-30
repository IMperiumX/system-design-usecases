"""
Base interface for rate limiting algorithms.

System Design Concept:
    The chapter discusses 5 different rate limiting algorithms, each with
    different trade-offs. This base class defines a common interface for
    all implementations, allowing the system to switch algorithms easily.
"""

from abc import ABC, abstractmethod
from src.models import RateLimitRule, RateLimitResult, ClientIdentifier
from src.storage.redis_client import RedisClient


class RateLimiterBase(ABC):
    """
    Abstract base class for rate limiting algorithms.

    All algorithms from the chapter inherit from this and implement
    the check_rate_limit method with their specific logic.
    """

    def __init__(self, redis_client: RedisClient):
        self.redis = redis_client

    @abstractmethod
    async def check_rate_limit(
        self, client: ClientIdentifier, rule: RateLimitRule
    ) -> RateLimitResult:
        """
        Check if request should be allowed or rate limited.

        Args:
            client: Client making the request
            rule: Rate limit rule to apply

        Returns:
            RateLimitResult indicating if allowed and quota info

        System Design Concept:
            This is the core decision point shown in Figure 4-3.
            The middleware calls this method to determine if a request
            should proceed or return HTTP 429.
        """
        pass

    def _get_retry_after(self, ttl: int) -> int:
        """
        Calculate seconds until the rate limit window resets.

        This is used for the X-Ratelimit-Retry-After header
        as described in the chapter (page 401-402).
        """
        return max(ttl, 1)
