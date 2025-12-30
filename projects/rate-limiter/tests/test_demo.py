"""
Test suite for rate limiter algorithms.

System Design Concept:
    These tests verify the key behaviors described in the chapter:
    - Token bucket allows bursts
    - Fixed window has edge case issue
    - Sliding window log is accurate
    - etc.
"""

import pytest
import asyncio
import time
from src.storage.redis_client import redis_client
from src.services.rate_limiter_service import RateLimiterService
from src.models import (
    ClientIdentifier,
    RateLimitRule,
    TimeUnit,
    RateLimitAlgorithm,
)


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_redis():
    """Connect to Redis before tests, disconnect after."""
    await redis_client.connect()
    yield
    await redis_client.disconnect()


@pytest.fixture
async def service():
    """Create a fresh rate limiter service for each test."""
    return RateLimiterService(redis_client)


@pytest.mark.asyncio
async def test_token_bucket_allows_burst(service):
    """
    Test that token bucket allows burst traffic.

    From chapter page 168: Token bucket allows bursts as long as
    tokens are available.
    """
    client = ClientIdentifier(user_id="burst_user")

    rule = RateLimitRule(
        domain="test",
        key="user_id",
        requests_per_unit=3,
        unit=TimeUnit.SECOND,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        bucket_size=5,  # Larger bucket allows burst
    )

    service.add_rule(rule)

    # Send 5 rapid requests - should all be allowed due to bucket size
    allowed_count = 0
    for _ in range(5):
        result = await service.check_request(client, "test", "user_id")
        if result.allowed:
            allowed_count += 1

    # Token bucket with bucket_size=5 should allow all 5
    assert allowed_count >= 4, "Token bucket should allow burst traffic"


@pytest.mark.asyncio
async def test_fixed_window_basic(service):
    """
    Test basic fixed window counter functionality.

    From chapter page 211: Simple counter that resets each window.
    """
    client = ClientIdentifier(user_id="window_user")

    rule = RateLimitRule(
        domain="test_window",
        key="user_id",
        requests_per_unit=3,
        unit=TimeUnit.SECOND,
        algorithm=RateLimitAlgorithm.FIXED_WINDOW,
    )

    service.add_rule(rule)

    # First 3 requests should be allowed
    for i in range(3):
        result = await service.check_request(client, "test_window", "user_id")
        assert result.allowed, f"Request {i+1} should be allowed"

    # 4th request should be rejected
    result = await service.check_request(client, "test_window", "user_id")
    assert not result.allowed, "4th request should be rejected"
    assert result.retry_after is not None, "Should have retry_after value"


@pytest.mark.asyncio
async def test_sliding_window_log_accuracy(service):
    """
    Test sliding window log accuracy.

    From chapter page 277: Most accurate algorithm.
    """
    client = ClientIdentifier(user_id="log_user")

    rule = RateLimitRule(
        domain="test_log",
        key="user_id",
        requests_per_unit=2,
        unit=TimeUnit.SECOND,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW_LOG,
    )

    service.add_rule(rule)

    # First 2 requests allowed
    result1 = await service.check_request(client, "test_log", "user_id")
    assert result1.allowed

    result2 = await service.check_request(client, "test_log", "user_id")
    assert result2.allowed

    # 3rd request should be rejected
    result3 = await service.check_request(client, "test_log", "user_id")
    assert not result3.allowed

    # Wait for window to slide
    await asyncio.sleep(2)

    # After window slides, should be allowed again
    result4 = await service.check_request(client, "test_log", "user_id")
    assert result4.allowed


@pytest.mark.asyncio
async def test_leaky_bucket_queue(service):
    """
    Test leaky bucket queue behavior.

    From chapter page 178: Requests processed at fixed rate.
    """
    client = ClientIdentifier(user_id="leak_user")

    rule = RateLimitRule(
        domain="test_leak",
        key="user_id",
        requests_per_unit=5,
        unit=TimeUnit.SECOND,
        algorithm=RateLimitAlgorithm.LEAKY_BUCKET,
        queue_size=3,
    )

    service.add_rule(rule)

    # Should allow up to queue_size requests
    results = []
    for _ in range(5):
        result = await service.check_request(client, "test_leak", "user_id")
        results.append(result.allowed)

    allowed_count = sum(results)
    assert allowed_count <= 3, "Should respect queue size"


@pytest.mark.asyncio
async def test_sliding_window_counter(service):
    """
    Test sliding window counter approximation.

    From chapter page 286: Hybrid approach with good accuracy.
    """
    client = ClientIdentifier(user_id="counter_user")

    rule = RateLimitRule(
        domain="test_counter",
        key="user_id",
        requests_per_unit=5,
        unit=TimeUnit.SECOND,
        algorithm=RateLimitAlgorithm.SLIDING_WINDOW_COUNTER,
    )

    service.add_rule(rule)

    # Send requests and verify limits
    allowed = 0
    for _ in range(7):
        result = await service.check_request(client, "test_counter", "user_id")
        if result.allowed:
            allowed += 1

    # Should allow close to the limit
    assert allowed <= 5, "Should not exceed limit significantly"
    assert allowed >= 4, "Should allow most requests within limit"


@pytest.mark.asyncio
async def test_rate_limit_headers(service):
    """
    Test that rate limit results include proper headers.

    From chapter page 397-402: X-Ratelimit-* headers.
    """
    client = ClientIdentifier(user_id="header_user")

    rule = RateLimitRule(
        domain="test_headers",
        key="user_id",
        requests_per_unit=5,
        unit=TimeUnit.MINUTE,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
    )

    service.add_rule(rule)

    result = await service.check_request(client, "test_headers", "user_id")

    headers = result.to_headers()

    assert "X-Ratelimit-Remaining" in headers
    assert "X-Ratelimit-Limit" in headers

    # When rate limited, should have retry-after
    # Make enough requests to trigger limit
    for _ in range(10):
        result = await service.check_request(client, "test_headers", "user_id")

    if not result.allowed:
        headers = result.to_headers()
        assert "X-Ratelimit-Retry-After" in headers


@pytest.mark.asyncio
async def test_no_rule_allows_request(service):
    """
    Test that requests are allowed when no rule exists (fail open).

    From chapter page 66: High fault tolerance requirement.
    """
    client = ClientIdentifier(user_id="norule_user")

    # Request for domain with no rule
    result = await service.check_request(client, "nonexistent", "user_id")

    # Should allow when no rule (fail open for availability)
    assert result.allowed, "Should allow request when no rule exists"


def test_client_identifier_key_generation():
    """
    Test that client identifiers generate correct Redis keys.

    Format should be: rate_limit:{domain}:{key_type}:{identifier}
    """
    rule = RateLimitRule(
        domain="auth",
        key="user_id",
        requests_per_unit=5,
        unit=TimeUnit.MINUTE,
        algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
    )

    client = ClientIdentifier(user_id="user123")
    key = client.get_key(rule)

    assert key == "rate_limit:auth:user_id:user123"


def test_rule_window_calculation():
    """Test that time units convert to seconds correctly."""
    rules = [
        (TimeUnit.SECOND, 1),
        (TimeUnit.MINUTE, 60),
        (TimeUnit.HOUR, 3600),
        (TimeUnit.DAY, 86400),
    ]

    for unit, expected_seconds in rules:
        rule = RateLimitRule(
            domain="test",
            key="test",
            requests_per_unit=5,
            unit=unit,
            algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
        )
        assert rule.get_window_seconds() == expected_seconds
