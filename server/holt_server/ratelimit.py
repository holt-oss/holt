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
# How often idle keys are swept out, so one-off IPs do not accumulate forever.
PRUNE_EVERY = 300.0


class RateLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._clock = clock
        self._pruned = clock()

    def hit(self, key: str, limit: int) -> None:
        """Count one request against `key`; raise `rate_limited` over `limit`."""
        self.hit_all([(key, limit)])

    def hit_all(self, limits: list[tuple[str, int]]) -> None:
        """Count one request against every `(key, limit)`, or against none of
        them: one that is over raises `rate_limited` and spends nothing on the
        others. A limit of 0 or less is no limit, and isn't counted."""
        now = self._clock()
        with self._lock:
            if now - self._pruned >= PRUNE_EVERY:
                self._prune(now)
            active = [(key, limit) for key, limit in limits if limit > 0]
            for key, limit in active:
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
            for key, _ in active:
                self._hits[key].append(now)

    def count(self, key: str) -> int:
        """Requests counted against `key` in the last hour."""
        now = self._clock()
        with self._lock:
            return sum(1 for t in self._hits.get(key, ()) if t > now - WINDOW)

    def _prune(self, now: float) -> None:
        for k in [k for k, hits in self._hits.items() if not hits or hits[-1] <= now - WINDOW]:
            del self._hits[k]
        self._pruned = now

    def __len__(self) -> int:
        return len(self._hits)
