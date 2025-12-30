"""
Redis client for rate limiter storage.

System Design Concept:
    This implements the storage layer from Figure 4-12 in the chapter.
    Redis is chosen for its:
    - Fast in-memory operations
    - Built-in INCR and EXPIRE commands
    - Support for Lua scripts to prevent race conditions
    - Time-based expiration strategies

Simulates:
    Production Redis cluster (in practice, we'd use Redis Cluster or Sentinel
    for high availability across multiple data centers as mentioned in the
    chapter's distributed environment section)

Simplifications:
    - Single Redis instance (production would use cluster/replication)
    - No connection pooling optimization
    - Synchronization is simplified (production needs cross-datacenter sync)

Race Condition Handling:
    As discussed on page 437-442, concurrent requests can cause race conditions.
    We use Lua scripts (mentioned in the chapter) to ensure atomic operations.
"""

import logging
import time
from typing import Any
import redis.asyncio as redis
from src.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Async Redis client wrapper for rate limiter operations.

    Provides atomic operations using Lua scripts to prevent race conditions
    as described in the chapter (page 444-445).
    """

    def __init__(self):
        self._client: redis.Redis | None = None
        self._lua_scripts: dict[str, Any] = {}

    async def connect(self):
        """Establish connection to Redis."""
        self._client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password if settings.redis_password else None,
            decode_responses=True,
        )
        logger.info(f"[REDIS] Connected to {settings.redis_host}:{settings.redis_port}")
        await self._load_lua_scripts()

    async def disconnect(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            logger.info("[REDIS] Disconnected")

    async def _load_lua_scripts(self):
        """
        Load Lua scripts for atomic operations.

        System Design Concept:
            Lua scripts solve race conditions (page 444) by executing
            atomically on the Redis server. This prevents two concurrent
            requests from reading the same counter value and both
            incrementing it incorrectly.
        """
        # Script for atomic increment with limit check
        # Returns: [allowed (0/1), current_count, ttl]
        increment_script = """
        local key = KEYS[1]
        local limit = tonumber(ARGV[1])
        local window = tonumber(ARGV[2])

        local current = tonumber(redis.call('get', key) or '0')

        if current < limit then
            local new_count = redis.call('incr', key)
            if new_count == 1 then
                redis.call('expire', key, window)
            end
            local ttl = redis.call('ttl', key)
            return {1, new_count, ttl}
        else
            local ttl = redis.call('ttl', key)
            return {0, current, ttl}
        end
        """

        # Script for token bucket algorithm
        # Returns: [allowed (0/1), remaining_tokens]
        token_bucket_script = """
        local key = KEYS[1]
        local capacity = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])

        local tokens_key = key .. ':tokens'
        local timestamp_key = key .. ':timestamp'

        local tokens = tonumber(redis.call('get', tokens_key) or capacity)
        local last_refill = tonumber(redis.call('get', timestamp_key) or now)

        -- Calculate tokens to add based on time elapsed
        local elapsed = now - last_refill
        local tokens_to_add = elapsed * refill_rate
        tokens = math.min(capacity, tokens + tokens_to_add)

        local allowed = 0
        if tokens >= 1 then
            tokens = tokens - 1
            allowed = 1
        end

        redis.call('set', tokens_key, tokens)
        redis.call('set', timestamp_key, now)
        redis.call('expire', tokens_key, 3600)
        redis.call('expire', timestamp_key, 3600)

        return {allowed, math.floor(tokens)}
        """

        self._lua_scripts["increment"] = self._client.register_script(increment_script)
        self._lua_scripts["token_bucket"] = self._client.register_script(token_bucket_script)
        logger.info("[REDIS] Lua scripts loaded")

    async def incr_with_limit(
        self, key: str, limit: int, window_seconds: int
    ) -> tuple[bool, int, int]:
        """
        Atomically increment counter if under limit.

        Args:
            key: Redis key for the counter
            limit: Maximum allowed count
            window_seconds: Time window in seconds

        Returns:
            (allowed, current_count, ttl_seconds)

        System Design Concept:
            This implements the basic counter logic from Figure 4-12.
            The INCR and EXPIRE commands mentioned in the chapter (page 330-331)
            are combined in a Lua script for atomicity.
        """
        result = await self._lua_scripts["increment"](
            keys=[key], args=[limit, window_seconds]
        )
        allowed = bool(result[0])
        count = int(result[1])
        ttl = int(result[2]) if result[2] > 0 else window_seconds

        action = "ALLOWED" if allowed else "REJECTED"
        logger.debug(f"[REDIS] {action} key={key} count={count}/{limit} ttl={ttl}s")

        return allowed, count, ttl

    async def token_bucket_check(
        self, key: str, capacity: int, refill_rate: float
    ) -> tuple[bool, int]:
        """
        Check token bucket and consume one token if available.

        Args:
            key: Redis key for the bucket
            capacity: Maximum tokens in bucket
            refill_rate: Tokens added per second

        Returns:
            (allowed, remaining_tokens)

        System Design Concept:
            Implements token bucket algorithm (page 132-137) using Lua
            for atomic token consumption and refilling.
        """
        now = time.time()
        result = await self._lua_scripts["token_bucket"](
            keys=[key], args=[capacity, refill_rate, now]
        )
        allowed = bool(result[0])
        remaining = int(result[1])

        action = "ALLOWED" if allowed else "REJECTED"
        logger.debug(
            f"[REDIS] TOKEN_BUCKET {action} key={key} remaining={remaining}/{capacity}"
        )

        return allowed, remaining

    async def get(self, key: str) -> str | None:
        """Get value for key."""
        return await self._client.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None):
        """
        Set key to value with optional expiration.

        Args:
            key: Redis key
            value: Value to store
            ex: Expiration time in seconds (TTL)
        """
        await self._client.set(key, value, ex=ex)

    async def incr(self, key: str) -> int:
        """
        Increment counter by 1 (Redis INCR command from chapter).

        Returns the new value after incrementing.
        """
        return await self._client.incr(key)

    async def expire(self, key: str, seconds: int):
        """
        Set expiration on key (Redis EXPIRE command from chapter).

        Args:
            key: Redis key
            seconds: TTL in seconds
        """
        await self._client.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        """
        Get time-to-live for key in seconds.

        Returns:
            Seconds until expiration, or -1 if no expiration, -2 if key doesn't exist
        """
        return await self._client.ttl(key)

    async def zadd(self, key: str, mapping: dict[str, float]):
        """
        Add members to sorted set (for sliding window log).

        System Design Concept:
            Sorted sets are mentioned on page 250 for implementing
            sliding window log algorithm. Timestamps are stored as scores.
        """
        await self._client.zadd(key, mapping)

    async def zremrangebyscore(self, key: str, min_score: float, max_score: float):
        """Remove members from sorted set with scores in range."""
        await self._client.zremrangebyscore(key, min_score, max_score)

    async def zcard(self, key: str) -> int:
        """Get number of members in sorted set."""
        return await self._client.zcard(key)

    async def delete(self, *keys: str):
        """Delete one or more keys."""
        await self._client.delete(*keys)

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        return await self._client.exists(key) > 0


# Global Redis client instance
redis_client = RedisClient()
