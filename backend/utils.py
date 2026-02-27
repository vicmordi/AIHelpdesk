"""
Shared utilities for request handling and similar.
"""


def get_client_ip(request) -> str:
    """
    Extract client IP from FastAPI/Starlette request.
    - Checks x-forwarded-for header first (for proxies/load balancers)
    - Falls back to request.client.host
    - Returns "unknown" if unavailable
    """
    if request is None:
        return "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
        return ip if ip else "unknown"
    if getattr(request, "client", None) and request.client:
        host = getattr(request.client, "host", None)
        return host if host else "unknown"
    return "unknown"
