"""
Notification Service - Long polling implementation

System Design Concept:
    Implements [[long-polling]] for real-time file change notifications

Simulates:
    Notification server cluster handling 1M connections/server

At Scale:
    - Multiple notification servers behind load balancer
    - Redis pub/sub for cross-server event distribution
    - Exponential backoff on reconnection to prevent storms
"""

import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID
from collections import defaultdict

from src.models import Event, EventType
from src.config import settings


class NotificationService:
    """
    Long polling notification service

    How it works:
    1. Client sends GET /notifications/poll with user_id
    2. Server holds connection open (60s timeout)
    3. If event occurs, immediately respond and close connection
    4. If timeout, respond 204 No Content
    5. Client immediately reconnects (maintains persistent presence)
    """

    def __init__(self):
        # user_id → asyncio.Queue of events
        self.subscribers: dict[str, asyncio.Queue] = {}

        # Track connection counts for monitoring
        self.connection_count = 0
        self.max_connections = settings.max_connections_per_server

    async def subscribe(
        self, user_id: str, timeout_seconds: int = None
    ) -> Optional[Event]:
        """
        Long poll: wait for event or timeout

        Args:
            user_id: User to subscribe
            timeout_seconds: How long to wait (default from settings)

        Returns:
            Event if one occurred, None on timeout

        Raises:
            ConnectionError if max connections exceeded
        """
        if self.connection_count >= self.max_connections:
            raise ConnectionError("Maximum connections reached")

        # Create queue for user if doesn't exist
        if user_id not in self.subscribers:
            self.subscribers[user_id] = asyncio.Queue()

        queue = self.subscribers[user_id]
        timeout = timeout_seconds or settings.long_poll_timeout_seconds

        self.connection_count += 1

        try:
            # Wait for event with timeout
            event = await asyncio.wait_for(queue.get(), timeout=timeout)
            return event
        except asyncio.TimeoutError:
            # No events occurred, client will reconnect
            return None
        finally:
            self.connection_count -= 1

    async def publish(self, event: Event):
        """
        Publish event to user

        If user is subscribed (long poll active), immediately deliver.
        If user offline, event goes to offline queue.

        Args:
            event: Event to publish
        """
        user_id = str(event.user_id)

        if user_id in self.subscribers:
            # User is connected, deliver immediately
            await self.subscribers[user_id].put(event)
        else:
            # User offline, send to offline queue
            await offline_queue.enqueue(user_id, event)

    async def broadcast(self, user_ids: list[str], event: Event):
        """
        Broadcast event to multiple users

        Used for file sharing notifications
        """
        for user_id in user_ids:
            event_copy = Event(**event.dict())
            event_copy.user_id = UUID(user_id)
            await self.publish(event_copy)

    async def unsubscribe(self, user_id: str):
        """
        Clean up user's subscription

        Called when user goes offline
        """
        if user_id in self.subscribers:
            del self.subscribers[user_id]

    def get_stats(self) -> dict:
        """Get service statistics"""
        return {
            "active_connections": self.connection_count,
            "max_connections": self.max_connections,
            "subscribed_users": len(self.subscribers),
        }


class OfflineQueue:
    """
    Queue for events when user is offline

    System Design Note:
        In production: Kafka topic partitioned by user_id
        Retention: 7 days

        When user comes online:
        - Fetch all pending events from Kafka
        - Deliver in order
        - Mark as consumed
    """

    def __init__(self):
        # user_id → list of events
        self.queues: dict[str, list[Event]] = defaultdict(list)
        self.max_queue_size = 1000  # Prevent unbounded growth

    async def enqueue(self, user_id: str, event: Event):
        """Add event for offline user"""
        if len(self.queues[user_id]) < self.max_queue_size:
            self.queues[user_id].append(event)
        else:
            # Drop oldest event (or in production: move to cold storage)
            self.queues[user_id].pop(0)
            self.queues[user_id].append(event)

    async def dequeue_all(self, user_id: str) -> list[Event]:
        """
        Client came online, fetch all pending events

        Returns events in chronological order
        """
        events = self.queues.pop(user_id, [])
        return sorted(events, key=lambda e: e.timestamp)

    async def peek(self, user_id: str) -> list[Event]:
        """Check pending events without removing"""
        return self.queues.get(user_id, [])

    def get_stats(self) -> dict:
        """Get queue statistics"""
        total_events = sum(len(events) for events in self.queues.values())
        return {
            "users_with_pending_events": len(self.queues),
            "total_pending_events": total_events,
        }


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


async def notify_file_uploaded(file_id: UUID, user_id: UUID, file_name: str):
    """Send file.uploaded notification"""
    event = Event(
        event_type=EventType.FILE_UPLOADED,
        file_id=file_id,
        user_id=user_id,
        metadata={"file_name": file_name},
    )
    await notification_service.publish(event)


async def notify_file_updated(file_id: UUID, user_id: UUID, file_name: str, version: int):
    """Send file.updated notification"""
    event = Event(
        event_type=EventType.FILE_UPDATED,
        file_id=file_id,
        user_id=user_id,
        metadata={"file_name": file_name, "version": version},
    )
    await notification_service.publish(event)


async def notify_file_shared(
    file_id: UUID, owner_id: UUID, shared_with_id: UUID, file_name: str
):
    """Send file.shared notification"""
    event = Event(
        event_type=EventType.FILE_SHARED,
        file_id=file_id,
        user_id=shared_with_id,  # Notify the recipient
        metadata={"file_name": file_name, "owner_id": str(owner_id)},
    )
    await notification_service.publish(event)


async def notify_sync_conflict(file_id: UUID, user_id: UUID, conflict_data: dict):
    """Send sync.conflict notification"""
    event = Event(
        event_type=EventType.SYNC_CONFLICT,
        file_id=file_id,
        user_id=user_id,
        metadata=conflict_data,
    )
    await notification_service.publish(event)


# Global instances
notification_service = NotificationService()
offline_queue = OfflineQueue()
