"""
Time-series storage abstraction layer.

System Design Concept:
    [[time-series-database]] - Optimized storage for temporal data

Simulates:
    InfluxDB write/query API, Prometheus storage layer

At Scale:
    - Write-Ahead Log (WAL) for durability
    - In-memory cache for hot data (last 26 hours)
    - Time-Structured Merge Tree (TSM) storage engine
    - Automatic data compression (delta-of-delta encoding)
"""

from django.db.models import Avg, Max, Min, Sum, Count, Q
from django.utils import timezone
from metrics.models import Metric, AggregatedMetric
from metrics.storage.cache import QueryResultCache
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class TimeSeriesStorage:
    """
    Time-series storage layer with caching.

    Provides high-level API for writing and querying metrics data.

    Features:
        - Batch writes for efficiency
        - Query result caching
        - Label-based filtering
        - Aggregation functions (avg, max, min, sum, count)
        - Time-range queries

    Usage:
        storage = TimeSeriesStorage()

        # Write metrics
        storage.write_batch([
            {'name': 'cpu.load', 'labels': {'host': 'web-01'}, 'value': 0.75},
            {'name': 'cpu.load', 'labels': {'host': 'web-02'}, 'value': 0.82},
        ])

        # Query metrics
        results = storage.query(
            metric_name='cpu.load',
            start_time=datetime.now() - timedelta(hours=1),
            labels={'host': 'web-01'},
            aggregation='avg'
        )
    """

    def __init__(self, enable_cache: bool = True):
        """
        Initialize storage layer.

        Args:
            enable_cache: Whether to use query result caching
        """
        self.cache = QueryResultCache() if enable_cache else None
        logger.info(f"TimeSeriesStorage initialized (cache={'enabled' if enable_cache else 'disabled'})")

    def write(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None,
        timestamp: Optional[datetime] = None
    ) -> Metric:
        """
        Write a single metric data point.

        Args:
            name: Metric name (e.g., 'cpu.load')
            value: Metric value
            labels: Optional labels/tags
            timestamp: Optional timestamp (defaults to now)

        Returns:
            Created Metric instance
        """
        metric = Metric.objects.create(
            name=name,
            value=value,
            labels=labels or {},
            timestamp=timestamp or timezone.now()
        )

        logger.debug(f"Wrote metric: {name} = {value}")
        return metric

    def write_batch(self, metrics: List[Dict[str, Any]]) -> int:
        """
        Write multiple metrics efficiently.

        Args:
            metrics: List of metric data:
                [
                    {
                        'name': 'cpu.load',
                        'value': 0.75,
                        'labels': {'host': 'web-01'},
                        'timestamp': datetime(...)  # optional
                    },
                    ...
                ]

        Returns:
            Number of metrics written
        """
        now = timezone.now()

        metric_objects = [
            Metric(
                name=m['name'],
                value=m['value'],
                labels=m.get('labels', {}),
                timestamp=m.get('timestamp', now)
            )
            for m in metrics
        ]

        # Bulk create for efficiency
        Metric.objects.bulk_create(metric_objects)

        logger.info(f"Batch wrote {len(metric_objects)} metrics")
        return len(metric_objects)

    def query(
        self,
        metric_name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        labels: Optional[Dict[str, str]] = None,
        aggregation: Optional[str] = None,
        group_by: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Query time-series data with optional aggregation.

        Args:
            metric_name: Metric to query
            start_time: Start of time range (inclusive)
            end_time: End of time range (exclusive)
            labels: Filter by label values (exact match)
            aggregation: Aggregation function: 'avg', 'max', 'min', 'sum', 'count'
            group_by: List of label keys to group by

        Returns:
            List of data points:
                Without aggregation:
                    [{'timestamp': ..., 'value': ..., 'labels': {...}}, ...]
                With aggregation:
                    [{'labels': {...}, 'value': ..., 'count': ...}, ...]

        Example:
            # Raw data points
            storage.query(
                metric_name='cpu.load',
                start_time=datetime.now() - timedelta(hours=1),
                labels={'host': 'web-01'}
            )

            # Aggregated by host
            storage.query(
                metric_name='cpu.load',
                start_time=datetime.now() - timedelta(hours=1),
                aggregation='avg',
                group_by=['host']
            )
        """
        # Use cache if enabled
        if self.cache:
            return self.cache.cache_query_result(
                metric_name=metric_name,
                start_time=start_time or datetime.min,
                end_time=end_time or timezone.now(),
                labels=labels or {},
                aggregation=aggregation or 'none',
                fetch_fn=lambda: self._execute_query(
                    metric_name, start_time, end_time, labels, aggregation, group_by
                )
            )
        else:
            return self._execute_query(
                metric_name, start_time, end_time, labels, aggregation, group_by
            )

    def _execute_query(
        self,
        metric_name: str,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        labels: Optional[Dict[str, str]],
        aggregation: Optional[str],
        group_by: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        """Internal query execution (called on cache miss)."""
        # Build base query
        queryset = Metric.objects.filter(name=metric_name)

        # Apply time range filters
        if start_time:
            queryset = queryset.filter(timestamp__gte=start_time)
        if end_time:
            queryset = queryset.filter(timestamp__lt=end_time)

        # Apply label filters
        if labels:
            for key, value in labels.items():
                # PostgreSQL JSONB query
                queryset = queryset.filter(**{f'labels__{key}': value})

        # Execute aggregation or return raw data
        if aggregation:
            return self._aggregate_query(queryset, aggregation, group_by)
        else:
            return self._raw_query(queryset)

    def _raw_query(self, queryset) -> List[Dict[str, Any]]:
        """Return raw data points without aggregation."""
        results = []

        for metric in queryset.order_by('timestamp'):
            results.append({
                'timestamp': metric.timestamp.isoformat(),
                'value': metric.value,
                'labels': metric.labels
            })

        logger.debug(f"Raw query returned {len(results)} data points")
        return results

    def _aggregate_query(
        self,
        queryset,
        aggregation: str,
        group_by: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        """
        Execute aggregation query.

        Note: Grouping by JSONB fields is complex in Django ORM.
        For production, this would be better handled by the TSDB itself.
        """
        agg_functions = {
            'avg': Avg('value'),
            'max': Max('value'),
            'min': Min('value'),
            'sum': Sum('value'),
            'count': Count('id')
        }

        if aggregation not in agg_functions:
            raise ValueError(f"Invalid aggregation: {aggregation}. Must be one of {list(agg_functions.keys())}")

        # Simplified aggregation without group_by
        # In production TSDB, group_by would be efficiently handled
        if not group_by:
            result = queryset.aggregate(
                value=agg_functions[aggregation],
                count=Count('id')
            )

            logger.debug(f"Aggregation query: {aggregation} = {result['value']}")

            return [{
                'labels': {},
                'value': result['value'],
                'count': result['count']
            }]

        # Group by is complex with JSONB - simplified implementation
        # In real TSDB, this would be optimized
        else:
            logger.warning("group_by is simplified in this implementation")

            # Collect all unique label combinations
            results_by_labels = {}

            for metric in queryset:
                # Extract group_by labels
                group_labels = {
                    k: metric.labels.get(k)
                    for k in group_by
                    if k in metric.labels
                }

                # Use sorted JSON as key
                import json
                key = json.dumps(group_labels, sort_keys=True)

                if key not in results_by_labels:
                    results_by_labels[key] = {
                        'labels': group_labels,
                        'values': [],
                    }

                results_by_labels[key]['values'].append(metric.value)

            # Compute aggregations
            results = []
            for group_data in results_by_labels.values():
                values = group_data['values']

                if aggregation == 'avg':
                    agg_value = sum(values) / len(values)
                elif aggregation == 'max':
                    agg_value = max(values)
                elif aggregation == 'min':
                    agg_value = min(values)
                elif aggregation == 'sum':
                    agg_value = sum(values)
                elif aggregation == 'count':
                    agg_value = len(values)
                else:
                    agg_value = None

                results.append({
                    'labels': group_data['labels'],
                    'value': agg_value,
                    'count': len(values)
                })

            logger.debug(f"Grouped aggregation returned {len(results)} groups")
            return results

    def get_metric_names(self) -> List[str]:
        """Get list of all distinct metric names."""
        names = Metric.objects.values_list('name', flat=True).distinct()
        return list(names)

    def get_label_keys(self, metric_name: Optional[str] = None) -> List[str]:
        """
        Get all label keys for a metric (or all metrics).

        Note: This is expensive with JSONB. In production TSDB,
        label keys/values are indexed separately.
        """
        queryset = Metric.objects.all()

        if metric_name:
            queryset = queryset.filter(name=metric_name)

        # Extract all unique keys from JSONB labels
        all_keys = set()
        for metric in queryset[:1000]:  # Limit for performance
            all_keys.update(metric.labels.keys())

        return sorted(all_keys)

    def get_label_values(
        self,
        metric_name: str,
        label_key: str
    ) -> List[str]:
        """
        Get all values for a specific label key.

        Example:
            storage.get_label_values('cpu.load', 'host')
            # Returns: ['web-01', 'web-02', 'db-01', ...]
        """
        metrics = Metric.objects.filter(name=metric_name)

        values = set()
        for metric in metrics[:1000]:  # Limit for performance
            if label_key in metric.labels:
                values.add(metric.labels[label_key])

        return sorted(values)

    def delete_old_data(self, older_than: datetime) -> int:
        """
        Delete metrics older than specified time.

        Part of data retention strategy.

        Args:
            older_than: Delete metrics with timestamp < this

        Returns:
            Number of metrics deleted
        """
        deleted_count, _ = Metric.objects.filter(
            timestamp__lt=older_than
        ).delete()

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} old metrics (older than {older_than})")

        return deleted_count
