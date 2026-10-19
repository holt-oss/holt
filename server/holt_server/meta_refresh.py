"""Read a repository's details (language, stars, topics...) right after its
report is stored, so a repo checked for the first time shows up on Discover,
the Hacktoberfest row and its card complete, without waiting for the warm pass.

A report job reads its own repo's details first (`read_now`, waiting at most
jobs.META_WAIT_S) so the report reaches the page with them. When that read
fails or runs out of time, `note` tries again after the report: best effort,
and a failure is only logged. Reports that
finish within `DELAY_S` of each other share one query (up to
github.DETAILS_BATCH repos, about a point). A repo whose details are younger than
discover.META_MAX_AGE_HOURS is not read again; the daily meta-only warm pass
(`deploy/prod/warm-meta.sh`) keeps the rest fresh.

The report job itself doesn't read topics, so this is a separate query rather
than something copied out of the report.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from holt_server import repos
from holt_server.db import RepoMeta, now, utc

if TYPE_CHECKING:
    from holt_server.services import Services

log = logging.getLogger("holt_server.meta_refresh")

# How long to gather repos before reading: reports that finish close together
# share one query.
DELAY_S = 5.0


class MetaRefresher:
    def __init__(self, svc: Services, delay: float = DELAY_S) -> None:
        self.svc = svc
        self.delay = delay
        self._pending: dict[str, str] = {}  # repo_key -> repo, as the report named it
        self._task: asyncio.Task | None = None
        self.queries = 0

    def note(self, repo: str) -> None:
        """A report for `repo` was just stored. Never raises."""
        try:
            self._pending.setdefault(repos.key(repo), repo)
            if self._task is None or self._task.done():
                self._task = asyncio.get_running_loop().create_task(
                    self._flush(), name="holt-meta-refresh")
        except Exception:  # noqa: BLE001 -- details are a nicety; the report is done
            log.exception("could not schedule a details read for %s", repo)

    async def read_now(self, repo: str) -> None:
        """Read `repo`'s details now, when it has none or they're stale, so a
        report about to be announced carries them. Raises on a failed read."""
        await self._read({repos.key(repo): repo})

    async def _flush(self) -> None:
        await asyncio.sleep(self.delay)
        # Repos noted while a read is under way wait for the next round.
        while self._pending:
            batch, self._pending = self._pending, {}
            try:
                await self._read(batch)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- the next report tries again
                log.warning("reading repository details failed (%d repos): %s",
                            len(batch), getattr(exc, "code", None) or type(exc).__name__)

    async def _read(self, pending: dict[str, str]) -> None:
        # Here, not at the top: discover imports services, which imports jobs.
        from holt_server import discover

        stale = await self._stale(pending)
        for batch in discover.batches(stale):
            before = getattr(self.svc.lookup, "points_used", 0)
            details = await self.svc.lookup.details(batch)
            self.queries += 1
            written = await discover.store_meta(self.svc, details)
            log.info("repository details: %d of %d read, %d GitHub point(s)", written,
                     len(batch), getattr(self.svc.lookup, "points_used", 0) - before)

    async def _stale(self, pending: dict[str, str]) -> list[str]:
        from holt_server import discover

        cutoff = now() - timedelta(hours=discover.META_MAX_AGE_HOURS)
        async with self.svc.db.session() as s:
            fetched = dict((await s.execute(
                select(RepoMeta.repo_key, RepoMeta.fetched_at)
                .where(RepoMeta.repo_key.in_(list(pending))))).all())
            # Read before the README, links and release were kept: read again.
            old_shape = set((await s.execute(
                select(RepoMeta.repo_key).where(RepoMeta.repo_key.in_(list(pending)), RepoMeta.links.is_(None)))).scalars())
        return [repo for key, repo in pending.items()
                if key not in fetched or key in old_shape or utc(fetched[key]) < cutoff]

    async def drain(self) -> None:
        """Wait for the reads already noted (tests, and a clean shutdown)."""
        while self._task is not None and not self._task.done():
            await asyncio.shield(self._task)

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        self._pending.clear()
