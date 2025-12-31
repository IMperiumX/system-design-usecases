"""
Leaderboard service - Business logic layer.

System Design Concept:
    Implements [[separation-of-concerns]] pattern:
    - Views handle HTTP (request/response)
    - Services handle business logic
    - Storage handles data access

Simulates:
    Dedicated microservice in production architecture
"""

import uuid
from datetime import datetime
from typing import List, Dict, Optional
from django.db import transaction

from core.models import User, Game, LeaderboardSnapshot
from core.storage.redis_store import RedisLeaderboardStore


class LeaderboardService:
    """
    Core leaderboard business logic.

    This service orchestrates between Redis (for real-time rankings)
    and PostgreSQL (for user data and audit logs).

    System Design Concepts:
        - [[polyglot-persistence]]: Redis + PostgreSQL for different use cases
        - [[cqrs-lite]]: Separate paths for writes (update_score) and reads (get_top_n)
        - [[read-through-cache]]: Fetch from Redis, fall back to DB for user details
    """

    def __init__(self):
        """Initialize service with Redis store."""
        self.redis_store = RedisLeaderboardStore()

    def update_score(
        self,
        user_id: str,
        points: int = 1,
        match_id: Optional[str] = None,
        month: Optional[str] = None,
    ) -> Dict:
        """
        Update user's score after winning a match.

        Args:
            user_id: UUID of user who won
            points: Points earned (default: 1)
            match_id: UUID of match (for audit trail)
            month: Leaderboard month (default: current month)

        Returns:
            Dict with new_score, rank, and month

        Workflow:
            1. Validate user exists in database
            2. Increment score in Redis (O(log n))
            3. Log match to PostgreSQL (audit trail)
            4. Fetch new rank from Redis (O(log n))
            5. Return updated stats

        System Design Concept:
            [[write-pattern]]: Redis is primary data store, PostgreSQL is audit log.
            This enables fast writes (Redis) with full history (PostgreSQL).

        At Scale:
            - Use message queue (Kafka) to decouple Redis update from DB insert
            - Batch DB inserts every 10 seconds to reduce write load
            - Add circuit breaker if DB is slow (don't block Redis updates)

        Raises:
            ValueError: If user doesn't exist
        """
        # Validate user exists
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            raise ValueError(f"User {user_id} not found")

        # Determine month
        if month is None:
            month = datetime.now().strftime("%Y-%m")

        # Generate match ID if not provided
        if match_id is None:
            match_id = str(uuid.uuid4())

        # Update score in Redis (fast path - O(log n))
        new_score = self.redis_store.increment_score(user_id, points, month)

        # Log to database (audit trail - async in production)
        Game.objects.create(
            user=user,
            score_earned=points,
            match_id=match_id,
            leaderboard_month=month,
        )

        # Get new rank
        new_rank = self.redis_store.get_user_rank(user_id, month)

        return {
            "user_id": user_id,
            "new_score": new_score,
            "rank": new_rank,
            "month": month,
        }

    def get_top_n(self, n: int = 10, month: Optional[str] = None) -> List[Dict]:
        """
        Fetch top N players on the leaderboard.

        Args:
            n: Number of players to return (default: 10)
            month: Leaderboard month (default: current month)

        Returns:
            List of dicts with rank, user_id, username, display_name, score

        Workflow:
            1. Fetch top N from Redis (O(log n + n))
            2. Batch fetch user details from PostgreSQL (1 query)
            3. Merge leaderboard data + user details
            4. Return enriched results

        System Design Concept:
            [[read-pattern]]: Redis for rankings (real-time), PostgreSQL for
            user metadata (relatively static).

        Optimization:
            Cache user details for top 10 in Redis hash (avoid DB query).
            Invalidate cache on profile update.

        Example:
            >>> service.get_top_n(3)
            [
                {"rank": 1, "user_id": "...", "username": "alice", "score": 987},
                {"rank": 2, "user_id": "...", "username": "bob", "score": 965},
                ...
            ]
        """
        # Get top N from Redis
        top_players = self.redis_store.get_top_n(n, month)

        if not top_players:
            return []

        # Extract user IDs
        user_ids = [user_id for user_id, _ in top_players]

        # Batch fetch user details (1 DB query instead of N)
        users = User.objects.filter(id__in=user_ids).in_bulk(field_name="id")

        # Merge results
        results = []
        for rank, (user_id, score) in enumerate(top_players, start=1):
            user = users.get(user_id)
            if user:
                results.append(
                    {
                        "rank": rank,
                        "user_id": str(user.id),
                        "username": user.username,
                        "display_name": user.display_name,
                        "avatar_url": user.avatar_url,
                        "score": score,
                    }
                )

        return results

    def get_user_rank(self, user_id: str, month: Optional[str] = None) -> Optional[Dict]:
        """
        Get specific user's rank and score.

        Args:
            user_id: UUID of user
            month: Leaderboard month (default: current month)

        Returns:
            Dict with user details, rank, and score, or None if not found

        Workflow:
            1. Fetch rank from Redis (O(log n))
            2. Fetch score from Redis (O(1))
            3. Fetch user details from PostgreSQL
            4. Return combined result

        Returns None if:
            - User not in leaderboard (hasn't won any matches this month)
            - User doesn't exist in database

        Example:
            >>> service.get_user_rank("550e8400-...")
            {
                "user_id": "550e8400-...",
                "username": "alice",
                "rank": 42,
                "score": 123,
                "month": "2025-01"
            }
        """
        # Get rank and score from Redis
        rank = self.redis_store.get_user_rank(user_id, month)
        if rank is None:
            return None

        score = self.redis_store.get_user_score(user_id, month)

        # Get user details from DB
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

        if month is None:
            month = datetime.now().strftime("%Y-%m")

        return {
            "user_id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "avatar_url": user.avatar_url,
            "rank": rank,
            "score": score,
            "month": month,
        }

    def get_surrounding_players(
        self, user_id: str, offset: int = 4, month: Optional[str] = None
    ) -> Dict:
        """
        Get players above and below a specific user (bonus feature).

        Args:
            user_id: UUID of user to center results around
            offset: Number of players above/below (default: 4)
            month: Leaderboard month (default: current month)

        Returns:
            Dict with:
                - data: List of players with ranks and scores
                - user_rank: Rank of the requested user
                - month: Leaderboard month

        System Design Concept:
            Implements bonus requirement from chapter: show ±4 positions
            around user for better context (e.g., "You're rank 1,234,567
            but look, you're close to passing these 4 players!").

        Use Case:
            Mobile game leaderboard showing:
            - Top 10 global leaders
            - Your position + nearby players

        Example:
            >>> service.get_surrounding_players("user_123", offset=2)
            {
                "data": [
                    {"rank": 98, "username": "player1", "score": 547},
                    {"rank": 99, "username": "player2", "score": 546},
                    {"rank": 100, "username": "alice", "score": 545, "is_current_user": True},
                    {"rank": 101, "username": "player3", "score": 544},
                    {"rank": 102, "username": "player4", "score": 543},
                ],
                "user_rank": 100,
                "month": "2025-01"
            }
        """
        # Get surrounding players from Redis
        surrounding = self.redis_store.get_surrounding_players(user_id, offset, month)

        if not surrounding:
            return {"data": [], "user_rank": None, "month": month}

        # Extract user IDs
        user_ids = [uid for uid, _, _ in surrounding]

        # Batch fetch user details
        users = User.objects.filter(id__in=user_ids).in_bulk(field_name="id")

        # Get user's rank
        user_rank = self.redis_store.get_user_rank(user_id, month)

        # Build results
        results = []
        for uid, score, is_current in surrounding:
            user = users.get(uid)
            if user:
                # Calculate actual rank (1-indexed)
                rank = self.redis_store.get_user_rank(uid, month)
                player_data = {
                    "rank": rank,
                    "user_id": str(user.id),
                    "username": user.username,
                    "display_name": user.display_name,
                    "score": score,
                }
                if is_current:
                    player_data["is_current_user"] = True
                results.append(player_data)

        if month is None:
            month = datetime.now().strftime("%Y-%m")

        return {"data": results, "user_rank": user_rank, "month": month}

    def get_leaderboard_stats(self, month: Optional[str] = None) -> Dict:
        """
        Get statistics about the leaderboard.

        Args:
            month: Leaderboard month (default: current month)

        Returns:
            Dict with total_users, top_score, and month

        Use Case:
            - Admin dashboard
            - Capacity planning
            - Player engagement metrics

        Example:
            >>> service.get_leaderboard_stats()
            {
                "total_users": 1_234_567,
                "top_score": 987,
                "month": "2025-01"
            }
        """
        if month is None:
            month = datetime.now().strftime("%Y-%m")

        total_users = self.redis_store.get_leaderboard_size(month)

        # Get top score
        top_players = self.redis_store.get_top_n(1, month)
        top_score = top_players[0][1] if top_players else 0

        return {"total_users": total_users, "top_score": top_score, "month": month}

    @transaction.atomic
    def archive_leaderboard(self, month: str) -> int:
        """
        Archive leaderboard to PostgreSQL snapshots (monthly cron job).

        Args:
            month: Month to archive in YYYY-MM format

        Returns:
            Number of snapshots created

        Workflow:
            1. Fetch entire leaderboard from Redis
            2. Bulk create LeaderboardSnapshot records
            3. Set Redis TTL to 7 days (grace period)
            4. Return count of archived users

        System Design Concept:
            [[data-lifecycle-management]]: Move from hot storage (Redis)
            to warm storage (PostgreSQL) to cold storage (S3/Glacier).

        Recommended Schedule:
            Run at 00:00:00 on 1st of each month (UTC)

        At Scale:
            - Stream to S3 in Parquet format
            - Use AWS Glue to partition by month
            - Query with Athena for historical analytics

        Example:
            >>> service.archive_leaderboard("2024-12")
            1_234_567  # Archived 1.2M users
        """
        # Fetch all users from leaderboard (can be millions!)
        # This is acceptable as a monthly batch job
        all_players = self.redis_store.get_range(0, -1, month)

        # Bulk create snapshots
        snapshots = []
        for rank, (user_id, score) in enumerate(all_players, start=1):
            try:
                user = User.objects.get(id=user_id)
                snapshots.append(
                    LeaderboardSnapshot(
                        user=user,
                        month=month,
                        final_score=score,
                        final_rank=rank,
                    )
                )
            except User.DoesNotExist:
                # Skip if user was deleted
                continue

        # Bulk insert (much faster than individual creates)
        LeaderboardSnapshot.objects.bulk_create(
            snapshots, ignore_conflicts=True  # Skip duplicates
        )

        # Set expiry on Redis sorted set (7 days grace period)
        self.redis_store.set_leaderboard_expiry(days=7, month=month)

        return len(snapshots)

    def rebuild_from_games(self, month: str) -> int:
        """
        Rebuild leaderboard from Game audit logs (disaster recovery).

        Args:
            month: Month to rebuild in YYYY-MM format

        Returns:
            Number of users restored

        Workflow:
            1. Clear existing Redis leaderboard
            2. Query all games for the month from PostgreSQL
            3. Aggregate scores per user
            4. Bulk insert into Redis

        System Design Concept:
            [[event-sourcing]]: Audit log (Game model) is source of truth.
            Redis leaderboard can be rebuilt from events.

        Use Case:
            - Redis node failure (before read replica promoted)
            - Data corruption in Redis
            - Migrating to new Redis cluster

        Warning:
            This can take several minutes for millions of games.
            Consider running offline or during low-traffic period.

        Example:
            >>> service.rebuild_from_games("2025-01")
            987_654  # Restored 987K users
        """
        # Clear existing leaderboard
        self.redis_store.clear_leaderboard(month)

        # Aggregate scores from game logs
        from django.db.models import Sum, Count

        user_scores = (
            Game.objects.filter(leaderboard_month=month)
            .values("user_id")
            .annotate(total_score=Sum("score_earned"), game_count=Count("id"))
        )

        # Bulk insert into Redis
        count = 0
        for entry in user_scores:
            user_id = str(entry["user_id"])
            score = entry["total_score"]
            self.redis_store.increment_score(user_id, score, month)
            count += 1

        return count
