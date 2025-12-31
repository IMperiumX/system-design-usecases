"""
Django REST Framework views for leaderboard API.

System Design Concept:
    [[api-layer]]: Thin controllers that delegate to service layer.
    Views handle HTTP concerns (status codes, headers), services handle
    business logic.
"""

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, NotFound

from core.services.leaderboard_service import LeaderboardService
from core.serializers import (
    ScoreUpdateRequestSerializer,
    ScoreUpdateResponseSerializer,
    LeaderboardResponseSerializer,
    UserRankResponseSerializer,
    SurroundingPlayersResponseSerializer,
    LeaderboardStatsSerializer,
    LeaderboardEntrySerializer,
)


class ScoreUpdateView(APIView):
    """
    POST /api/v1/scores

    Update user's score after winning a match.

    System Design Concept:
        [[server-authoritative]]: This is an internal API that should
        only be called by the game service, not directly by clients.

    Security:
        In production, require X-Game-Service-Token header authentication.

    At Scale:
        - Add rate limiting per game service instance
        - Use circuit breaker if Redis is slow
        - Consider async processing with message queue
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = LeaderboardService()

    def post(self, request):
        """
        Update user score.

        Expected request body:
            {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "points": 1,
                "match_id": "660f9511-..." (optional)
            }

        Response:
            {
                "user_id": "550e8400-...",
                "new_score": 47,
                "rank": 1523,
                "month": "2025-01"
            }
        """
        # Validate input
        serializer = ScoreUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # TODO: Validate game service token
        # game_token = request.headers.get('X-Game-Service-Token')
        # if game_token != settings.GAME_SERVICE_TOKEN:
        #     return Response({"error": "Unauthorized"}, status=401)

        # Update score via service
        try:
            result = self.service.update_score(
                user_id=str(serializer.validated_data["user_id"]),
                points=serializer.validated_data["points"],
                match_id=serializer.validated_data.get("match_id"),
            )
        except ValueError as e:
            raise NotFound(detail=str(e))

        # Return response
        response_serializer = ScoreUpdateResponseSerializer(result)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class LeaderboardView(APIView):
    """
    GET /api/v1/scores

    Fetch top N players on the leaderboard.

    System Design Concept:
        [[pagination]]: Limit results to prevent large response payloads.
        Client can request more with limit parameter.

    Caching:
        Consider caching top 10 for 1 second (acceptable staleness).
        Use Redis with key pattern: "leaderboard_cache:{month}:top:{n}"

    At Scale:
        - Add CDN caching for top 10 (60 second TTL)
        - Pre-compute top 100 in background job
        - Add ETag header for conditional requests
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = LeaderboardService()

    def get(self, request):
        """
        Get top N players.

        Query params:
            - limit: Number of players (default: 10, max: 100)
            - month: Leaderboard month (default: current month)

        Response:
            {
                "data": [
                    {
                        "rank": 1,
                        "user_id": "...",
                        "username": "alice",
                        "display_name": "Alice",
                        "avatar_url": "...",
                        "score": 987
                    },
                    ...
                ],
                "total": 10,
                "month": "2025-01"
            }
        """
        # Parse query params
        limit = int(request.query_params.get("limit", 10))
        month = request.query_params.get("month")

        # Validate limit
        if limit < 1 or limit > 100:
            return Response(
                {"error": "limit must be between 1 and 100"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Fetch from service
        results = self.service.get_top_n(n=limit, month=month)

        # Build response
        response_data = {
            "data": results,
            "total": len(results),
            "month": month or self.service.redis_store._get_leaderboard_key(month).split("_")[-1].replace("_", "-"),
        }

        serializer = LeaderboardResponseSerializer(response_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UserRankView(APIView):
    """
    GET /api/v1/scores/{user_id}

    Get specific user's rank and score.

    System Design Concept:
        [[personalized-view]]: Shows user their position on global leaderboard.

    Privacy:
        In production, restrict to:
        - Own user_id (authenticated)
        - Friends (if social features enabled)

    At Scale:
        - Cache user rank for 5 seconds (acceptable staleness)
        - Add percentile rank for massive leaderboards (faster than exact rank)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = LeaderboardService()

    def get(self, request, user_id):
        """
        Get user's rank.

        Path params:
            - user_id: UUID of user

        Query params:
            - month: Leaderboard month (optional)

        Response:
            {
                "user_id": "...",
                "username": "alice",
                "display_name": "Alice",
                "avatar_url": "...",
                "rank": 42,
                "score": 123,
                "month": "2025-01"
            }
        """
        month = request.query_params.get("month")

        # Fetch from service
        result = self.service.get_user_rank(user_id, month)

        if result is None:
            raise NotFound(
                detail=f"User {user_id} not found in leaderboard for month {month or 'current'}"
            )

        serializer = UserRankResponseSerializer(result)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SurroundingPlayersView(APIView):
    """
    GET /api/v1/scores/{user_id}/surrounding

    Get players ±N positions around a user (bonus feature).

    System Design Concept:
        [[contextual-ranking]]: Shows user their immediate competition,
        which is more motivating than just seeing "Rank #1,234,567".

    Use Case:
        Mobile game showing:
        - "You're rank 1,234,567"
        - "Beat these 4 players to move up!"
        - Shows immediate goals instead of distant top 10

    At Scale:
        - Pre-compute common offsets (±4, ±10) in background job
        - Cache for 10 seconds (rankings don't change that fast)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = LeaderboardService()

    def get(self, request, user_id):
        """
        Get surrounding players.

        Path params:
            - user_id: UUID of user

        Query params:
            - offset: Number above/below (default: 4, max: 10)
            - month: Leaderboard month (optional)

        Response:
            {
                "data": [
                    {"rank": 98, "username": "player1", "score": 547},
                    {"rank": 99, "username": "player2", "score": 546},
                    {"rank": 100, "username": "alice", "score": 545, "is_current_user": true},
                    {"rank": 101, "username": "player3", "score": 544},
                    {"rank": 102, "username": "player4", "score": 543}
                ],
                "user_rank": 100,
                "month": "2025-01"
            }
        """
        # Parse query params
        offset = int(request.query_params.get("offset", 4))
        month = request.query_params.get("month")

        # Validate offset
        if offset < 1 or offset > 10:
            return Response(
                {"error": "offset must be between 1 and 10"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Fetch from service
        result = self.service.get_surrounding_players(user_id, offset, month)

        if not result["data"]:
            raise NotFound(
                detail=f"User {user_id} not found in leaderboard for month {month or 'current'}"
            )

        serializer = SurroundingPlayersResponseSerializer(result)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LeaderboardStatsView(APIView):
    """
    GET /api/v1/stats

    Get leaderboard statistics (admin endpoint).

    Use Case:
        - Admin dashboard
        - Monitoring and alerting
        - Capacity planning

    At Scale:
        - Cache for 60 seconds
        - Add more metrics (p50/p95 scores, DAU trend, etc.)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.service = LeaderboardService()

    def get(self, request):
        """
        Get leaderboard stats.

        Query params:
            - month: Leaderboard month (optional)

        Response:
            {
                "total_users": 1234567,
                "top_score": 987,
                "month": "2025-01"
            }
        """
        month = request.query_params.get("month")
        result = self.service.get_leaderboard_stats(month)

        serializer = LeaderboardStatsSerializer(result)
        return Response(serializer.data, status=status.HTTP_200_OK)
