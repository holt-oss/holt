"""Per-IP (anonymous) and per-user limits on new work.

In memory, sliding one-hour window. That is right for one server process; a
second process would need this moved into Postgres.
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict, deque

from holt_server.errors import ApiError

WINDOW = 3600.0


class RateLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._clock = clock

    def hit(self, key: str, limit: int) -> None:
        """Count one request against `key`; raise `rate_limited` over `limit`."""
        if limit <= 0:
            return
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - WINDOW:
                hits.popleft()
            if len(hits) >= limit:
                retry = max(1, math.ceil(hits[0] + WINDOW - now))
                raise ApiError(
                    "rate_limited",
                    "You've checked a lot of repositories in the last hour. "
                    "Please wait a bit, or sign in for a higher limit.",
                    retry_after=retry,
                )
            hits.append(now)
