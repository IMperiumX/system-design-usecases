"""
Data models for the rate limiter system.

System Design Concept:
    These models represent the rate limiting rules and responses discussed
    in the chapter. In production systems like Lyft's rate limiter, rules
    are stored as YAML configurations and loaded into memory.

Key Models:
    - RateLimitRule: Defines throttle limits per endpoint/user/IP
    - RateLimitResult: Response indicating if request is allowed
    - RateLimitHeaders: HTTP headers to inform clients of quota
"""

from enum import Enum
from pydantic import BaseModel, Field, field_validator
from typing import Literal


class TimeUnit(str, Enum):
    """Time units for rate limit windows."""
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


class RateLimitAlgorithm(str, Enum):
    """
    Available rate limiting algorithms from the chapter.

    - TOKEN_BUCKET: Allows burst traffic, used by Amazon & Stripe
    - LEAKY_BUCKET: Fixed processing rate, used by Shopify
    - FIXED_WINDOW: Simple counter, has edge case issues
    - SLIDING_WINDOW_LOG: Most accurate, memory intensive
    - SLIDING_WINDOW_COUNTER: Hybrid approach, good balance
    """
    TOKEN_BUCKET = "token_bucket"
    LEAKY_BUCKET = "leaky_bucket"
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW_LOG = "sliding_window_log"
    SLIDING_WINDOW_COUNTER = "sliding_window_counter"


class RateLimitRule(BaseModel):
    """
    Configuration for a rate limit rule.

    Example from chapter (Lyft's config format):
        domain: auth
        descriptors:
          - key: auth_type
            value: login
            rate_limit:
              unit: minute
              requests_per_unit: 5

    Attributes:
        domain: Rule category (e.g., "auth", "messaging", "api")
        key: Identifier type (e.g., "user_id", "ip_address", "endpoint")
        requests_per_unit: Maximum allowed requests
        unit: Time window for the limit
        algorithm: Which rate limiting algorithm to use
    """
    domain: str = Field(description="Rule category/namespace")
    key: str = Field(description="What to rate limit by (user_id, ip, etc)")
    requests_per_unit: int = Field(gt=0, description="Max requests allowed")
    unit: TimeUnit = Field(description="Time window")
    algorithm: RateLimitAlgorithm = Field(
        default=RateLimitAlgorithm.TOKEN_BUCKET,
        description="Algorithm to use"
    )

    # Token bucket specific parameters
    bucket_size: int | None = Field(
        default=None,
        description="Max tokens in bucket (defaults to requests_per_unit)"
    )
    refill_rate: int | None = Field(
        default=None,
        description="Tokens added per second (computed from requests_per_unit)"
    )

    # Leaky bucket specific parameters
    queue_size: int | None = Field(
        default=None,
        description="Max queue size (defaults to requests_per_unit * 2)"
    )

    @field_validator("bucket_size", mode="before")
    @classmethod
    def set_bucket_size(cls, v, info):
        """Default bucket size to requests_per_unit if not specified."""
        if v is None and "requests_per_unit" in info.data:
            return info.data["requests_per_unit"]
        return v

    @field_validator("queue_size", mode="before")
    @classmethod
    def set_queue_size(cls, v, info):
        """Default queue size to 2x requests_per_unit if not specified."""
        if v is None and "requests_per_unit" in info.data:
            return info.data["requests_per_unit"] * 2
        return v

    def get_window_seconds(self) -> int:
        """Convert time unit to seconds."""
        mapping = {
            TimeUnit.SECOND: 1,
            TimeUnit.MINUTE: 60,
            TimeUnit.HOUR: 3600,
            TimeUnit.DAY: 86400,
        }
        return mapping[self.unit]


class RateLimitResult(BaseModel):
    """
    Result of a rate limit check.

    System Design Concept:
        This represents the decision made by the rate limiter middleware
        (Figure 4-3 in the chapter). If allowed=False, the middleware
        returns HTTP 429 to the client.

    Attributes:
        allowed: Whether the request should proceed
        remaining: Requests remaining in current window
        limit: Total requests allowed per window
        retry_after: Seconds until window resets (if throttled)
        algorithm: Which algorithm made the decision
    """
    allowed: bool
    remaining: int = Field(ge=0)
    limit: int = Field(gt=0)
    retry_after: int | None = Field(default=None, ge=0)
    algorithm: str

    def to_headers(self) -> dict[str, str]:
        """
        Convert to HTTP rate limit headers.

        As described in the chapter (page 397-402):
            X-Ratelimit-Remaining: Remaining requests in window
            X-Ratelimit-Limit: Max requests per window
            X-Ratelimit-Retry-After: Seconds until retry (if throttled)
        """
        headers = {
            "X-Ratelimit-Remaining": str(self.remaining),
            "X-Ratelimit-Limit": str(self.limit),
        }
        if self.retry_after is not None:
            headers["X-Ratelimit-Retry-After"] = str(self.retry_after)
        return headers


class ClientIdentifier(BaseModel):
    """
    Identifies a client for rate limiting purposes.

    System Design Concept:
        Rate limiting can be applied per IP, per user, or per endpoint
        (as discussed in chapter requirements). This model encapsulates
        the various ways to identify a client.

    Attributes:
        user_id: Authenticated user identifier
        ip_address: Client IP address
        endpoint: API endpoint being accessed
    """
    user_id: str | None = None
    ip_address: str | None = None
    endpoint: str | None = None

    def get_key(self, rule: RateLimitRule) -> str:
        """
        Generate Redis key for this client based on the rule.

        Format: rate_limit:{domain}:{key_type}:{identifier}

        Example:
            rule.domain = "auth"
            rule.key = "user_id"
            client.user_id = "user123"
            -> "rate_limit:auth:user_id:user123"
        """
        if rule.key == "user_id" and self.user_id:
            identifier = self.user_id
        elif rule.key == "ip_address" and self.ip_address:
            identifier = self.ip_address
        elif rule.key == "endpoint" and self.endpoint:
            identifier = self.endpoint
        else:
            identifier = "anonymous"

        return f"rate_limit:{rule.domain}:{rule.key}:{identifier}"
