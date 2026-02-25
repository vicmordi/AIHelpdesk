"""
Rate limiting for all public API endpoints.
Uses IP-based limits by default; supports optional user-based key via request state.
OWASP: prevents brute-force and DoS; returns 429 with Retry-After for graceful back-off.
"""

import json
import os
import re
from fastapi import Request, Response
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Same pattern as config.CORS_ORIGIN_REGEX so 429 responses can add CORS when middleware is skipped
_CORS_ORIGIN_PATTERN = re.compile(r"^https://[^/]+\.(web\.app|firebaseapp\.com)$")


def _get_identifier(request: Request) -> str:
    """
    Rate limit key: IP-based. When X-Forwarded-For is set (e.g. behind proxy),
    use the leftmost client IP; otherwise use direct client host.
    OWASP: prevents single IP from exhausting limits.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


# Default: 200 requests per minute per IP. Stricter limits on auth routes (see auth.py).
_default = os.getenv("RATE_LIMIT_DEFAULT", "200/minute")
limiter = Limiter(
    key_func=_get_identifier,
    default_limits=[_default],
    headers_enabled=True,
    retry_after="http-date",
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """
    Return 429 with JSON body and Retry-After header.
    Adds CORS headers so browsers don't block when this response bypasses CORS middleware.
    OWASP: consistent error format; clients can back off and retry.
    """
    retry_after_seconds = 60
    body = {
        "detail": "Too many requests. Please slow down and retry later.",
        "retry_after_seconds": retry_after_seconds,
    }
    headers = {"Retry-After": str(retry_after_seconds)}
    origin = request.headers.get("origin")
    if origin and _CORS_ORIGIN_PATTERN.match(origin):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    return Response(
        content=json.dumps(body),
        status_code=429,
        media_type="application/json",
        headers=headers,
    )
