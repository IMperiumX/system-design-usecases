"""
Django REST Framework serializers for leaderboard API.

System Design Concept:
    [[api-design]]: Clean separation between internal data models
    and external API representation.
"""

from rest_framework import serializers
from core.models import User


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for User model.

    Used in leaderboard responses to show player details.
    """

    class Meta:
        model = User
        fields = ["id", "username", "display_name", "avatar_url"]
        read_only_fields = ["id"]


class ScoreUpdateRequestSerializer(serializers.Serializer):
    """
    Serializer for POST /api/v1/scores request.

    Validates score update requests from game service.

    System Design Concept:
        [[input-validation]]: Validate at API boundary to prevent
        invalid data from entering the system.
    """

    user_id = serializers.UUIDField(
        required=True,
        help_text="UUID of user who won the match",
    )

    points = serializers.IntegerField(
        default=1,
        min_value=1,
        max_value=1000,  # Prevent abuse
        help_text="Points earned (default: 1 per win)",
    )

    match_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of match (for audit trail)",
    )

    def validate_user_id(self, value):
        """Validate that user exists."""
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError(f"User {value} not found")
        return value


class ScoreUpdateResponseSerializer(serializers.Serializer):
    """
    Serializer for POST /api/v1/scores response.

    Returns updated user stats after score increment.
    """

    user_id = serializers.UUIDField()
    new_score = serializers.IntegerField()
    rank = serializers.IntegerField()
    month = serializers.CharField()


class LeaderboardEntrySerializer(serializers.Serializer):
    """
    Serializer for a single leaderboard entry.

    Used in GET /api/v1/scores response.
    """

    rank = serializers.IntegerField(help_text="Player's rank (1-indexed)")
    user_id = serializers.UUIDField(help_text="User UUID")
    username = serializers.CharField(help_text="Username")
    display_name = serializers.CharField(help_text="Display name")
    avatar_url = serializers.URLField(help_text="Avatar CDN URL")
    score = serializers.IntegerField(help_text="Total score")


class LeaderboardResponseSerializer(serializers.Serializer):
    """
    Serializer for GET /api/v1/scores response.

    Returns top N players on the leaderboard.
    """

    data = LeaderboardEntrySerializer(many=True)
    total = serializers.IntegerField(help_text="Number of entries returned")
    month = serializers.CharField(help_text="Leaderboard month (YYYY-MM)")


class UserRankResponseSerializer(serializers.Serializer):
    """
    Serializer for GET /api/v1/scores/{user_id} response.

    Returns specific user's rank and score.
    """

    user_id = serializers.UUIDField()
    username = serializers.CharField()
    display_name = serializers.CharField()
    avatar_url = serializers.URLField()
    rank = serializers.IntegerField()
    score = serializers.IntegerField()
    month = serializers.CharField()


class SurroundingPlayerSerializer(serializers.Serializer):
    """
    Serializer for a player in surrounding results.

    Includes is_current_user flag to highlight the queried user.
    """

    rank = serializers.IntegerField()
    user_id = serializers.UUIDField()
    username = serializers.CharField()
    display_name = serializers.CharField()
    score = serializers.IntegerField()
    is_current_user = serializers.BooleanField(default=False)


class SurroundingPlayersResponseSerializer(serializers.Serializer):
    """
    Serializer for GET /api/v1/scores/{user_id}/surrounding response.

    Returns players ±N positions around the queried user.
    """

    data = SurroundingPlayerSerializer(many=True)
    user_rank = serializers.IntegerField()
    month = serializers.CharField()


class LeaderboardStatsSerializer(serializers.Serializer):
    """
    Serializer for leaderboard statistics.

    Used by admin endpoints for monitoring.
    """

    total_users = serializers.IntegerField()
    top_score = serializers.IntegerField()
    month = serializers.CharField()
