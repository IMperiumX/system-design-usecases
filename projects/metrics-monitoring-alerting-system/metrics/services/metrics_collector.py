"""
Metrics Collector Service

System Design Concept:
    [[push-model]] - Agents push metrics to collectors

Simulates:
    CloudWatch PutMetricData API, Prometheus remote write

At Scale:
    - Horizontal scaling with load balancer
    - Auto-scaling based on CPU/memory
    - Rate limiting per client
    - Request validation and sanitization
"""

from metrics.storage.queue import MetricsQueue
from django.utils import timezone
from typing import List, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Receives metrics from agents and enqueues for processing.

    This is the entry point for metrics ingestion (push model).
    Collectors are stateless and horizontally scalable.

    Responsibilities:
        - Validate incoming metric data
        - Enqueue to message queue (Kafka simulation)
        - Return acknowledgment to client (fire-and-forget)

    Does NOT:
        - Write directly to database (decoupled via queue)
        - Perform aggregations (done by consumer or query service)
        - Evaluate alerts (done by alert manager)

    Usage:
        collector = MetricsCollector()

        # Collect single metric
        collector.collect({
            'name': 'cpu.load',
            'value': 0.75,
            'labels': {'host': 'web-01', 'region': 'us-west'},
            'timestamp': '2024-01-01T00:00:00Z'
        })

        # Collect batch (preferred for efficiency)
        collector.collect_batch([metric1, metric2, ...])
    """

    def __init__(self, queue: MetricsQueue = None):
        """
        Initialize collector with message queue.

        Args:
            queue: MetricsQueue instance (creates default if None)
        """
        self.queue = queue or MetricsQueue()
        logger.info("MetricsCollector initialized")

    def collect(self, metric_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Collect a single metric.

        Args:
            metric_data: Metric payload:
                {
                    'name': str,       # Required
                    'value': float,    # Required
                    'labels': dict,    # Optional
                    'timestamp': str   # Optional (ISO format)
                }

        Returns:
            Acknowledgment: {'status': 'accepted', 'metric': ...}

        Raises:
            ValueError: If validation fails
        """
        # Validate required fields
        self._validate_metric(metric_data)

        # Normalize timestamp
        metric_data = self._normalize_metric(metric_data)

        # Enqueue for processing
        try:
            self.queue.produce(metric_data)

            logger.debug(f"Collected metric: {metric_data['name']}")

            return {
                'status': 'accepted',
                'metric': metric_data['name']
            }

        except Exception as e:
            logger.error(f"Failed to enqueue metric: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }

    def collect_batch(self, metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Collect multiple metrics in batch (more efficient).

        Args:
            metrics: List of metric payloads

        Returns:
            Summary: {
                'accepted': int,
                'rejected': int,
                'errors': List[str]
            }
        """
        valid_metrics = []
        errors = []

        # Validate and normalize each metric
        for i, metric_data in enumerate(metrics):
            try:
                self._validate_metric(metric_data)
                normalized = self._normalize_metric(metric_data)
                valid_metrics.append(normalized)

            except ValueError as e:
                errors.append(f"Metric {i}: {str(e)}")
                logger.warning(f"Rejected metric {i}: {e}")

        # Batch enqueue valid metrics
        if valid_metrics:
            try:
                self.queue.produce_batch(valid_metrics)
                logger.info(f"Collected batch: {len(valid_metrics)} metrics")

            except Exception as e:
                logger.error(f"Failed to enqueue batch: {e}")
                errors.append(f"Queue error: {str(e)}")
                return {
                    'accepted': 0,
                    'rejected': len(metrics),
                    'errors': errors
                }

        return {
            'accepted': len(valid_metrics),
            'rejected': len(errors),
            'errors': errors
        }

    def _validate_metric(self, metric: Dict[str, Any]) -> None:
        """
        Validate metric data.

        Raises:
            ValueError: If validation fails
        """
        # Required fields
        if 'name' not in metric:
            raise ValueError("Missing required field: name")

        if 'value' not in metric:
            raise ValueError("Missing required field: value")

        # Type checks
        if not isinstance(metric['name'], str):
            raise ValueError("Field 'name' must be string")

        if not isinstance(metric['value'], (int, float)):
            raise ValueError("Field 'value' must be numeric")

        # Label validation
        if 'labels' in metric:
            if not isinstance(metric['labels'], dict):
                raise ValueError("Field 'labels' must be dictionary")

            # Check label cardinality (prevent high-cardinality labels)
            if len(metric['labels']) > 20:
                raise ValueError("Too many labels (max 20)")

        # Metric name format
        if len(metric['name']) > 255:
            raise ValueError("Metric name too long (max 255 chars)")

    def _normalize_metric(self, metric: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize metric data (add defaults, parse timestamp).

        Returns:
            Normalized metric dict
        """
        normalized = metric.copy()

        # Add default labels if missing
        if 'labels' not in normalized:
            normalized['labels'] = {}

        # Parse/default timestamp
        if 'timestamp' in normalized:
            # Parse ISO format string to datetime
            if isinstance(normalized['timestamp'], str):
                try:
                    normalized['timestamp'] = datetime.fromisoformat(
                        normalized['timestamp'].replace('Z', '+00:00')
                    )
                except ValueError as e:
                    logger.warning(f"Invalid timestamp format: {e}, using current time")
                    normalized['timestamp'] = timezone.now()
        else:
            # Default to current time
            normalized['timestamp'] = timezone.now()

        # Convert datetime to ISO string for JSON serialization
        if isinstance(normalized['timestamp'], datetime):
            normalized['timestamp'] = normalized['timestamp'].isoformat()

        return normalized

    def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get collector queue statistics for monitoring.

        Returns:
            Queue statistics across all partitions
        """
        stats = self.queue.get_all_stats()

        total_unconsumed = sum(s['unconsumed_count'] for s in stats)
        total_count = sum(s['total_count'] for s in stats)

        return {
            'partitions': len(stats),
            'total_events': total_count,
            'unconsumed_events': total_unconsumed,
            'partition_details': stats
        }


class CollectionAgent:
    """
    Agent that runs on monitored servers to collect and push metrics.

    In production, this would be a daemon process (like CloudWatch agent)
    collecting system metrics at regular intervals.

    This is a simplified version for demonstration.

    Usage:
        agent = CollectionAgent(
            collector_url="http://metrics-collector:8000/api/v1/metrics",
            host_labels={'host': 'web-01', 'region': 'us-west'}
        )

        # Collect system metrics
        metrics = agent.collect_system_metrics()

        # Push to collector
        agent.push(metrics)
    """

    def __init__(
        self,
        collector: MetricsCollector,
        host_labels: Dict[str, str] = None
    ):
        """
        Initialize collection agent.

        Args:
            collector: MetricsCollector instance
            host_labels: Common labels for all metrics from this host
        """
        self.collector = collector
        self.host_labels = host_labels or {}
        logger.info(f"CollectionAgent initialized with labels: {self.host_labels}")

    def collect_system_metrics(self) -> List[Dict[str, Any]]:
        """
        Collect system metrics (CPU, memory, disk).

        In production, this would use psutil or /proc filesystem.
        This is a simulated version.

        Returns:
            List of metric payloads
        """
        import random

        metrics = []

        # Simulate CPU metrics
        metrics.append({
            'name': 'cpu.load',
            'value': random.uniform(0.1, 0.9),
            'labels': {**self.host_labels, 'cpu': 'avg'}
        })

        # Simulate memory metrics
        metrics.append({
            'name': 'memory.used_percent',
            'value': random.uniform(30, 90),
            'labels': self.host_labels
        })

        # Simulate disk metrics
        metrics.append({
            'name': 'disk.used_percent',
            'value': random.uniform(20, 80),
            'labels': {**self.host_labels, 'mount': '/'}
        })

        # Simulate network metrics
        metrics.append({
            'name': 'network.bytes_sent',
            'value': random.randint(1000000, 10000000),
            'labels': {**self.host_labels, 'interface': 'eth0'}
        })

        return metrics

    def push(self, metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Push metrics to collector.

        Args:
            metrics: List of metric payloads

        Returns:
            Push result summary
        """
        result = self.collector.collect_batch(metrics)

        if result['accepted'] > 0:
            logger.info(
                f"Pushed {result['accepted']} metrics "
                f"({result['rejected']} rejected)"
            )

        if result['errors']:
            logger.error(f"Push errors: {result['errors']}")

        return result
