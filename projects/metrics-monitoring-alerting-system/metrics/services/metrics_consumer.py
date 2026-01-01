"""
Metrics Consumer Service

System Design Concept:
    [[stream-processing]] - Consumes from queue and writes to storage

Simulates:
    Apache Storm/Flink consumer, Kafka Streams application

At Scale:
    - Multiple consumer instances (consumer group)
    - Partition assignment coordination
    - Checkpointing for fault tolerance
    - Backpressure handling
"""

from metrics.storage.queue import SimpleConsumer, MetricsQueue
from metrics.storage.timeseries import TimeSeriesStorage
from datetime import datetime
from typing import List, Dict, Any
import logging
import time

logger = logging.getLogger(__name__)


class MetricsConsumer:
    """
    Consumes metrics from queue and writes to time-series storage.

    This decouples the collection layer from storage layer,
    providing:
        - Buffering during database outages
        - Batch writes for efficiency
        - At-least-once delivery

    In production, this would run as a long-lived background process.

    Usage:
        consumer = MetricsConsumer(partition=0, group_id="metrics-writer")

        # Process single batch
        consumer.process_batch()

        # Run continuous loop
        consumer.run(max_iterations=100)
    """

    def __init__(
        self,
        partition: int,
        group_id: str = "metrics-writer",
        batch_size: int = 100,
        storage: TimeSeriesStorage = None,
        queue: MetricsQueue = None
    ):
        """
        Initialize consumer for a partition.

        Args:
            partition: Partition number to consume from
            group_id: Consumer group identifier
            batch_size: Number of events to process per batch
            storage: TimeSeriesStorage instance
            queue: MetricsQueue instance
        """
        self.partition = partition
        self.group_id = group_id
        self.batch_size = batch_size

        # Initialize storage and queue
        self.storage = storage or TimeSeriesStorage()
        self.consumer = SimpleConsumer(
            partition=partition,
            group_id=group_id,
            queue=queue
        )

        # Metrics tracking
        self.metrics_processed = 0
        self.batches_processed = 0
        self.errors = 0

        logger.info(
            f"MetricsConsumer initialized: partition={partition}, "
            f"group_id={group_id}, batch_size={batch_size}"
        )

    def process_batch(self) -> Dict[str, int]:
        """
        Process one batch of events from queue.

        Returns:
            Statistics: {
                'fetched': int,
                'written': int,
                'errors': int
            }
        """
        # Poll for events
        events = self.consumer.poll(batch_size=self.batch_size)

        if not events:
            logger.debug(f"No events available (partition {self.partition})")
            return {'fetched': 0, 'written': 0, 'errors': 0}

        logger.info(f"Processing batch of {len(events)} events")

        # Convert events to metrics
        metrics_to_write = []
        errors = 0

        for event in events:
            try:
                metric_data = self._parse_event(event)
                metrics_to_write.append(metric_data)

            except Exception as e:
                logger.error(f"Failed to parse event {event.id}: {e}")
                errors += 1

        # Batch write to storage
        written = 0
        if metrics_to_write:
            try:
                written = self.storage.write_batch(metrics_to_write)
                logger.info(f"Wrote {written} metrics to storage")

            except Exception as e:
                logger.error(f"Failed to write batch: {e}")
                errors += len(metrics_to_write)

        # Commit offset if successful
        if written > 0:
            self.consumer.commit()
            self.metrics_processed += written
            self.batches_processed += 1

        self.errors += errors

        return {
            'fetched': len(events),
            'written': written,
            'errors': errors
        }

    def _parse_event(self, event) -> Dict[str, Any]:
        """
        Parse MetricEvent to storage format.

        Args:
            event: MetricEvent instance

        Returns:
            Metric data dict for TimeSeriesStorage
        """
        payload = event.payload

        # Parse timestamp
        timestamp = payload.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

        return {
            'name': payload['name'],
            'value': payload['value'],
            'labels': payload.get('labels', {}),
            'timestamp': timestamp
        }

    def run(
        self,
        max_iterations: int = None,
        poll_interval_seconds: float = 1.0
    ) -> None:
        """
        Run continuous consumption loop.

        Args:
            max_iterations: Stop after N iterations (None = run forever)
            poll_interval_seconds: Sleep time when queue is empty

        This would typically run as a background daemon/service.
        """
        iteration = 0

        logger.info(f"Starting consumer loop (partition {self.partition})")

        while True:
            if max_iterations and iteration >= max_iterations:
                logger.info(f"Reached max iterations ({max_iterations}), stopping")
                break

            # Process one batch
            stats = self.process_batch()

            # Sleep if queue was empty
            if stats['fetched'] == 0:
                time.sleep(poll_interval_seconds)

            iteration += 1

            # Log progress periodically
            if iteration % 10 == 0:
                logger.info(
                    f"Consumer progress: {self.metrics_processed} metrics processed, "
                    f"{self.batches_processed} batches, {self.errors} errors"
                )

    def get_stats(self) -> Dict[str, Any]:
        """Get consumer statistics for monitoring."""
        lag = self.consumer.queue.get_lag(
            self.partition,
            self.consumer.current_offset
        )

        return {
            'partition': self.partition,
            'group_id': self.group_id,
            'current_offset': self.consumer.current_offset,
            'lag': lag,
            'metrics_processed': self.metrics_processed,
            'batches_processed': self.batches_processed,
            'errors': self.errors
        }


class ConsumerPool:
    """
    Manages multiple consumers (one per partition).

    In production, this would be handled by a consumer group
    coordinator (e.g., Kafka's GroupCoordinator).

    Usage:
        pool = ConsumerPool(num_partitions=10)

        # Process all partitions once
        pool.process_all_once()

        # Run continuous processing (would be separate processes)
        # pool.run_all()  # Not implemented - would spawn threads/processes
    """

    def __init__(
        self,
        num_partitions: int = 10,
        group_id: str = "metrics-writer"
    ):
        """
        Initialize consumer pool.

        Args:
            num_partitions: Number of partitions (one consumer each)
            group_id: Consumer group identifier
        """
        self.consumers = [
            MetricsConsumer(
                partition=i,
                group_id=group_id
            )
            for i in range(num_partitions)
        ]

        logger.info(f"ConsumerPool initialized with {num_partitions} consumers")

    def process_all_once(self) -> Dict[str, Any]:
        """
        Process one batch from each partition.

        Returns:
            Aggregated statistics
        """
        total_stats = {
            'fetched': 0,
            'written': 0,
            'errors': 0
        }

        for consumer in self.consumers:
            stats = consumer.process_batch()

            total_stats['fetched'] += stats['fetched']
            total_stats['written'] += stats['written']
            total_stats['errors'] += stats['errors']

        logger.info(
            f"ConsumerPool processed: {total_stats['written']} metrics "
            f"({total_stats['errors']} errors)"
        )

        return total_stats

    def get_all_stats(self) -> List[Dict[str, Any]]:
        """Get statistics from all consumers."""
        return [consumer.get_stats() for consumer in self.consumers]
