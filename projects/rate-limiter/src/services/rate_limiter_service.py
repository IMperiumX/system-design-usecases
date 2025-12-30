"""
Rate Limiter Service - Orchestrates rate limiting with rules

System Design Concept:
    This represents the "Rate Limiter Middleware" from Figure 4-13 in
    the chapter. It loads rules from configuration and applies the
    appropriate algorithm to incoming requests.

    In production (like Lyft's implementation), rules are loaded from
    disk configuration files and cached in memory.

Simulates:
    The detailed design from Figure 4-13 where workers pull rules from
    disk and the middleware fetches them from cache.

Key Methods:
    - check_request: Main entry point for rate limit checks
    - add_rule: Dynamic rule configuration
"""

import logging
from typing import Dict
from src.models import (
    RateLimitRule,
    RateLimitResult,
    ClientIdentifier,
    TimeUnit,
    RateLimitAlgorithm,
)
from src.storage.redis_client import RedisClient
from src.services.rate_limiter_factory import RateLimiterFactory

logger = logging.getLogger(__name__)


class RateLimiterService:
    """
    Central rate limiter service that manages rules and applies algorithms.

    System Design Concept:
        This implements the architecture from Figure 4-13:
        - Rules are stored (simulated as in-memory dict, would be disk in production)
        - Middleware fetches counters from Redis
        - Based on rules, applies appropriate algorithm
        - Returns decision (allow/reject)
    """

    def __init__(self, redis_client: RedisClient):
        self.redis = redis_client
        self.rules: Dict[str, RateLimitRule] = {}
        self._load_default_rules()

    def _load_default_rules(self):
        """
        Load default rate limiting rules.

        System Design Concept:
            These rules follow the format shown in the chapter (page 360-384)
            from Lyft's rate limiter configuration.

        In production:
            - Rules stored as YAML files on disk
            - Workers periodically load from disk to cache
            - Supports hot-reloading without restart
        """
        # Example: Login endpoint (5 requests per minute)
        self.add_rule(
            RateLimitRule(
                domain="auth",
                key="user_id",
                requests_per_unit=5,
                unit=TimeUnit.MINUTE,
                algorithm=RateLimitAlgorithm.SLIDING_WINDOW_COUNTER,
            )
        )

        # Example: API endpoint (100 requests per minute per IP)
        self.add_rule(
            RateLimitRule(
                domain="api",
                key="ip_address",
                requests_per_unit=100,
                unit=TimeUnit.MINUTE,
                algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            )
        )

        # Example: Marketing messages (5 per day per user)
        self.add_rule(
            RateLimitRule(
                domain="messaging",
                key="user_id",
                requests_per_unit=5,
                unit=TimeUnit.DAY,
                algorithm=RateLimitAlgorithm.LEAKY_BUCKET,
            )
        )

        logger.info(f"[SERVICE] Loaded {len(self.rules)} default rules")

    def add_rule(self, rule: RateLimitRule):
        """
        Add or update a rate limiting rule.

        Args:
            rule: Rate limit rule configuration

        The key format matches the domain:key_type pattern from Lyft's
        configuration shown in the chapter.
        """
        rule_key = f"{rule.domain}:{rule.key}"
        self.rules[rule_key] = rule
        logger.info(
            f"[SERVICE] Added rule {rule_key}: "
            f"{rule.requests_per_unit}/{rule.unit.value} "
            f"using {rule.algorithm.value}"
        )

    def get_rule(self, domain: str, key: str) -> RateLimitRule | None:
        """Get rule for a specific domain and key type."""
        rule_key = f"{domain}:{key}"
        return self.rules.get(rule_key)

    async def check_request(
        self, client: ClientIdentifier, domain: str, key_type: str = "user_id"
    ) -> RateLimitResult:
        """
        Check if a request should be allowed or rate limited.

        Args:
            client: Client making the request
            domain: Rule domain (e.g., "auth", "api", "messaging")
            key_type: What to rate limit by ("user_id", "ip_address", etc.)

        Returns:
            RateLimitResult with allow/reject decision and headers

        System Design Concept:
            This is the core decision flow from Figure 4-3:
            1. Request comes to middleware
            2. Middleware checks rate limit
            3. If allowed, forward to API server
            4. If rejected, return HTTP 429

        Implementation:
            1. Look up rule for domain:key_type
            2. Create appropriate algorithm instance
            3. Delegate to algorithm's check_rate_limit
            4. Return result with headers
        """
        # Find matching rule
        rule = self.get_rule(domain, key_type)

        if not rule:
            logger.warning(
                f"[SERVICE] No rule found for {domain}:{key_type}, allowing by default"
            )
            # No rule = no rate limit (fail open)
            return RateLimitResult(
                allowed=True,
                remaining=999,
                limit=1000,
                retry_after=None,
                algorithm="none"
            )

        # Create rate limiter for this algorithm
        limiter = RateLimiterFactory.create(rule.algorithm, self.redis)

        # Check rate limit
        result = await limiter.check_rate_limit(client, rule)

        return result
