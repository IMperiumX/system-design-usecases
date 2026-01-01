"""
Cache abstraction layer for query results.

System Design Concept:
    [[caching-strategy]] - Reduces database load and improves query latency

Simulates:
    Distributed Redis cache layer

At Scale:
    - Redis Cluster with automatic sharding
    - Multi-tier caching (L1: in-memory, L2: Redis)
    - Cache warming for predictable queries
    - Intelligent TTL based on data recency
"""

from django.core.cache import cache
from django.conf import settings
import hashlib
import json
import logging
from typing import Any, Optional, Callable
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class MetricsCache:
    """
    Cache layer for metrics query results.

    Features:
        - Query result caching with intelligent TTL
        - Cache key generation from query parameters
        - Cache invalidation on writes
        - Hit/miss tracking for monitoring

    Usage:
        cache = MetricsCache()
        result = cache.get_or_set(
            key_params={'metric': 'cpu.load', 'start': '2024-01-01'},
            fetch_fn=lambda: expensive_db_query(),
            ttl=300
        )
    """

    def __init__(self, prefix: str = "metrics"):
        self.prefix = prefix
        self.default_ttl = getattr(settings, 'CACHE_DEFAULT_TTL', 300)  # 5 minutes

    def _generate_key(self, **params) -> str:
        """
        Generate cache key from query parameters.

        Uses MD5 hash of sorted JSON to ensure consistent keys
        for equivalent queries regardless of parameter order.
        """
        params_sorted = json.dumps(params, sort_keys=True)
        key_hash = hashlib.md5(params_sorted.encode()).hexdigest()
        return f"{self.prefix}:{key_hash}"

    def get(self, **params) -> Optional[Any]:
        """Retrieve cached value by query parameters."""
        key = self._generate_key(**params)
        value = cache.get(key)

        if value is not None:
            logger.debug(f"Cache HIT: {key[:32]}...")
        else:
            logger.debug(f"Cache MISS: {key[:32]}...")

        return value

    def set(self, value: Any, ttl: Optional[int] = None, **params) -> None:
        """Store value in cache with TTL."""
        key = self._generate_key(**params)
        ttl = ttl or self.default_ttl

        cache.set(key, value, ttl)
        logger.debug(f"Cache SET: {key[:32]}... (TTL: {ttl}s)")

    def get_or_set(
        self,
        fetch_fn: Callable[[], Any],
        ttl: Optional[int] = None,
        **params
    ) -> Any:
        """
        Get from cache or fetch and cache if not found.

        This is the primary method for query result caching.

        Args:
            fetch_fn: Function to call on cache miss
            ttl: Time-to-live in seconds (None = default)
            **params: Query parameters for key generation

        Returns:
            Cached or freshly fetched value
        """
        # Try cache first
        value = self.get(**params)
        if value is not None:
            return value

        # Cache miss - fetch from source
        logger.info(f"Fetching data for cache key {self._generate_key(**params)[:32]}...")
        value = fetch_fn()

        # Store in cache
        self.set(value, ttl=ttl, **params)

        return value

    def invalidate(self, **params) -> None:
        """Invalidate specific cache entry."""
        key = self._generate_key(**params)
        cache.delete(key)
        logger.info(f"Cache INVALIDATED: {key[:32]}...")

    def invalidate_pattern(self, pattern: str) -> None:
        """
        Invalidate all keys matching pattern.

        Note: This requires Redis and is expensive.
        Use sparingly or implement with cache versioning instead.
        """
        # This is a simplified implementation
        # In production, use cache versioning instead of pattern deletion
        logger.warning(f"Pattern invalidation not fully implemented: {pattern}")

    def clear_all(self) -> None:
        """Clear entire cache (use with caution!)."""
        cache.clear()
        logger.warning("Entire cache cleared!")

    @staticmethod
    def adaptive_ttl(data_age: timedelta) -> int:
        """
        Calculate adaptive TTL based on data recency.

        Recent data changes frequently → shorter TTL
        Old data is stable → longer TTL

        Strategy:
            - Data < 1 hour old: 60s TTL (hot data)
            - Data 1-24 hours old: 300s TTL (warm data)
            - Data > 24 hours old: 3600s TTL (cold data)

        This aligns with the chapter's observation that 85% of queries
        are for data from the last 26 hours.
        """
        if data_age < timedelta(hours=1):
            return 60  # 1 minute for very recent data
        elif data_age < timedelta(hours=24):
            return 300  # 5 minutes for recent data
        else:
            return 3600  # 1 hour for old data


class QueryResultCache(MetricsCache):
    """
    Specialized cache for time-series query results.

    Automatically handles TTL based on query time range.
    """

    def cache_query_result(
        self,
        metric_name: str,
        start_time: datetime,
        end_time: datetime,
        labels: dict,
        aggregation: str,
        fetch_fn: Callable[[], Any]
    ) -> Any:
        """
        Cache a time-series query result with intelligent TTL.

        Args:
            metric_name: Metric being queried
            start_time: Query start time
            end_time: Query end time
            labels: Label filters
            aggregation: Aggregation function (avg, max, etc.)
            fetch_fn: Function to fetch data on cache miss

        Returns:
            Query result (from cache or fresh fetch)
        """
        # Calculate how old the data is
        now = datetime.now()
        data_age = now - end_time if end_time < now else timedelta(0)

        # Use adaptive TTL
        ttl = self.adaptive_ttl(data_age)

        # Generate cache key from all parameters
        return self.get_or_set(
            fetch_fn=fetch_fn,
            ttl=ttl,
            metric_name=metric_name,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            labels=labels,
            aggregation=aggregation
        )


class AlertStateCache:
    """
    Cache for alert state lookups.

    Reduces database load for frequent alert state checks.
    Uses shorter TTL since alert state changes frequently.
    """

    def __init__(self):
        self.cache = MetricsCache(prefix="alert_state")
        self.default_ttl = 30  # 30 seconds for alert state

    def get_alert_state(
        self,
        fingerprint: str,
        fetch_fn: Callable[[], Any]
    ) -> Any:
        """Get alert state from cache or database."""
        return self.cache.get_or_set(
            fetch_fn=fetch_fn,
            ttl=self.default_ttl,
            fingerprint=fingerprint
        )

    def invalidate_alert(self, fingerprint: str) -> None:
        """Invalidate alert state cache on state change."""
        self.cache.invalidate(fingerprint=fingerprint)
