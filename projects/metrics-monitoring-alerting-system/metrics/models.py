"""
Django ORM models for Metrics Monitoring and Alerting System.

These models simulate a time-series database and alert management system.
In production, metrics would be stored in InfluxDB/Prometheus, but we use
Django ORM to demonstrate the data model and query patterns.

System Design Concepts:
    - [[time-series-database]]: Optimized storage for temporal data
    - [[alert-state-machine]]: Alert lifecycle management
    - [[message-queue]]: Kafka-style event buffering
"""

from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from datetime import timedelta
import hashlib
import json


class Metric(models.Model):
    """
    Time-series data point representing a single metric observation.

    Simulates:
        InfluxDB measurement or Prometheus time series

    At Scale:
        - Would use columnar storage (Parquet/ORC)
        - Delta-of-delta compression for timestamps
        - Sharding by (metric_name, time_range)
        - In-memory cache for hot data (last 26 hours)

    Query Patterns:
        - Range scan by (name, timestamp)
        - Filter by labels (JSONB index)
        - Aggregations (avg, max, min, count)
    """

    name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Metric name (e.g., 'cpu.load', 'http.requests')"
    )

    labels = models.JSONField(
        default=dict,
        help_text="Key-value tags for filtering (e.g., {'host': 'web-01', 'region': 'us-west'})"
    )

    timestamp = models.DateTimeField(
        db_index=True,
        help_text="When the metric was observed (UTC)"
    )

    value = models.FloatField(
        help_text="Metric value (gauge, counter, histogram)"
    )

    # Metadata
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this record was inserted into DB"
    )

    class Meta:
        indexes = [
            # Composite index for common query: filter by name + time range
            models.Index(fields=['name', 'timestamp'], name='metric_name_time_idx'),
            # Reverse for descending time queries
            models.Index(fields=['name', '-timestamp'], name='metric_name_time_desc_idx'),
            # Time-only for global time range queries
            models.Index(fields=['timestamp'], name='metric_timestamp_idx'),
        ]
        ordering = ['-timestamp']  # Most recent first
        verbose_name = "Metric"
        verbose_name_plural = "Metrics"

    def __str__(self):
        labels_str = ','.join(f"{k}={v}" for k, v in self.labels.items())
        return f"{self.name}{{{labels_str}}} = {self.value} @ {self.timestamp}"

    @property
    def series_id(self):
        """
        Unique identifier for this time series (name + labels).
        Used for grouping related data points.
        """
        labels_sorted = json.dumps(self.labels, sort_keys=True)
        series_str = f"{self.name}::{labels_sorted}"
        return hashlib.md5(series_str.encode()).hexdigest()


class MetricEvent(models.Model):
    """
    Message queue event buffer (simulates Kafka).

    Decouples metrics collection from storage, providing:
    - Buffering during database outages
    - Ordered processing within partitions
    - At-least-once delivery guarantees

    Simulates:
        Apache Kafka partition + offset

    Simplifications:
        - Single broker (Django DB)
        - No replication
        - Simplified consumer group coordination

    At Scale:
        - Multi-node Kafka cluster
        - Replication factor = 3
        - Configurable retention (hours to days)
    """

    partition = models.IntegerField(
        db_index=True,
        help_text="Partition number (based on metric name hash)"
    )

    offset = models.BigIntegerField(
        db_index=True,
        help_text="Sequential offset within partition"
    )

    metric_name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Metric name for routing/filtering"
    )

    payload = models.JSONField(
        help_text="Full metric data: {name, labels, timestamp, value}"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="Event creation time"
    )

    consumed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this event has been processed"
    )

    consumed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this event was consumed"
    )

    class Meta:
        indexes = [
            # Consumer reads: partition + offset ordering
            models.Index(fields=['partition', 'offset'], name='event_partition_offset_idx'),
            # Cleanup job: find old consumed events
            models.Index(fields=['consumed', 'created_at'], name='event_consumed_created_idx'),
        ]
        ordering = ['partition', 'offset']
        unique_together = [['partition', 'offset']]
        verbose_name = "Metric Event"
        verbose_name_plural = "Metric Events"

    def __str__(self):
        status = "consumed" if self.consumed else "pending"
        return f"Partition {self.partition}, Offset {self.offset} [{status}]"


class AlertRule(models.Model):
    """
    Configuration for alert conditions and notification settings.

    Loaded from YAML but persisted in DB for runtime modification.

    Simulates:
        Prometheus alert rule

    Example YAML:
        - alert: HighCPUUsage
          expr: cpu.load > 0.8
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "High CPU on {{ host }}"
    """

    CONDITION_CHOICES = [
        ('>', 'Greater Than'),
        ('>=', 'Greater Than or Equal'),
        ('<', 'Less Than'),
        ('<=', 'Less Than or Equal'),
        ('==', 'Equal'),
        ('!=', 'Not Equal'),
    ]

    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('critical', 'Critical'),
    ]

    name = models.CharField(
        max_length=255,
        unique=True,
        help_text="Alert rule name (e.g., 'high_cpu_usage')"
    )

    metric_name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Metric to monitor (e.g., 'cpu.load')"
    )

    condition = models.CharField(
        max_length=2,
        choices=CONDITION_CHOICES,
        help_text="Comparison operator"
    )

    threshold = models.FloatField(
        help_text="Threshold value to compare against"
    )

    duration_seconds = models.IntegerField(
        default=300,  # 5 minutes
        validators=[MinValueValidator(0)],
        help_text="How long condition must be true before firing (seconds)"
    )

    label_filters = models.JSONField(
        default=dict,
        blank=True,
        help_text="Filter metrics by labels (e.g., {'region': 'us-west'})"
    )

    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default='warning',
        help_text="Alert severity level"
    )

    # Notification settings
    notification_channels = models.JSONField(
        default=list,
        help_text="List of channels: ['email', 'webhook', 'pagerduty']"
    )

    webhook_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="Webhook endpoint for notifications"
    )

    email_recipients = models.JSONField(
        default=list,
        blank=True,
        help_text="List of email addresses"
    )

    # Rule metadata
    annotations = models.JSONField(
        default=dict,
        blank=True,
        help_text="Template variables for notification messages"
    )

    enabled = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this rule is active"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['severity', 'name']
        verbose_name = "Alert Rule"
        verbose_name_plural = "Alert Rules"

    def __str__(self):
        return f"{self.name} ({self.severity}): {self.metric_name} {self.condition} {self.threshold}"

    def check_condition(self, value: float) -> bool:
        """Evaluate if value meets the alert condition."""
        ops = {
            '>': lambda a, b: a > b,
            '>=': lambda a, b: a >= b,
            '<': lambda a, b: a < b,
            '<=': lambda a, b: a <= b,
            '==': lambda a, b: a == b,
            '!=': lambda a, b: a != b,
        }
        return ops[self.condition](value, self.threshold)


class AlertInstance(models.Model):
    """
    A specific firing of an alert rule with state tracking.

    Implements alert state machine:
        inactive → pending → firing → resolved

    State Transitions:
        - inactive → pending: Condition becomes true
        - pending → firing: Condition true for duration threshold
        - pending → inactive: Condition becomes false
        - firing → resolved: Condition becomes false
        - resolved → inactive: Cleanup after resolution window

    Simulates:
        Prometheus Alertmanager alert instance

    At Scale:
        - State stored in fast key-value store (Redis)
        - Sharded by alert fingerprint
        - Distributed state consistency via consensus
    """

    STATE_CHOICES = [
        ('inactive', 'Inactive'),
        ('pending', 'Pending'),
        ('firing', 'Firing'),
        ('resolved', 'Resolved'),
    ]

    rule = models.ForeignKey(
        AlertRule,
        on_delete=models.CASCADE,
        related_name='instances',
        help_text="The rule that generated this alert"
    )

    fingerprint = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Hash of rule + label values for deduplication"
    )

    state = models.CharField(
        max_length=20,
        choices=STATE_CHOICES,
        default='inactive',
        db_index=True,
        help_text="Current alert state"
    )

    # State timestamps
    pending_since = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When condition first became true"
    )

    firing_since = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When alert started firing (duration threshold met)"
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When condition became false"
    )

    # Current metric values
    current_value = models.FloatField(
        help_text="Latest metric value that triggered/maintains this alert"
    )

    labels = models.JSONField(
        default=dict,
        help_text="Actual label values from metrics"
    )

    # Notification tracking
    notifications_sent = models.IntegerField(
        default=0,
        help_text="Count of notifications sent for this alert"
    )

    last_notification_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When last notification was sent"
    )

    notification_errors = models.IntegerField(
        default=0,
        help_text="Count of failed notification attempts"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # Find firing alerts for notifications
            models.Index(fields=['state', 'firing_since'], name='alert_state_firing_idx'),
            # Deduplication lookup
            models.Index(fields=['fingerprint', 'state'], name='alert_fingerprint_state_idx'),
            # Cleanup old resolved alerts
            models.Index(fields=['state', 'resolved_at'], name='alert_state_resolved_idx'),
        ]
        ordering = ['-firing_since', '-updated_at']
        unique_together = [['rule', 'fingerprint']]
        verbose_name = "Alert Instance"
        verbose_name_plural = "Alert Instances"

    def __str__(self):
        labels_str = ','.join(f"{k}={v}" for k, v in self.labels.items())
        return f"{self.rule.name} [{self.state}] {labels_str}"

    @staticmethod
    def generate_fingerprint(rule_id: int, labels: dict) -> str:
        """
        Generate unique fingerprint for alert deduplication.

        Same rule + same labels = same alert instance
        (prevents duplicate notifications)
        """
        labels_sorted = json.dumps(labels, sort_keys=True)
        fingerprint_str = f"{rule_id}::{labels_sorted}"
        return hashlib.md5(fingerprint_str.encode()).hexdigest()

    def should_fire(self) -> bool:
        """Check if alert should transition from pending to firing."""
        if self.state != 'pending' or not self.pending_since:
            return False

        duration_met = (
            timezone.now() - self.pending_since
        ).total_seconds() >= self.rule.duration_seconds

        return duration_met

    def transition_to_pending(self, value: float):
        """Transition from inactive to pending."""
        self.state = 'pending'
        self.pending_since = timezone.now()
        self.current_value = value
        self.save()

    def transition_to_firing(self):
        """Transition from pending to firing."""
        self.state = 'firing'
        self.firing_since = timezone.now()
        self.resolved_at = None
        self.save()

    def transition_to_resolved(self):
        """Transition from firing to resolved."""
        self.state = 'resolved'
        self.resolved_at = timezone.now()
        self.save()

    def transition_to_inactive(self):
        """Transition from pending/resolved to inactive."""
        self.state = 'inactive'
        self.pending_since = None
        self.firing_since = None
        self.save()


class AggregatedMetric(models.Model):
    """
    Downsampled/rolled-up metrics for long-term storage.

    Data Retention Strategy:
        - 0-7 days: Raw data (Metric model)
        - 7-30 days: 1-minute resolution (this model)
        - 30-365 days: 1-hour resolution (this model)

    Simulates:
        InfluxDB continuous queries or Prometheus recording rules

    At Scale:
        - Scheduled jobs (cron) for rollup computation
        - Delete raw data after rollup
        - Store in cheaper cold storage (S3)
    """

    RESOLUTION_CHOICES = [
        ('1m', '1 Minute'),
        ('1h', '1 Hour'),
        ('1d', '1 Day'),
    ]

    name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Metric name"
    )

    labels = models.JSONField(
        default=dict,
        help_text="Label key-value pairs"
    )

    timestamp = models.DateTimeField(
        db_index=True,
        help_text="Bucket start time"
    )

    resolution = models.CharField(
        max_length=2,
        choices=RESOLUTION_CHOICES,
        help_text="Aggregation window size"
    )

    # Aggregated values
    avg_value = models.FloatField(null=True, help_text="Average in window")
    max_value = models.FloatField(null=True, help_text="Maximum in window")
    min_value = models.FloatField(null=True, help_text="Minimum in window")
    sum_value = models.FloatField(null=True, help_text="Sum in window")
    count = models.IntegerField(help_text="Number of data points")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['name', 'resolution', 'timestamp'], name='agg_name_res_time_idx'),
        ]
        ordering = ['-timestamp']
        unique_together = [['name', 'labels', 'timestamp', 'resolution']]
        verbose_name = "Aggregated Metric"
        verbose_name_plural = "Aggregated Metrics"

    def __str__(self):
        return f"{self.name} [{self.resolution}] avg={self.avg_value} @ {self.timestamp}"
