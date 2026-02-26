"""
Brute force detection: track failed login attempts by IP.
If >= 5 failures from same IP within 5 minutes, log brute_force_attempt and clear.
Thread-safe for async (single process).
"""

import logging
import time
from collections import defaultdict
from typing import List, Optional

logger = logging.getLogger(__name__)

# ip -> list of timestamps of failed attempts
_failures_by_ip: dict = defaultdict(list)
WINDOW_SECONDS = 300  # 5 minutes
THRESHOLD = 5


def _prune(ts_list: List[float]) -> List[float]:
    now = time.time()
    return [t for t in ts_list if now - t < WINDOW_SECONDS]


def record_failed_login(ip: str) -> bool:
    """
    Record a failed login from IP. Prune old entries.
    Returns True if this IP has reached brute-force threshold (caller should log brute_force_attempt).
    """
    if not ip:
        return False
    now = time.time()
    _failures_by_ip[ip] = _prune(_failures_by_ip[ip])
    _failures_by_ip[ip].append(now)
    return len(_failures_by_ip[ip]) >= THRESHOLD


def clear_after_brute_force_log(ip: str) -> None:
    """Clear recorded failures for this IP after logging brute_force_attempt."""
    if ip in _failures_by_ip:
        del _failures_by_ip[ip]


def get_client_ip(request) -> str:
    """Extract client IP from FastAPI/Starlette request (supports X-Forwarded-For)."""
    if request is None:
        return ""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if getattr(request, "client", None) and request.client:
        return getattr(request.client, "host", "") or ""
    return ""
