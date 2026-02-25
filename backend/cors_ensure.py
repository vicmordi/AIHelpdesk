"""
Ensures CORS headers are present on every response when the request Origin is allowed.
Fixes CORS errors when 500/429 or exception responses bypass the normal CORS middleware.
"""

import re
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Same as config.CORS_ORIGIN_REGEX: allow all Firebase Hosting origins
_CORS_ORIGIN_PATTERN = re.compile(r"^https://[^/]+\.(web\.app|firebaseapp\.com)$")


def cors_headers_for_origin(origin: Optional[str]) -> dict:
    """Return CORS header dict if origin is allowed; else empty dict. For use in exception handlers."""
    if not origin or not _CORS_ORIGIN_PATTERN.match(origin):
        return {}
    return {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true"}


class CorsEnsureMiddleware(BaseHTTPMiddleware):
    """
    Run last on response; if Access-Control-Allow-Origin is missing and the
    request Origin matches our allowed pattern, add CORS headers.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        origin = request.headers.get("origin")
        if not origin:
            return response
        if not _CORS_ORIGIN_PATTERN.match(origin):
            return response
        # Already has CORS origin (e.g. from CORSMiddleware)
        if response.headers.get("access-control-allow-origin"):
            return response
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        if request.method == "OPTIONS":
            response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
            response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, Authorization")
        return response
