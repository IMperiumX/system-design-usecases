"""
Django admin configuration for leaderboard models.

System Design Concept:
    Admin panel provides observability into the system for debugging
    and monitoring. Critical for understanding data in development.
"""

from django.contrib import admin
from core.models import User, Game, LeaderboardSnapshot


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """
    Admin interface for User model.

    Use Case:
        - Create test users for demo
        - View user details
        - Search users by username/display_name
    """

    list_display = ["id", "username", "display_name", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["username", "display_name"]
    readonly_fields = ["id", "created_at"]
    ordering = ["-created_at"]

    fieldsets = (
        ("Identity", {"fields": ("id", "username", "display_name")}),
        ("Profile", {"fields": ("avatar_url",)}),
        ("Metadata", {"fields": ("created_at",)}),
    )


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    """
    Admin interface for Game model (audit log).

    Use Case:
        - View game history
        - Debug score calculation issues
        - Analyze player activity patterns
    """

    list_display = [
        "id",
        "user",
        "score_earned",
        "leaderboard_month",
        "played_at",
    ]
    list_filter = ["leaderboard_month", "played_at"]
    search_fields = ["user__username", "match_id"]
    readonly_fields = ["id", "played_at"]
    ordering = ["-played_at"]
    raw_id_fields = ["user"]  # Use search widget for foreign key

    fieldsets = (
        ("Game Details", {"fields": ("user", "match_id", "score_earned")}),
        ("Leaderboard", {"fields": ("leaderboard_month",)}),
        ("Metadata", {"fields": ("id", "played_at")}),
    )

    def get_queryset(self, request):
        """Optimize query with select_related to avoid N+1."""
        queryset = super().get_queryset(request)
        return queryset.select_related("user")


@admin.register(LeaderboardSnapshot)
class LeaderboardSnapshotAdmin(admin.ModelAdmin):
    """
    Admin interface for LeaderboardSnapshot model.

    Use Case:
        - View historical leaderboards
        - Verify monthly archival process
        - Compare rankings across months
    """

    list_display = ["user", "month", "final_rank", "final_score", "created_at"]
    list_filter = ["month", "created_at"]
    search_fields = ["user__username"]
    readonly_fields = ["created_at"]
    ordering = ["month", "final_rank"]
    raw_id_fields = ["user"]

    fieldsets = (
        ("Leaderboard", {"fields": ("user", "month")}),
        ("Final Standings", {"fields": ("final_rank", "final_score")}),
        ("Metadata", {"fields": ("created_at",)}),
    )

    def get_queryset(self, request):
        """Optimize query with select_related."""
        queryset = super().get_queryset(request)
        return queryset.select_related("user")
