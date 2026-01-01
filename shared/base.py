"""
Base Classes for System Design Implementations

Provides abstract base classes and common patterns used across implementations.
Compatible with Django's sync-first approach, with optional async support.
"""

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar
from datetime import datetime, timedelta


K = TypeVar('K')  # Key type
V = TypeVar('V')  # Value type


class BaseStorage(ABC, Generic[K, V]):
    """
    Abstract base class for storage implementations.
    
    System Design Concept:
        Storage is fundamental to every system. This abstraction allows
        swapping implementations (in-memory → Redis → distributed) without
        changing business logic.
    
    Implementations might include:
        - InMemoryStorage: Dict-based, for testing/demos
        - RedisStorage: For caching with TTL
        - DjangoStorage: Backed by Django ORM
    """
    
    @abstractmethod
    def get(self, key: K) -> V | None:
        """Retrieve a value by key."""
        pass
    
    @abstractmethod
    def set(self, key: K, value: V, ttl: int | None = None) -> None:
        """Store a value with optional TTL in seconds."""
        pass
    
    @abstractmethod
    def delete(self, key: K) -> bool:
        """Delete a key. Returns True if key existed."""
        pass
    
    @abstractmethod
    def exists(self, key: K) -> bool:
        """Check if a key exists."""
        pass


class InMemoryStorage(BaseStorage[str, Any]):
    """
    Simple in-memory storage implementation.
    
    System Design Concept:
        Simulates a key-value store like Redis. In production, this would
        be replaced with actual Redis or Django's cache framework.
    
    Simplifications:
        - No persistence (data lost on restart)
        - Single process (no distribution)
        - Basic TTL support via lazy expiration
    
    Usage in Django:
        For real projects, prefer django.core.cache with Redis backend.
        This class is for learning/demos where you want to see the internals.
    """
    
    def __init__(self):
        self._data: dict[str, Any] = {}
        self._expiry: dict[str, datetime] = {}
    
    def _is_expired(self, key: str) -> bool:
        if key in self._expiry:
            if datetime.now() > self._expiry[key]:
                del self._data[key]
                del self._expiry[key]
                return True
        return False
    
    def get(self, key: str) -> Any | None:
        if self._is_expired(key):
            return None
        return self._data.get(key)
    
    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self._data[key] = value
        if ttl:
            self._expiry[key] = datetime.now() + timedelta(seconds=ttl)
        elif key in self._expiry:
            del self._expiry[key]
    
    def delete(self, key: str) -> bool:
        if key in self._data:
            del self._data[key]
            self._expiry.pop(key, None)
            return True
        return False
    
    def exists(self, key: str) -> bool:
        if self._is_expired(key):
            return False
        return key in self._data
    
    def clear(self) -> None:
        """Clear all data. Useful for tests."""
        self._data.clear()
        self._expiry.clear()


class BaseService(ABC):
    """
    Abstract base class for business logic services.
    
    System Design Concept:
        Services encapsulate business logic, separate from Django views/serializers.
        This keeps views thin and logic testable without HTTP overhead.
    
    Django Pattern:
        - Views handle HTTP request/response
        - Serializers handle validation/transformation  
        - Services handle business logic
        - Models handle persistence
    """
    
    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Return service health status."""
        pass


class RateLimiter(ABC):
    """
    Abstract rate limiter interface.
    
    System Design Concept:
        Rate limiting protects services from abuse and ensures fair usage.
        Different algorithms trade off between accuracy and memory usage.
    
    Common implementations:
        - Token Bucket: Smooth rate, allows bursts
        - Sliding Window: Accurate but more memory
        - Fixed Window: Simple but can have edge spikes
    
    Django Integration:
        Can be used as middleware or decorator on views.
        For production, consider django-ratelimit or Redis-based solutions.
    """
    
    @abstractmethod
    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed under rate limit."""
        pass
    
    @abstractmethod
    def get_remaining(self, key: str) -> int:
        """Get remaining requests in current window."""
        pass


class TokenBucketRateLimiter(RateLimiter):
    """
    Token Bucket rate limiter implementation.
    
    System Design Concept:
        Tokens accumulate at a fixed rate up to a maximum (bucket size).
        Each request consumes one token. Allows bursts up to bucket size.
    
    Simplifications:
        - In-memory only (use Redis for distributed)
        - Single process
    """
    
    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: Tokens added per second
            capacity: Maximum tokens (bucket size)
        """
        self.rate = rate
        self.capacity = capacity
        self._buckets: dict[str, dict] = {}
    
    def _get_bucket(self, key: str) -> dict:
        now = datetime.now()
        
        if key not in self._buckets:
            self._buckets[key] = {
                'tokens': self.capacity,
                'last_update': now
            }
            return self._buckets[key]
        
        bucket = self._buckets[key]
        elapsed = (now - bucket['last_update']).total_seconds()
        bucket['tokens'] = min(
            self.capacity,
            bucket['tokens'] + elapsed * self.rate
        )
        bucket['last_update'] = now
        return bucket
    
    def is_allowed(self, key: str) -> bool:
        bucket = self._get_bucket(key)
        if bucket['tokens'] >= 1:
            bucket['tokens'] -= 1
            return True
        return False
    
    def get_remaining(self, key: str) -> int:
        bucket = self._get_bucket(key)
        return int(bucket['tokens'])


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.
    
    System Design Concept:
        Prevents cascading failures by stopping requests to failing services.
        States: CLOSED (normal) → OPEN (failing) → HALF_OPEN (testing)
    
    Django Usage:
        Wrap external service calls (APIs, databases) to fail fast
        when downstream services are unhealthy.
    
    At Scale:
        Would be distributed (shared state via Redis) and include
        more sophisticated health metrics.
    """
    
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time: datetime | None = None
        self.state = self.CLOSED
    
    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure_time = datetime.now()
        
        if self.failures >= self.failure_threshold:
            self.state = self.OPEN
    
    def record_success(self) -> None:
        self.failures = 0
        self.state = self.CLOSED
    
    def is_available(self) -> bool:
        if self.state == self.CLOSED:
            return True
        
        if self.state == self.OPEN and self.last_failure_time:
            if datetime.now() > self.last_failure_time + timedelta(seconds=self.recovery_timeout):
                self.state = self.HALF_OPEN
                return True
        
        return self.state == self.HALF_OPEN
    
    def __call__(self, func):
        """Use as decorator."""
        from functools import wraps
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not self.is_available():
                raise CircuitBreakerOpen(f"Circuit breaker is {self.state}")
            
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise
        
        return wrapper


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""
    pass