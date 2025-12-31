"""
Redis storage layer for leaderboard sorted sets.

System Design Concept:
    Implements [[redis-sorted-sets]] with O(log n) operations using [[skip-list]]
    internal data structure.

Simulates:
    Redis Cluster (production deployment)

Simplifications:
    - Single Redis instance (no sharding)
    - No connection pooling (using redis-py default)
    - No read replicas

At Scale:
    - Shard by score ranges (fixed partition strategy)
    - Add secondary cache for user → shard mapping
    - Use Redis Cluster for auto-failover
    - Enable RDB + AOF persistence
"""

import redis
from typing import List, Tuple, Optional
from datetime import datetime
from django.conf import settings


class RedisLeaderboardStore:
    """
    Abstraction layer for Redis sorted set operations.

    This class demonstrates the core leaderboard operations from the chapter:
    - ZINCRBY: Increment user score
    - ZREVRANGE: Get top N players (descending order)
    - ZREVRANK: Get user's rank (0-indexed)
    - ZSCORE: Get user's score
    """

    def __init__(self):
        """
        Initialize Redis connection.

        System Design Note:
            In production, use connection pooling to reuse connections
            and avoid TCP handshake overhead for each request.
        """
        self.redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            decode_responses=True,  # Return strings instead of bytes
        )

    def _get_leaderboard_key(self, month: Optional[str] = None) -> str:
        """
        Generate Redis key for leaderboard sorted set.

        Args:
            month: Leaderboard month in YYYY-MM format (default: current month)

        Returns:
            Redis key like "leaderboard_2025_01"

        System Design Note:
            Key naming strategy enables:
            - Monthly leaderboard rotation
            - Easy archival of old months
            - Historical queries
        """
        if month is None:
            month = datetime.now().strftime("%Y-%m")
        # Replace hyphen with underscore for Redis key
        month_key = month.replace("-", "_")
        return f"leaderboard_{month_key}"

    def increment_score(
        self, user_id: str, points: int = 1, month: Optional[str] = None
    ) -> int:
        """
        Increment user's score on the leaderboard.

        Args:
            user_id: Unique user identifier (UUID)
            points: Points to add (default: 1)
            month: Leaderboard month (default: current month)

        Returns:
            User's new total score

        Redis Command:
            ZINCRBY leaderboard_2025_01 1 "user_123"

        Time Complexity:
            O(log n) where n is number of users in leaderboard

        System Design Concept:
            [[sorted-set-insert]]: Redis automatically maintains sort order
            during insert. Skip list enables O(log n) insertion.

        At Scale:
            - With sharding, determine target shard from score
            - May need to move user between shards if score crosses boundary
        """
        key = self._get_leaderboard_key(month)
        new_score = self.redis_client.zincrby(key, points, user_id)
        return int(new_score)

    def get_user_score(self, user_id: str, month: Optional[str] = None) -> Optional[int]:
        """
        Get user's current score.

        Args:
            user_id: Unique user identifier
            month: Leaderboard month (default: current month)

        Returns:
            User's score, or None if user not in leaderboard

        Redis Command:
            ZSCORE leaderboard_2025_01 "user_123"

        Time Complexity:
            O(1) using hash table lookup
        """
        key = self._get_leaderboard_key(month)
        score = self.redis_client.zscore(key, user_id)
        return int(score) if score is not None else None

    def get_user_rank(self, user_id: str, month: Optional[str] = None) -> Optional[int]:
        """
        Get user's rank on the leaderboard.

        Args:
            user_id: Unique user identifier
            month: Leaderboard month (default: current month)

        Returns:
            User's rank (1-indexed), or None if user not in leaderboard

        Redis Command:
            ZREVRANK leaderboard_2025_01 "user_123"

        Time Complexity:
            O(log n) traversing skip list

        System Design Concept:
            [[skip-list-search]]: Multi-level indexes enable fast rank lookup
            without scanning all entries.

        Note:
            ZREVRANK returns 0-indexed rank (0 = highest score).
            We add 1 to return 1-indexed rank for user display.
        """
        key = self._get_leaderboard_key(month)
        rank = self.redis_client.zrevrank(key, user_id)
        return rank + 1 if rank is not None else None

    def get_top_n(
        self, n: int = 10, month: Optional[str] = None
    ) -> List[Tuple[str, int]]:
        """
        Get top N players on the leaderboard.

        Args:
            n: Number of top players to fetch (default: 10)
            month: Leaderboard month (default: current month)

        Returns:
            List of (user_id, score) tuples in descending order

        Redis Command:
            ZREVRANGE leaderboard_2025_01 0 9 WITHSCORES

        Time Complexity:
            O(log n + m) where n is total users, m is number to fetch

        System Design Concept:
            [[range-query]]: Skip list enables efficient range queries
            without full table scan.

        Example:
            >>> store.get_top_n(3)
            [('user_5', 987), ('user_12', 965), ('user_7', 943)]
        """
        key = self._get_leaderboard_key(month)
        # ZREVRANGE returns list like ['user1', '100', 'user2', '95', ...]
        # withscores=True pairs them: [('user1', 100.0), ('user2', 95.0), ...]
        results = self.redis_client.zrevrange(
            key, 0, n - 1, withscores=True
        )
        # Convert scores to integers
        return [(user_id, int(score)) for user_id, score in results]

    def get_range(
        self, start: int, end: int, month: Optional[str] = None
    ) -> List[Tuple[str, int]]:
        """
        Get players in a specific rank range.

        Args:
            start: Start rank (0-indexed, inclusive)
            end: End rank (0-indexed, inclusive)
            month: Leaderboard month (default: current month)

        Returns:
            List of (user_id, score) tuples

        Redis Command:
            ZREVRANGE leaderboard_2025_01 <start> <end> WITHSCORES

        Time Complexity:
            O(log n + m) where m is range size

        Use Case:
            Fetch players surrounding a specific user (±4 positions)

        Example:
            # Get ranks 4255-4259 (0-indexed)
            >>> store.get_range(4255, 4259)
            [('user_a', 545), ('user_b', 544), ('user_c', 543), ...]
        """
        key = self._get_leaderboard_key(month)
        results = self.redis_client.zrevrange(
            key, start, end, withscores=True
        )
        return [(user_id, int(score)) for user_id, score in results]

    def get_surrounding_players(
        self, user_id: str, offset: int = 4, month: Optional[str] = None
    ) -> List[Tuple[str, int, bool]]:
        """
        Get players above and below a specific user.

        Args:
            user_id: User to center the results around
            offset: Number of players above/below to include (default: 4)
            month: Leaderboard month (default: current month)

        Returns:
            List of (user_id, score, is_current_user) tuples

        System Design Concept:
            Implements bonus requirement from chapter: show ±4 positions
            around user on leaderboard.

        Algorithm:
            1. Get user's rank (0-indexed)
            2. Calculate range: [max(0, rank - offset), rank + offset]
            3. Fetch range from Redis
            4. Mark current user in results

        Example:
            If user_123 is rank 100 (0-indexed 99):
            - Fetches ranks 95-103 (±4 positions)
            - Returns 9 total players with user_123 marked
        """
        rank = self.get_user_rank(user_id, month)
        if rank is None:
            return []

        # Convert to 0-indexed for Redis
        rank_0indexed = rank - 1
        start = max(0, rank_0indexed - offset)
        end = rank_0indexed + offset

        results = self.get_range(start, end, month)

        # Mark current user
        return [
            (uid, score, uid == user_id)
            for uid, score in results
        ]

    def get_leaderboard_size(self, month: Optional[str] = None) -> int:
        """
        Get total number of users in leaderboard.

        Args:
            month: Leaderboard month (default: current month)

        Returns:
            Count of users in leaderboard

        Redis Command:
            ZCARD leaderboard_2025_01

        Time Complexity:
            O(1) - Redis tracks size in metadata

        Use Case:
            - Capacity planning
            - Calculating percentile ranks
            - Monitoring leaderboard growth
        """
        key = self._get_leaderboard_key(month)
        return self.redis_client.zcard(key)

    def clear_leaderboard(self, month: Optional[str] = None) -> bool:
        """
        Delete a leaderboard (for testing or monthly rotation).

        Args:
            month: Leaderboard month to delete (default: current month)

        Returns:
            True if deleted, False if not found

        Redis Command:
            DEL leaderboard_2025_01

        Time Complexity:
            O(n) to free memory for all entries

        WARNING:
            Use with caution in production. Consider setting TTL instead.
        """
        key = self._get_leaderboard_key(month)
        return self.redis_client.delete(key) > 0

    def set_leaderboard_expiry(
        self, days: int = 90, month: Optional[str] = None
    ) -> bool:
        """
        Set expiration time for a leaderboard.

        Args:
            days: Days until expiration (default: 90)
            month: Leaderboard month (default: current month)

        Returns:
            True if expiry set successfully

        Redis Command:
            EXPIRE leaderboard_2025_01 <seconds>

        System Design Concept:
            [[data-lifecycle-management]]: Automatically remove old leaderboards
            to save Redis memory. Historical data should be in PostgreSQL snapshots.

        Recommended:
            - Keep current month + last 2 months in Redis (hot data)
            - Archive older months to PostgreSQL (warm data)
            - Move to S3/Glacier after 1 year (cold data)
        """
        key = self._get_leaderboard_key(month)
        seconds = days * 24 * 60 * 60
        return self.redis_client.expire(key, seconds)

    def health_check(self) -> bool:
        """
        Check if Redis connection is healthy.

        Returns:
            True if Redis is reachable, False otherwise

        Use Case:
            - Health check endpoint for load balancer
            - Service monitoring and alerting
        """
        try:
            return self.redis_client.ping()
        except redis.ConnectionError:
            return False
