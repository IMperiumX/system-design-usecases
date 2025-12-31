"""
Cache Service - Metadata caching layer

System Design Concept:
    Implements [[caching-strategies]] (cache-aside pattern)

Simulates:
    Distributed Redis cluster

At Scale:
    - Redis Cluster with consistent hashing
    - Multi-layer cache (L1: in-process, L2: Redis)
    - Cache replication for high availability
"""

from datetime import datetime, timedelta
from typing import Optional, Any
import json

from src.config import settings


class CacheService:
    """
    In-memory cache simulating Redis

    Production implementation would use:
        import aioredis
        redis = await aioredis.create_redis_pool('redis://localhost')
    """

    def __init__(self):
        self._cache: dict[str, tuple[Any, datetime]] = {}  # key → (value, expiry)
        self.ttl = timedelta(seconds=settings.cache_ttl_seconds)
        self.enabled = settings.enable_metadata_cache

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache

        Returns:
            Cached value if exists and not expired, None otherwise
        """
        if not self.enabled:
            return None

        if key not in self._cache:
            return None

        value, expiry = self._cache[key]

        # Check expiration
        if datetime.utcnow() > expiry:
            # Expired, delete
            del self._cache[key]
            return None

        return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """
        Set value in cache

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (None = use default)
        """
        if not self.enabled:
            return

        expiry_delta = timedelta(seconds=ttl) if ttl else self.ttl
        expiry = datetime.utcnow() + expiry_delta

        self._cache[key] = (value, expiry)

    async def delete(self, key: str):
        """
        Delete key from cache

        Used for cache invalidation on updates
        """
        if key in self._cache:
            del self._cache[key]

    async def delete_pattern(self, pattern: str):
        """
        Delete all keys matching pattern

        Example:
            await cache.delete_pattern("user:123:*")

        Simulates:
            Redis KEYS command + DEL
        """
        keys_to_delete = [k for k in self._cache.keys() if self._matches_pattern(k, pattern)]
        for key in keys_to_delete:
            del self._cache[key]

    def _matches_pattern(self, key: str, pattern: str) -> bool:
        """Simple glob-style pattern matching"""
        import fnmatch
        return fnmatch.fnmatch(key, pattern)

    async def exists(self, key: str) -> bool:
        """Check if key exists and is not expired"""
        return await self.get(key) is not None

    async def clear(self):
        """Clear entire cache (for testing)"""
        self._cache.clear()

    def get_stats(self) -> dict:
        """Get cache statistics"""
        return {
            "size": len(self._cache),
            "enabled": self.enabled,
            "ttl_seconds": settings.cache_ttl_seconds,
        }


# Global cache instance
cache = CacheService()


# ============================================================================
# HELPER FUNCTIONS FOR COMMON CACHE PATTERNS
# ============================================================================


def file_cache_key(file_id: str) -> str:
    """Generate cache key for file metadata"""
    return f"file:{file_id}"


def user_files_cache_key(user_id: str) -> str:
    """Generate cache key for user's file list"""
    return f"user:{user_id}:files"


def block_cache_key(block_hash: str) -> str:
    """Generate cache key for block metadata"""
    return f"block:{block_hash}"


async def cache_file_metadata(file_id: str, metadata: dict, ttl: Optional[int] = None):
    """Cache file metadata"""
    await cache.set(file_cache_key(file_id), metadata, ttl)


async def get_cached_file_metadata(file_id: str) -> Optional[dict]:
    """Get cached file metadata"""
    return await cache.get(file_cache_key(file_id))


async def invalidate_file_cache(file_id: str, user_id: str):
    """
    Invalidate all cache entries related to a file

    Must be called on every file update!
    """
    await cache.delete(file_cache_key(file_id))
    await cache.delete(user_files_cache_key(user_id))
