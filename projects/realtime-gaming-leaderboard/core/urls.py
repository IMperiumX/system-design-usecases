"""
URL configuration for leaderboard API endpoints.

System Design Concept:
    [[rest-api-design]]: Clean, intuitive URLs following RESTful principles.
"""

from django.urls import path
from core.views import (
    ScoreUpdateView,
    LeaderboardView,
    UserRankView,
    SurroundingPlayersView,
    LeaderboardStatsView,
)

app_name = "core"

urlpatterns = [
    # POST /api/v1/scores - Update user score
    path("scores", ScoreUpdateView.as_view(), name="score-update"),

    # GET /api/v1/scores - Get top N leaderboard
    path("scores/", LeaderboardView.as_view(), name="leaderboard"),

    # GET /api/v1/scores/{user_id} - Get user's rank
    path("scores/<uuid:user_id>", UserRankView.as_view(), name="user-rank"),

    # GET /api/v1/scores/{user_id}/surrounding - Get surrounding players
    path(
        "scores/<uuid:user_id>/surrounding",
        SurroundingPlayersView.as_view(),
        name="surrounding-players",
    ),

    # GET /api/v1/stats - Get leaderboard stats (admin)
    path("stats", LeaderboardStatsView.as_view(), name="stats"),
]
