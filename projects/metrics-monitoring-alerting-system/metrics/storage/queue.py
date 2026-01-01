"""
Message queue abstraction (Kafka simulation).

System Design Concept:
    [[message-queue-buffering]] - Decouples producers from consumers

Simulates:
    Apache Kafka with partitions, offsets, and consumer groups

Simplifications:
    - Single broker (Django database)
    - No replication
    - Simplified consumer group coordination

At Scale:
    - Multi-node Kafka cluster (3+ brokers)
    - Replication factor = 3
    - ZooKeeper for coordination
    - Retention policies (time/size based)
"""

from django.db import transaction
from django.db.models import Max
from metrics.models import MetricEvent
import hashlib
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class MetricsQueue:
    """
    Message queue for metrics events (simulates Kafka).

    Features:
        - Partitioning by metric name for parallelism
        - Sequential offset tracking per partition
        - At-least-once delivery semantics
        - Consumer commit/offset management

    Usage:
        queue = MetricsQueue(num_partitions=10)

        # Producer
        queue.produce(metric_data)

        # Consumer
        events = queue.consume(partition=0, last_offset=100, batch_size=100)
        queue.commit(partition=0, offset=200)
    """

    def __init__(self, num_partitions: int = 10):
        """
        Initialize queue with partition count.

        Args:
            num_partitions: Number of partitions for parallel processing
                           (similar to Kafka topic partitions)
        """
        self.num_partitions = num_partitions
        logger.info(f"MetricsQueue initialized with {num_partitions} partitions")

    def _get_partition(self, metric_name: str) -> int:
        """
        Calculate partition number from metric name.

        Uses consistent hashing to ensure same metric always
        goes to same partition (maintains ordering per metric).

        Args:
            metric_name: Name of the metric

        Returns:
            Partition number (0 to num_partitions-1)
        """
        metric_hash = int(hashlib.md5(metric_name.encode()).hexdigest(), 16)
        return metric_hash % self.num_partitions

    def _get_next_offset(self, partition: int) -> int:
        """
        Get next available offset for partition.

        Thread-safe via database transaction.
        """
        max_offset = MetricEvent.objects.filter(
            partition=partition
        ).aggregate(Max('offset'))['offset__max']

        return (max_offset or -1) + 1

    @transaction.atomic
    def produce(self, metric_data: Dict[str, Any]) -> MetricEvent:
        """
        Enqueue a metric event (producer).

        Args:
            metric_data: Metric payload {name, labels, timestamp, value}

        Returns:
            Created MetricEvent

        Example:
            event = queue.produce({
                'name': 'cpu.load',
                'labels': {'host': 'web-01'},
                'timestamp': '2024-01-01T00:00:00Z',
                'value': 0.75
            })
        """
        metric_name = metric_data['name']
        partition = self._get_partition(metric_name)
        offset = self._get_next_offset(partition)

        event = MetricEvent.objects.create(
            partition=partition,
            offset=offset,
            metric_name=metric_name,
            payload=metric_data
        )

        logger.debug(
            f"Produced event: partition={partition}, offset={offset}, "
            f"metric={metric_name}"
        )

        return event

    def produce_batch(self, metrics: List[Dict[str, Any]]) -> List[MetricEvent]:
        """
        Enqueue multiple metric events in batch.

        More efficient than individual produce() calls.

        Args:
            metrics: List of metric payloads

        Returns:
            List of created MetricEvents
        """
        events = []

        # Group by partition for efficient batch insert
        partitions_data = {}
        for metric_data in metrics:
            partition = self._get_partition(metric_data['name'])
            if partition not in partitions_data:
                partitions_data[partition] = []
            partitions_data[partition].append(metric_data)

        # Insert per partition with sequential offsets
        for partition, partition_metrics in partitions_data.items():
            with transaction.atomic():
                next_offset = self._get_next_offset(partition)

                for i, metric_data in enumerate(partition_metrics):
                    event = MetricEvent(
                        partition=partition,
                        offset=next_offset + i,
                        metric_name=metric_data['name'],
                        payload=metric_data
                    )
                    events.append(event)

                # Bulk create for efficiency
                MetricEvent.objects.bulk_create(events[-len(partition_metrics):])

        logger.info(f"Batch produced {len(events)} events across {len(partitions_data)} partitions")
        return events

    def consume(
        self,
        partition: int,
        last_offset: int = -1,
        batch_size: int = 100
    ) -> List[MetricEvent]:
        """
        Consume events from a partition (consumer).

        Args:
            partition: Partition to consume from
            last_offset: Last committed offset (-1 = start from beginning)
            batch_size: Maximum number of events to return

        Returns:
            List of unconsumed MetricEvents

        Example:
            events = queue.consume(partition=0, last_offset=99, batch_size=50)
            # Process events...
            if events:
                queue.commit(partition=0, offset=events[-1].offset)
        """
        events = MetricEvent.objects.filter(
            partition=partition,
            offset__gt=last_offset,
            consumed=False
        ).order_by('offset')[:batch_size]

        event_list = list(events)

        if event_list:
            logger.debug(
                f"Consumed {len(event_list)} events from partition {partition} "
                f"(offsets {event_list[0].offset}-{event_list[-1].offset})"
            )

        return event_list

    def commit(self, partition: int, offset: int) -> None:
        """
        Mark events as consumed up to offset (consumer commit).

        Args:
            partition: Partition number
            offset: Highest offset successfully processed

        Note:
            This marks events as consumed but doesn't delete them.
            A separate cleanup job would delete old consumed events.
        """
        updated_count = MetricEvent.objects.filter(
            partition=partition,
            offset__lte=offset,
            consumed=False
        ).update(
            consumed=True,
            consumed_at=datetime.now()
        )

        if updated_count > 0:
            logger.debug(
                f"Committed partition {partition} up to offset {offset} "
                f"({updated_count} events marked consumed)"
            )

    def get_lag(self, partition: int, consumer_offset: int) -> int:
        """
        Calculate consumer lag (unconsumed events).

        Args:
            partition: Partition number
            consumer_offset: Current consumer position

        Returns:
            Number of events behind latest offset
        """
        latest_offset = MetricEvent.objects.filter(
            partition=partition
        ).aggregate(Max('offset'))['offset__max']

        if latest_offset is None:
            return 0

        lag = latest_offset - consumer_offset
        return max(0, lag)

    def cleanup_consumed_events(self, retention_hours: int = 1) -> int:
        """
        Delete old consumed events (retention policy).

        Args:
            retention_hours: Keep consumed events for this many hours

        Returns:
            Number of events deleted

        Note:
            In production Kafka, this is automatic based on retention.ms config.
        """
        cutoff_time = datetime.now() - timedelta(hours=retention_hours)

        deleted_count, _ = MetricEvent.objects.filter(
            consumed=True,
            consumed_at__lt=cutoff_time
        ).delete()

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old consumed events")

        return deleted_count

    def get_partition_stats(self, partition: int) -> Dict[str, Any]:
        """
        Get statistics for a partition.

        Returns:
            Dictionary with partition metrics:
                - latest_offset: Highest offset in partition
                - unconsumed_count: Number of pending events
                - total_count: Total events in partition
        """
        events = MetricEvent.objects.filter(partition=partition)

        stats = {
            'partition': partition,
            'latest_offset': events.aggregate(Max('offset'))['offset__max'] or -1,
            'unconsumed_count': events.filter(consumed=False).count(),
            'total_count': events.count()
        }

        return stats

    def get_all_stats(self) -> List[Dict[str, Any]]:
        """Get statistics for all partitions."""
        return [
            self.get_partition_stats(partition)
            for partition in range(self.num_partitions)
        ]


class SimpleConsumer:
    """
    Simple consumer with automatic offset tracking.

    Wraps MetricsQueue for easier consumption pattern.

    Usage:
        consumer = SimpleConsumer(partition=0, group_id="metrics-writer")

        for batch in consumer.poll(batch_size=100):
            process_batch(batch)
            consumer.commit()  # Auto-commits last offset
    """

    def __init__(
        self,
        partition: int,
        group_id: str = "default",
        queue: Optional[MetricsQueue] = None
    ):
        """
        Initialize consumer.

        Args:
            partition: Partition to consume from
            group_id: Consumer group identifier (for logging/monitoring)
            queue: MetricsQueue instance (creates new if None)
        """
        self.partition = partition
        self.group_id = group_id
        self.queue = queue or MetricsQueue()
        self.current_offset = -1  # Start from beginning
        self.last_batch = []

        logger.info(
            f"Consumer initialized: group={group_id}, partition={partition}"
        )

    def poll(self, batch_size: int = 100, timeout_seconds: int = 1) -> List[MetricEvent]:
        """
        Poll for new events.

        Args:
            batch_size: Maximum events to return
            timeout_seconds: Unused (for API compatibility)

        Returns:
            List of MetricEvents
        """
        events = self.queue.consume(
            partition=self.partition,
            last_offset=self.current_offset,
            batch_size=batch_size
        )

        self.last_batch = events
        return events

    def commit(self) -> None:
        """Commit last polled batch."""
        if self.last_batch:
            last_offset = self.last_batch[-1].offset
            self.queue.commit(self.partition, last_offset)
            self.current_offset = last_offset
            logger.debug(f"Consumer committed offset {last_offset}")
