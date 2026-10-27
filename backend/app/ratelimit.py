"""In-memory sliding-window rate limiter.

Protects the shared LLM quota on a public demo. Keyed by user id when signed in,
otherwise by client IP. State lives in this process, which matches a single-instance
deployment; several instances would need a shared store such as Redis.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.auth import User
from app.config import get_settings

_WINDOWS = {"minute": 60, "day": 86_400}
_hits: dict[str, deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def client_key(request: Request, user: User | None) -> str:
    if user:
        return f"user:{user.id}"
    # Render and Vercel put the real client first in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return f"ip:{ip}"


def check(key: str, per_minute: int | None = None, per_day: int | None = None) -> None:
    """Record one hit for ``key`` or raise 429 if it is over either limit."""
    settings = get_settings()
    limits = {"minute": per_minute or settings.rate_limit_per_minute,
              "day": per_day or settings.rate_limit_per_day}
    now = time.time()
    with _lock:
        hits = _hits[key]
        while hits and hits[0] <= now - _WINDOWS["day"]:
            hits.popleft()
        last_minute = sum(1 for t in hits if t > now - _WINDOWS["minute"])
        if last_minute >= limits["minute"]:
            raise HTTPException(429, "You're sending requests too quickly. Please wait a minute and try again.",
                                headers={"Retry-After": "60"})
        if len(hits) >= limits["day"]:
            raise HTTPException(429, "Daily request limit reached. Please come back tomorrow.")
        hits.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()
