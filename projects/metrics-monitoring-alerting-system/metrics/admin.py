"""
Django Admin Interface Configuration

Registers models for debugging and manual management via admin panel.

Access at: http://localhost:8000/admin
"""

from django.contrib import admin
from metrics.models import Metric, MetricEvent, AlertRule, AlertInstance, AggregatedMetric


@admin.register(Metric)
class MetricAdmin(admin.ModelAdmin):
    """Admin interface for Metric model."""

    list_display = ['name', 'value', 'timestamp', 'created_at', 'label_preview']
    list_filter = ['name', 'timestamp']
    search_fields = ['name']
    ordering = ['-timestamp']
    date_hierarchy = 'timestamp'

    readonly_fields = ['created_at', 'series_id']

    fieldsets = (
        ('Metric Data', {
            'fields': ('name', 'value', 'timestamp', 'labels')
        }),
        ('Metadata', {
            'fields': ('series_id', 'created_at'),
            'classes': ('collapse',)
        }),
    )

    def label_preview(self, obj):
        """Show labels in list view."""
        if not obj.labels:
            return '-'
        items = [f"{k}={v}" for k, v in list(obj.labels.items())[:3]]
        return ', '.join(items)
    label_preview.short_description = 'Labels'


@admin.register(MetricEvent)
class MetricEventAdmin(admin.ModelAdmin):
    """Admin interface for MetricEvent model (Kafka simulation)."""

    list_display = ['partition', 'offset', 'metric_name', 'consumed', 'created_at']
    list_filter = ['partition', 'consumed', 'metric_name']
    search_fields = ['metric_name']
    ordering = ['partition', 'offset']

    readonly_fields = ['created_at', 'consumed_at']

    fieldsets = (
        ('Queue Position', {
            'fields': ('partition', 'offset', 'metric_name')
        }),
        ('Payload', {
            'fields': ('payload',)
        }),
        ('Consumption', {
            'fields': ('consumed', 'consumed_at', 'created_at')
        }),
    )

    actions = ['mark_consumed', 'mark_unconsumed']

    def mark_consumed(self, request, queryset):
        """Mark selected events as consumed."""
        from django.utils import timezone
        updated = queryset.update(consumed=True, consumed_at=timezone.now())
        self.message_user(request, f"{updated} events marked as consumed")
    mark_consumed.short_description = "Mark selected events as consumed"

    def mark_unconsumed(self, request, queryset):
        """Mark selected events as unconsumed."""
        updated = queryset.update(consumed=False, consumed_at=None)
        self.message_user(request, f"{updated} events marked as unconsumed")
    mark_unconsumed.short_description = "Mark selected events as unconsumed"


@admin.register(AlertRule)
class AlertRuleAdmin(admin.ModelAdmin):
    """Admin interface for AlertRule model."""

    list_display = [
        'name', 'metric_name', 'condition_display',
        'severity', 'enabled', 'created_at'
    ]
    list_filter = ['severity', 'enabled', 'condition']
    search_fields = ['name', 'metric_name']
    ordering = ['severity', 'name']

    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'enabled', 'severity')
        }),
        ('Condition', {
            'fields': (
                'metric_name', 'condition', 'threshold',
                'duration_seconds', 'label_filters'
            )
        }),
        ('Notifications', {
            'fields': (
                'notification_channels',
                'email_recipients', 'webhook_url'
            )
        }),
        ('Metadata', {
            'fields': ('annotations', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['enable_rules', 'disable_rules']

    def condition_display(self, obj):
        """Show condition in readable format."""
        return f"{obj.metric_name} {obj.condition} {obj.threshold}"
    condition_display.short_description = 'Condition'

    def enable_rules(self, request, queryset):
        """Enable selected rules."""
        updated = queryset.update(enabled=True)
        self.message_user(request, f"{updated} rules enabled")
    enable_rules.short_description = "Enable selected rules"

    def disable_rules(self, request, queryset):
        """Disable selected rules."""
        updated = queryset.update(enabled=False)
        self.message_user(request, f"{updated} rules disabled")
    disable_rules.short_description = "Disable selected rules"


@admin.register(AlertInstance)
class AlertInstanceAdmin(admin.ModelAdmin):
    """Admin interface for AlertInstance model."""

    list_display = [
        'rule', 'state', 'current_value',
        'firing_since', 'notifications_sent', 'updated_at'
    ]
    list_filter = ['state', 'rule__severity']
    search_fields = ['rule__name', 'fingerprint']
    ordering = ['-updated_at']
    date_hierarchy = 'updated_at'

    readonly_fields = [
        'fingerprint', 'created_at', 'updated_at',
        'pending_since', 'firing_since', 'resolved_at'
    ]

    fieldsets = (
        ('Alert Info', {
            'fields': ('rule', 'state', 'fingerprint')
        }),
        ('Current State', {
            'fields': ('current_value', 'labels')
        }),
        ('State Timestamps', {
            'fields': (
                'pending_since', 'firing_since', 'resolved_at'
            ),
            'classes': ('collapse',)
        }),
        ('Notifications', {
            'fields': (
                'notifications_sent', 'last_notification_at',
                'notification_errors'
            )
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['resolve_alerts']

    def resolve_alerts(self, request, queryset):
        """Manually resolve selected alerts."""
        resolved = 0
        for alert in queryset.filter(state='firing'):
            alert.transition_to_resolved()
            resolved += 1
        self.message_user(request, f"{resolved} alerts resolved")
    resolve_alerts.short_description = "Resolve selected firing alerts"


@admin.register(AggregatedMetric)
class AggregatedMetricAdmin(admin.ModelAdmin):
    """Admin interface for AggregatedMetric model."""

    list_display = [
        'name', 'resolution', 'timestamp',
        'avg_value', 'max_value', 'min_value', 'count'
    ]
    list_filter = ['resolution', 'name']
    search_fields = ['name']
    ordering = ['-timestamp']
    date_hierarchy = 'timestamp'

    readonly_fields = ['created_at']

    fieldsets = (
        ('Metric Info', {
            'fields': ('name', 'resolution', 'timestamp', 'labels')
        }),
        ('Aggregated Values', {
            'fields': (
                'avg_value', 'max_value', 'min_value',
                'sum_value', 'count'
            )
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


# Customize admin site headers
admin.site.site_header = "Metrics Monitoring & Alerting System"
admin.site.site_title = "Metrics Admin"
admin.site.index_title = "System Administration"
