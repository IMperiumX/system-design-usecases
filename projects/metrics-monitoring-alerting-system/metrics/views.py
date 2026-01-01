"""
Django REST Framework API Views

Provides REST API endpoints for metrics monitoring system.

System Design Concept:
    [[rest-api-design]] - RESTful interface for client access
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count, Max, Min
from django.utils import timezone

from metrics.models import Metric, AlertRule, AlertInstance
from metrics.serializers import (
    MetricSerializer, MetricIngestSerializer, MetricBatchIngestSerializer,
    AlertRuleSerializer, AlertInstanceSerializer,
    QueryRequestSerializer, QueryResponseSerializer,
    MetricNamesSerializer, LabelValuesSerializer, AlertTestSerializer,
    QueueStatsSerializer, SystemStatsSerializer
)
from metrics.services.metrics_collector import MetricsCollector
from metrics.services.query_service import QueryService
from metrics.services.alert_manager import AlertManager
from metrics.services.notification_service import NotificationService
from metrics.services.metrics_consumer import ConsumerPool

import logging

logger = logging.getLogger(__name__)


class MetricsIngestView(APIView):
    """
    Metrics ingestion endpoint (push model).

    POST /api/v1/metrics
        - Accept single or batch metrics from collection agents
        - Validate and enqueue to message queue
        - Return 202 Accepted (fire-and-forget)

    System Design Concept:
        [[push-model]] - Agents push metrics to collectors
    """

    def post(self, request):
        """
        Ingest metrics (single or batch).

        Request body:
            Single metric:
                {
                    "name": "cpu.load",
                    "value": 0.75,
                    "labels": {"host": "web-01"},
                    "timestamp": "2024-01-01T00:00:00Z"  # optional
                }

            Batch:
                {
                    "metrics": [
                        {"name": "cpu.load", "value": 0.75, ...},
                        {"name": "memory.used", "value": 65.2, ...}
                    ]
                }
        """
        # Check if batch request
        if 'metrics' in request.data:
            serializer = MetricBatchIngestSerializer(data=request.data)
        else:
            # Single metric - wrap in batch format
            serializer = MetricBatchIngestSerializer(
                data={'metrics': [request.data]}
            )

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        # Enqueue metrics
        collector = MetricsCollector()
        metrics_data = serializer.validated_data['metrics']

        result = collector.collect_batch(metrics_data)

        logger.info(
            f"Ingested {result['accepted']} metrics "
            f"({result['rejected']} rejected)"
        )

        return Response(
            {
                'status': 'accepted',
                'accepted': result['accepted'],
                'rejected': result['rejected'],
                'errors': result['errors']
            },
            status=status.HTTP_202_ACCEPTED
        )


class QueryView(APIView):
    """
    Time-series query endpoint.

    GET /api/v1/query
        - Query metrics by name, time range, labels
        - Support aggregations (avg, max, min, sum, count)
        - Results cached for performance

    Query parameters:
        - metric_name: required
        - start_time: ISO timestamp (default: 1 hour ago)
        - end_time: ISO timestamp (default: now)
        - labels: JSON dict (e.g., {"host": "web-01"})
        - aggregation: avg|max|min|sum|count
        - group_by: comma-separated label keys
    """

    def get(self, request):
        """Execute time-series query."""
        # Parse query parameters
        query_params = {
            'metric_name': request.query_params.get('metric_name'),
            'start_time': request.query_params.get('start_time'),
            'end_time': request.query_params.get('end_time'),
            'labels': request.query_params.get('labels', '{}'),
            'aggregation': request.query_params.get('aggregation'),
            'group_by': request.query_params.get('group_by', '').split(',') if request.query_params.get('group_by') else None
        }

        # Parse JSON labels
        import json
        try:
            query_params['labels'] = json.loads(query_params['labels'])
        except json.JSONDecodeError:
            return Response(
                {'error': 'Invalid JSON in labels parameter'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate request
        serializer = QueryRequestSerializer(data=query_params)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        # Execute query
        qs = QueryService()

        try:
            results = qs.query(**serializer.validated_data)

            logger.info(
                f"Query executed: {query_params['metric_name']}, "
                f"returned {len(results)} results"
            )

            # Serialize response
            response_serializer = QueryResponseSerializer(results, many=True)

            return Response({
                'metric_name': query_params['metric_name'],
                'results': response_serializer.data
            })

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class MetricsMetadataView(APIView):
    """
    Metrics metadata endpoints.

    GET /api/v1/metrics/names
        - List all metric names

    GET /api/v1/metrics/<metric_name>/labels
        - List label keys for a metric

    GET /api/v1/metrics/<metric_name>/labels/<label_key>/values
        - List values for a label key
    """

    def get(self, request, metric_name=None, label_key=None):
        """Get metrics metadata."""
        qs = QueryService()

        # List all metric names
        if not metric_name:
            names = qs.list_metrics()
            serializer = MetricNamesSerializer({'metric_names': names})
            return Response(serializer.data)

        # List label keys for metric
        if not label_key:
            keys = qs.get_label_keys(metric_name)
            return Response({'metric_name': metric_name, 'label_keys': keys})

        # List values for label key
        values = qs.get_label_values(metric_name, label_key)
        serializer = LabelValuesSerializer({
            'label_key': label_key,
            'values': values
        })
        return Response(serializer.data)


class AlertRuleViewSet(viewsets.ModelViewSet):
    """
    Alert rules CRUD operations.

    GET /api/v1/alerts/rules
        - List all alert rules

    POST /api/v1/alerts/rules
        - Create new alert rule

    GET /api/v1/alerts/rules/<id>
        - Get specific rule

    PUT/PATCH /api/v1/alerts/rules/<id>
        - Update rule

    DELETE /api/v1/alerts/rules/<id>
        - Delete rule
    """

    queryset = AlertRule.objects.all()
    serializer_class = AlertRuleSerializer

    def perform_create(self, serializer):
        """Create alert rule."""
        rule = serializer.save()
        logger.info(f"Created alert rule: {rule.name}")

    def perform_update(self, serializer):
        """Update alert rule."""
        rule = serializer.save()
        logger.info(f"Updated alert rule: {rule.name}")

    def perform_destroy(self, instance):
        """Delete alert rule."""
        logger.info(f"Deleted alert rule: {instance.name}")
        instance.delete()

    @action(detail=False, methods=['post'])
    def test(self, request):
        """
        Test an alert condition.

        POST /api/v1/alerts/rules/test
            {
                "metric_name": "cpu.load",
                "condition": ">",
                "threshold": 0.8,
                "current_value": 0.85
            }

        Response:
            {
                "would_fire": true,
                "metric_name": "cpu.load",
                "condition": ">",
                "threshold": 0.8,
                "current_value": 0.85
            }
        """
        serializer = AlertTestSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(serializer.validated_data)


class AlertInstanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Alert instances (read-only).

    GET /api/v1/alerts/instances
        - List all alert instances

    GET /api/v1/alerts/instances?state=firing
        - Filter by state

    GET /api/v1/alerts/instances/<id>
        - Get specific instance
    """

    queryset = AlertInstance.objects.all().order_by('-updated_at')
    serializer_class = AlertInstanceSerializer

    def get_queryset(self):
        """Filter by state if provided."""
        queryset = super().get_queryset()

        state = self.request.query_params.get('state')
        if state:
            queryset = queryset.filter(state=state)

        return queryset

    @action(detail=False, methods=['get'])
    def active(self, request):
        """
        Get only firing alerts.

        GET /api/v1/alerts/instances/active
        """
        alerts = AlertInstance.objects.filter(state='firing')
        serializer = self.get_serializer(alerts, many=True)
        return Response(serializer.data)


class SystemOperationsView(APIView):
    """
    System operations and background tasks.

    POST /api/v1/ops/process-queue
        - Process metrics from queue (consumer)

    POST /api/v1/ops/evaluate-alerts
        - Evaluate all alert rules

    GET /api/v1/ops/stats
        - Get system statistics
    """

    def post(self, request, operation=None):
        """Execute system operations."""

        if operation == 'process-queue':
            # Process one batch from all partitions
            pool = ConsumerPool()
            stats = pool.process_all_once()

            logger.info(f"Processed queue: {stats['written']} metrics written")

            return Response({
                'status': 'completed',
                'fetched': stats['fetched'],
                'written': stats['written'],
                'errors': stats['errors']
            })

        elif operation == 'evaluate-alerts':
            # Evaluate all alert rules
            manager = AlertManager()
            stats = manager.evaluate_all_rules()

            logger.info(
                f"Evaluated alerts: {stats['alerts_triggered']} triggered, "
                f"{stats['alerts_resolved']} resolved"
            )

            return Response({
                'status': 'completed',
                'rules_evaluated': stats['rules_evaluated'],
                'alerts_triggered': stats['alerts_triggered'],
                'alerts_resolved': stats['alerts_resolved'],
                'errors': stats['errors']
            })

        else:
            return Response(
                {'error': f'Unknown operation: {operation}'},
                status=status.HTTP_400_BAD_REQUEST
            )


class StatsView(APIView):
    """
    System statistics and monitoring.

    GET /api/v1/stats/queue
        - Queue statistics (partitions, lag, etc.)

    GET /api/v1/stats/system
        - Overall system statistics
    """

    def get(self, request, stat_type=None):
        """Get statistics."""

        if stat_type == 'queue':
            # Get queue statistics
            collector = MetricsCollector()
            stats = collector.get_queue_stats()

            serializer = QueueStatsSerializer(stats)
            return Response(serializer.data)

        elif stat_type == 'system':
            # Get system-wide statistics
            stats = {
                'total_metrics': Metric.objects.count(),
                'total_alerts': AlertInstance.objects.count(),
                'active_alerts': AlertInstance.objects.filter(state='firing').count(),
                'metric_names_count': Metric.objects.values('name').distinct().count(),
                'time_range_start': Metric.objects.aggregate(Min('timestamp'))['timestamp__min'] or timezone.now(),
                'time_range_end': Metric.objects.aggregate(Max('timestamp'))['timestamp__max'] or timezone.now(),
            }

            serializer = SystemStatsSerializer(stats)
            return Response(serializer.data)

        else:
            return Response(
                {'error': f'Unknown stat type: {stat_type}'},
                status=status.HTTP_400_BAD_REQUEST
            )


class HealthCheckView(APIView):
    """
    Health check endpoint.

    GET /api/v1/health
        - Returns system health status
    """

    def get(self, request):
        """Check system health."""
        # Basic health checks
        try:
            # Check database connectivity
            Metric.objects.count()

            # Check cache (if Redis configured)
            from django.core.cache import cache
            cache.set('health_check', 'ok', 10)
            cache_ok = cache.get('health_check') == 'ok'

            return Response({
                'status': 'healthy',
                'timestamp': timezone.now().isoformat(),
                'database': 'ok',
                'cache': 'ok' if cache_ok else 'degraded'
            })

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return Response(
                {
                    'status': 'unhealthy',
                    'error': str(e)
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
