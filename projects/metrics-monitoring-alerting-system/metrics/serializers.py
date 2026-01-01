"""
Django REST Framework Serializers

Handles JSON serialization/deserialization for API endpoints.

System Design Concept:
    [[api-design]] - RESTful interface for metrics and alerts
"""

from rest_framework import serializers
from metrics.models import Metric, AlertRule, AlertInstance, AggregatedMetric
from datetime import datetime


class MetricSerializer(serializers.ModelSerializer):
    """
    Serializer for Metric model.

    Used for query results (read-only).
    """
    series_id = serializers.ReadOnlyField()

    class Meta:
        model = Metric
        fields = ['id', 'name', 'labels', 'timestamp', 'value', 'series_id', 'created_at']
        read_only_fields = ['id', 'created_at', 'series_id']


class MetricIngestSerializer(serializers.Serializer):
    """
    Serializer for metrics ingestion (write API).

    Validates incoming metric data from collection agents.
    """
    name = serializers.CharField(max_length=255)
    value = serializers.FloatField()
    labels = serializers.JSONField(default=dict, required=False)
    timestamp = serializers.DateTimeField(required=False)

    def validate_labels(self, value):
        """Validate labels is a dict with reasonable cardinality."""
        if not isinstance(value, dict):
            raise serializers.ValidationError("Labels must be a dictionary")

        if len(value) > 20:
            raise serializers.ValidationError("Too many labels (max 20)")

        return value

    def validate_name(self, value):
        """Validate metric name format."""
        if len(value) > 255:
            raise serializers.ValidationError("Metric name too long (max 255 chars)")

        return value


class MetricBatchIngestSerializer(serializers.Serializer):
    """
    Serializer for batch metrics ingestion.

    Accepts array of metrics for efficient bulk insertion.
    """
    metrics = MetricIngestSerializer(many=True)

    def validate_metrics(self, value):
        """Validate batch size."""
        if len(value) > 1000:
            raise serializers.ValidationError("Batch too large (max 1000 metrics)")

        if len(value) == 0:
            raise serializers.ValidationError("Batch cannot be empty")

        return value


class AlertRuleSerializer(serializers.ModelSerializer):
    """
    Serializer for AlertRule model.

    Used for CRUD operations on alert rules.
    """
    class Meta:
        model = AlertRule
        fields = [
            'id', 'name', 'metric_name', 'condition', 'threshold',
            'duration_seconds', 'label_filters', 'severity',
            'notification_channels', 'webhook_url', 'email_recipients',
            'annotations', 'enabled', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_notification_channels(self, value):
        """Validate notification channels."""
        valid_channels = ['email', 'webhook', 'pagerduty']

        for channel in value:
            if channel not in valid_channels:
                raise serializers.ValidationError(
                    f"Invalid channel '{channel}'. Must be one of: {valid_channels}"
                )

        return value

    def validate(self, data):
        """Cross-field validation."""
        # If email channel enabled, require recipients
        if 'email' in data.get('notification_channels', []):
            if not data.get('email_recipients'):
                raise serializers.ValidationError(
                    "email_recipients required when email channel is enabled"
                )

        # If webhook channel enabled, require URL
        if 'webhook' in data.get('notification_channels', []):
            if not data.get('webhook_url'):
                raise serializers.ValidationError(
                    "webhook_url required when webhook channel is enabled"
                )

        return data


class AlertInstanceSerializer(serializers.ModelSerializer):
    """
    Serializer for AlertInstance model.

    Used for querying alert state and history.
    """
    rule_name = serializers.CharField(source='rule.name', read_only=True)
    metric_name = serializers.CharField(source='rule.metric_name', read_only=True)
    severity = serializers.CharField(source='rule.severity', read_only=True)

    class Meta:
        model = AlertInstance
        fields = [
            'id', 'rule', 'rule_name', 'metric_name', 'severity',
            'fingerprint', 'state', 'pending_since', 'firing_since',
            'resolved_at', 'current_value', 'labels',
            'notifications_sent', 'last_notification_at',
            'notification_errors', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'fingerprint', 'rule_name', 'metric_name', 'severity',
            'created_at', 'updated_at'
        ]


class QueryRequestSerializer(serializers.Serializer):
    """
    Serializer for time-series query requests.

    Validates query parameters for GET /api/v1/query endpoint.
    """
    metric_name = serializers.CharField(max_length=255)
    start_time = serializers.DateTimeField(required=False)
    end_time = serializers.DateTimeField(required=False)
    labels = serializers.JSONField(default=dict, required=False)
    aggregation = serializers.ChoiceField(
        choices=['avg', 'max', 'min', 'sum', 'count'],
        required=False
    )
    group_by = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )

    def validate(self, data):
        """Validate time range."""
        start_time = data.get('start_time')
        end_time = data.get('end_time')

        if start_time and end_time:
            if start_time >= end_time:
                raise serializers.ValidationError(
                    "start_time must be before end_time"
                )

        return data


class QueryResponseSerializer(serializers.Serializer):
    """
    Serializer for query response data.

    Formats query results for API response.
    """
    timestamp = serializers.CharField(required=False)
    value = serializers.FloatField()
    labels = serializers.JSONField(default=dict)
    count = serializers.IntegerField(required=False)


class AggregatedMetricSerializer(serializers.ModelSerializer):
    """
    Serializer for AggregatedMetric model.

    Used for querying downsampled data.
    """
    class Meta:
        model = AggregatedMetric
        fields = [
            'id', 'name', 'labels', 'timestamp', 'resolution',
            'avg_value', 'max_value', 'min_value', 'sum_value',
            'count', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class MetricNamesSerializer(serializers.Serializer):
    """
    Serializer for list of metric names.

    Response for GET /api/v1/metrics/names
    """
    metric_names = serializers.ListField(child=serializers.CharField())


class LabelValuesSerializer(serializers.Serializer):
    """
    Serializer for label values response.

    Response for GET /api/v1/metrics/labels/<key>/values
    """
    label_key = serializers.CharField()
    values = serializers.ListField(child=serializers.CharField())


class AlertTestSerializer(serializers.Serializer):
    """
    Serializer for testing alert rules.

    Request for POST /api/v1/alerts/test
    """
    metric_name = serializers.CharField()
    condition = serializers.ChoiceField(choices=['>', '>=', '<', '<=', '==', '!='])
    threshold = serializers.FloatField()
    current_value = serializers.FloatField()

    def validate(self, data):
        """Evaluate test condition and return result."""
        ops = {
            '>': lambda a, b: a > b,
            '>=': lambda a, b: a >= b,
            '<': lambda a, b: a < b,
            '<=': lambda a, b: a <= b,
            '==': lambda a, b: a == b,
            '!=': lambda a, b: a != b,
        }

        would_fire = ops[data['condition']](
            data['current_value'],
            data['threshold']
        )

        data['would_fire'] = would_fire
        return data


class QueueStatsSerializer(serializers.Serializer):
    """
    Serializer for queue statistics.

    Response for GET /api/v1/stats/queue
    """
    partitions = serializers.IntegerField()
    total_events = serializers.IntegerField()
    unconsumed_events = serializers.IntegerField()
    partition_details = serializers.ListField()


class SystemStatsSerializer(serializers.Serializer):
    """
    Serializer for system-wide statistics.

    Response for GET /api/v1/stats/system
    """
    total_metrics = serializers.IntegerField()
    total_alerts = serializers.IntegerField()
    active_alerts = serializers.IntegerField()
    metric_names_count = serializers.IntegerField()
    time_range_start = serializers.DateTimeField()
    time_range_end = serializers.DateTimeField()
