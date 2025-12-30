"""
FastAPI application with rate limiting middleware.

System Design Concept:
    This implements the API Gateway / Rate Limiter Middleware from
    Figure 4-2 and Figure 4-13 in the chapter.

    The middleware intercepts requests before they reach API servers
    and applies rate limiting. If rate limit is exceeded, returns
    HTTP 429 (Too Many Requests) as described on page 387.

Architecture:
    Request Flow (from Figure 4-3):
    1. Client sends request
    2. Rate limiter middleware checks limit
    3. If allowed: forward to API server
    4. If rejected: return 429 with retry-after header

HTTP Response Headers (from page 397-402):
    - X-Ratelimit-Remaining: Requests left in window
    - X-Ratelimit-Limit: Total allowed per window
    - X-Ratelimit-Retry-After: Seconds until retry
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable

from src.config import settings
from src.storage.redis_client import redis_client
from src.services.rate_limiter_service import RateLimiterService
from src.models import (
    ClientIdentifier,
    RateLimitRule,
    TimeUnit,
    RateLimitAlgorithm,
)

logger = logging.getLogger(__name__)


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Startup: Connect to Redis
    Shutdown: Close Redis connection
    """
    # Startup
    logger.info("[API] Starting rate limiter service")
    await redis_client.connect()
    logger.info("[API] Ready to handle requests")

    yield

    # Shutdown
    logger.info("[API] Shutting down")
    await redis_client.disconnect()


# Create FastAPI app
app = FastAPI(
    title="Rate Limiter Service",
    description="Distributed rate limiting with multiple algorithms",
    version="1.0.0",
    lifespan=lifespan,
)

# Initialize rate limiter service
rate_limiter_service = RateLimiterService(redis_client)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware that intercepts all requests.

    System Design Concept:
        This is the middleware from Figure 4-2 that sits between clients
        and API servers. It implements the decision logic from Figure 4-3.

    How it works:
        1. Extract client identifier (IP, user ID, etc.)
        2. Determine which rate limit rule to apply
        3. Check rate limit using appropriate algorithm
        4. Add rate limit headers to response
        5. If exceeded, return HTTP 429
    """

    async def dispatch(self, request: Request, call_next: Callable):
        """
        Process each request through rate limiting.

        Implementation:
            - Skip rate limiting for health check endpoint
            - Extract client info from request
            - Check rate limit
            - Add headers to response
            - Return 429 if rate limited
        """
        # Skip rate limiting for health check
        if request.url.path == "/health":
            return await call_next(request)

        # Extract client identifier
        # In production, would extract user_id from JWT token
        client = ClientIdentifier(
            ip_address=request.client.host if request.client else "unknown",
            user_id=request.headers.get("X-User-Id", "anonymous"),
            endpoint=request.url.path,
        )

        # Determine domain based on endpoint
        # This is simplified; production would use path-based routing
        domain = "api"  # Default domain
        if "/auth/" in request.url.path:
            domain = "auth"
        elif "/messages/" in request.url.path:
            domain = "messaging"

        # Check rate limit
        result = await rate_limiter_service.check_request(
            client, domain, key_type="ip_address"
        )

        # Add rate limit headers
        headers = result.to_headers()

        if not result.allowed:
            # Rate limit exceeded, return 429
            logger.warning(
                f"[MIDDLEWARE] Rate limit exceeded for {client.ip_address} "
                f"on {request.url.path}"
            )

            return JSONResponse(
                status_code=429,
                headers=headers,
                content={
                    "error": "Rate limit exceeded",
                    "message": f"Too many requests. Retry after {result.retry_after} seconds.",
                    "retry_after": result.retry_after,
                },
            )

        # Request allowed, proceed to API server
        response = await call_next(request)

        # Add rate limit headers to successful response
        for header, value in headers.items():
            response.headers[header] = value

        return response


# Add middleware to app
app.add_middleware(RateLimitMiddleware)


# ============================================================================
# API Endpoints
# ============================================================================


@app.get("/health")
async def health_check():
    """
    Health check endpoint (not rate limited).

    Used by load balancers and monitoring systems.
    """
    return {"status": "healthy", "service": "rate-limiter"}


@app.get("/")
async def root():
    """
    Root endpoint with information about the service.
    """
    return {
        "service": "Rate Limiter",
        "algorithms": [algo.value for algo in RateLimitAlgorithm],
        "endpoints": {
            "/health": "Health check",
            "/api/data": "Sample API endpoint (rate limited)",
            "/auth/login": "Sample auth endpoint (rate limited)",
            "/rules": "List active rate limit rules",
            "/rules/add": "Add a new rate limit rule",
        },
    }


@app.get("/api/data")
async def get_data():
    """
    Sample API endpoint that is rate limited.

    Rate limit: 100 requests per minute per IP (token bucket)
    """
    return {
        "message": "This is protected data from the API",
        "data": [1, 2, 3, 4, 5],
    }


@app.post("/auth/login")
async def login(username: str):
    """
    Sample authentication endpoint that is rate limited.

    Rate limit: 5 requests per minute per user (sliding window counter)
    """
    return {
        "message": f"Login attempt for {username}",
        "token": "fake-jwt-token-here",
    }


@app.get("/rules")
async def list_rules():
    """
    List all active rate limiting rules.

    Shows the configuration format similar to Lyft's YAML config
    from the chapter.
    """
    rules = []
    for rule_key, rule in rate_limiter_service.rules.items():
        rules.append({
            "domain": rule.domain,
            "key": rule.key,
            "limit": f"{rule.requests_per_unit} per {rule.unit.value}",
            "algorithm": rule.algorithm.value,
        })

    return {"rules": rules, "count": len(rules)}


@app.post("/rules/add")
async def add_rule(
    domain: str,
    key: str,
    requests_per_unit: int,
    unit: str,
    algorithm: str,
):
    """
    Add a new rate limiting rule dynamically.

    Example:
        POST /rules/add
        {
            "domain": "api",
            "key": "user_id",
            "requests_per_unit": 50,
            "unit": "minute",
            "algorithm": "token_bucket"
        }

    System Design Concept:
        In production, rules would be updated via configuration files
        and hot-reloaded. This endpoint simulates dynamic rule updates.
    """
    try:
        rule = RateLimitRule(
            domain=domain,
            key=key,
            requests_per_unit=requests_per_unit,
            unit=TimeUnit(unit),
            algorithm=RateLimitAlgorithm(algorithm),
        )

        rate_limiter_service.add_rule(rule)

        return {
            "message": "Rule added successfully",
            "rule": {
                "domain": domain,
                "key": key,
                "limit": f"{requests_per_unit} per {unit}",
                "algorithm": algorithm,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/simulate/{algorithm}")
async def simulate_algorithm(algorithm: str, request: Request):
    """
    Test endpoint to see specific algorithm in action.

    Allows testing different algorithms by overriding the default rule.

    Args:
        algorithm: One of: token_bucket, leaky_bucket, fixed_window,
                   sliding_window_log, sliding_window_counter
    """
    try:
        algo = RateLimitAlgorithm(algorithm)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid algorithm. Choose from: {[a.value for a in RateLimitAlgorithm]}"
        )

    # Create temporary rule for testing
    client = ClientIdentifier(
        ip_address=request.client.host if request.client else "unknown",
        user_id=request.headers.get("X-User-Id", "test-user"),
        endpoint="/simulate",
    )

    test_rule = RateLimitRule(
        domain="test",
        key="user_id",
        requests_per_unit=5,
        unit=TimeUnit.MINUTE,
        algorithm=algo,
    )

    # Temporarily add rule
    rate_limiter_service.add_rule(test_rule)

    # Check rate limit
    result = await rate_limiter_service.check_request(
        client, "test", key_type="user_id"
    )

    return {
        "algorithm": algorithm,
        "allowed": result.allowed,
        "remaining": result.remaining,
        "limit": result.limit,
        "retry_after": result.retry_after,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
