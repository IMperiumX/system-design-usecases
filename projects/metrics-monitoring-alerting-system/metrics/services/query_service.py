"""
Query Service

System Design Concept:
    [[query-optimization]] - Efficient time-series data retrieval

Simulates:
    PromQL query engine, InfluxDB Flux queries

At Scale:
    - Query result streaming for large datasets
    - Query plan optimization
    - Parallel execution across shards
    - Read replicas for scaling
"""

from metrics.storage.timeseries import TimeSeriesStorage
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class QueryService:
    """
    High-level query interface for metrics data.

    Wraps TimeSeriesStorage with additional features:
        - Query validation
        - Time-range helpers
        - Common query patterns
        - Statistics/metadata queries

    Usage:
        qs = QueryService()

        # Query with time range helper
        results = qs.query_last_hour(
            metric_name='cpu.load',
            labels={'host': 'web-01'},
            aggregation='avg'
        )

        # Get available metrics
        metrics = qs.list_metrics()

        # Get label values
        hosts = qs.get_label_values('cpu.load', 'host')
    """

    def __init__(self, storage: TimeSeriesStorage = None):
        """
        Initialize query service.

        Args:
            storage: TimeSeriesStorage instance
        """
        self.storage = storage or TimeSeriesStorage()
        logger.info("QueryService initialized")

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
        Execute time-series query.

        Args:
            metric_name: Metric to query
            start_time: Start of time range (default: 1 hour ago)
            end_time: End of time range (default: now)
            labels: Filter by labels
            aggregation: 'avg', 'max', 'min', 'sum', 'count'
            group_by: Group by label keys

        Returns:
            Query results
        """
        # Default time range: last hour
        if start_time is None:
            start_time = datetime.now() - timedelta(hours=1)
        if end_time is None:
            end_time = datetime.now()

        # Validate time range
        if start_time >= end_time:
            raise ValueError("start_time must be before end_time")

        logger.info(
            f"Query: {metric_name}, "
            f"range={start_time.isoformat()} to {end_time.isoformat()}, "
            f"aggregation={aggregation}"
        )

        return self.storage.query(
            metric_name=metric_name,
            start_time=start_time,
            end_time=end_time,
            labels=labels,
            aggregation=aggregation,
            group_by=group_by
        )

    def query_last_hour(
        self,
        metric_name: str,
        labels: Optional[Dict[str, str]] = None,
        aggregation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query data from the last hour."""
        return self.query(
            metric_name=metric_name,
            start_time=datetime.now() - timedelta(hours=1),
            labels=labels,
            aggregation=aggregation
        )

    def query_last_24_hours(
        self,
        metric_name: str,
        labels: Optional[Dict[str, str]] = None,
        aggregation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query data from the last 24 hours."""
        return self.query(
            metric_name=metric_name,
            start_time=datetime.now() - timedelta(hours=24),
            labels=labels,
            aggregation=aggregation
        )

    def query_range(
        self,
        metric_name: str,
        duration_minutes: int,
        labels: Optional[Dict[str, str]] = None,
        aggregation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Query data for a duration from now backwards.

        Args:
            metric_name: Metric to query
            duration_minutes: How many minutes back to query
            labels: Filter labels
            aggregation: Aggregation function

        Example:
            # Last 15 minutes of CPU data
            qs.query_range('cpu.load', duration_minutes=15, aggregation='avg')
        """
        return self.query(
            metric_name=metric_name,
            start_time=datetime.now() - timedelta(minutes=duration_minutes),
            labels=labels,
            aggregation=aggregation
        )

    def get_latest_value(
        self,
        metric_name: str,
        labels: Optional[Dict[str, str]] = None
    ) -> Optional[float]:
        """
        Get most recent value for a metric.

        Args:
            metric_name: Metric name
            labels: Filter labels

        Returns:
            Latest value or None if no data
        """
        results = self.query(
            metric_name=metric_name,
            start_time=datetime.now() - timedelta(minutes=5),
            labels=labels
        )

        if results:
            # Return most recent value (results are ordered by timestamp)
            return results[-1]['value']

        return None

    def list_metrics(self) -> List[str]:
        """Get list of all available metric names."""
        return self.storage.get_metric_names()

    def get_label_keys(self, metric_name: Optional[str] = None) -> List[str]:
        """
        Get all label keys for a metric or globally.

        Args:
            metric_name: Specific metric (None = all metrics)

        Returns:
            List of label keys
        """
        return self.storage.get_label_keys(metric_name)

    def get_label_values(
        self,
        metric_name: str,
        label_key: str
    ) -> List[str]:
        """
        Get all values for a label key.

        Example:
            # Get all hosts reporting CPU metrics
            hosts = qs.get_label_values('cpu.load', 'host')
        """
        return self.storage.get_label_values(metric_name, label_key)

    def get_series_count(
        self,
        metric_name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> int:
        """
        Get number of unique time series (unique label combinations).

        This helps assess metric cardinality.

        High cardinality can cause performance issues in TSDBs.
        """
        results = self.query(
            metric_name=metric_name,
            start_time=start_time,
            end_time=end_time
        )

        # Count unique label combinations
        unique_series = set()
        for result in results:
            import json
            labels_key = json.dumps(result['labels'], sort_keys=True)
            unique_series.add(labels_key)

        return len(unique_series)
