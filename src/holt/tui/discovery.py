"""Finding candidates, live or from a recording, as rows rather than markdown.

Two ways in, and the default matters. **Live** is what the feature is for: a
GitHub search over what you said you wanted, screened for free as each candidate
comes back. **Replaying a recording** is a demo of that — the same screening over
committed fixtures, no token, no network — and it is now something you ask for
rather than the thing the screen opens on. A page of repositories from a search
somebody else ran in June is not a result about you, and presenting it as the
first thing `ctrl+f` does made the feature look like a canned list.

Screening is free in both directions: `screen_records` runs no model, so a live
sweep spends GitHub API quota and a minute of waiting, and nothing else. The
model cost lives where it always did — pressing enter on a row starts an
ordinary assessment run.

The engine returns rendered markdown, which is the right output for a
file and the wrong one for a screen you navigate: the interface needs the slug
under the cursor so that pressing enter can assess it. Parsing the markdown back
into data would make the interface depend on how the report is worded, which is
exactly the coupling the whole TUI has avoided.

So the screening step is reassembled here from `discover`'s own public parts —
the session manifest, `screen_root`, and `screen_records`, which is where the
rule actually lives. Nothing about *what survives* is decided in this file. It
walks the same candidates in the same order and asks the same function.

The full analysis of survivors is deliberately not reproduced. Assessing a
repository already has a path through this interface, and a second one would be
the duplicate way of running a stage that this feature must not become: pressing
enter on a row starts an ordinary run.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from holt import discover
from holt.evidence.fixtures import FixtureProvider
from holt.profile import Profile
from holt.types import Window

#: The session that ships in the repository. Replays with no token and no key.
#: Reachable on request; never what the screen opens on.
DEFAULT_SESSION = "demo"

#: How many candidates a live search sources. The same default `holt discover`
#: uses, so the two produce comparable sweeps.
DEFAULT_LIMIT = 25

#: What a screening category means in words, since the engine's labels are
#: short. A category added later falls through to its own label rather than
#: being dropped, so a new reason still says something.
CATEGORY_WORDS = {
    "registry": "a catalogue, not software",
    "inactive": "not active enough",
    "no_outsiders": "no outsider has landed work",
    "unclear": "not enough evidence",
    "archived": "archived",
    "mirror": "a mirror of work done elsewhere",
}


def cut_reason(category: str) -> str:
    return CATEGORY_WORDS.get(category, category.replace("_", " "))


@dataclass(slots=True)
class Row:
    """One candidate the recorded search turned up, and what screening said."""

    slug: str
    description: str
    language: str
    stars: int
    verdict: str
    #: `None` when the candidate survived screening; otherwise why it was cut.
    category: str | None
    reason: str

    @property
    def survived(self) -> bool:
        return self.category is None


def row_for(candidate: Any, screened: Any) -> Row:
    """One screened candidate as a row. The only place a `Row` is built.

    Live and replay reach screening by different routes and must not describe
    it differently, so both come through here.
    """
    return Row(
        slug=candidate.slug,
        description=(candidate.description or "").strip(),
        language=candidate.language or "",
        stars=candidate.stars,
        verdict=getattr(screened.verdict, "value", str(screened.verdict)),
        category=screened.category,
        reason=screened.trace[0] if screened.trace else "",
    )


@dataclass(slots=True)
class Session:
    name: str
    profile_description: str
    queries: list[str]
    as_of: datetime
    rows: list[Row]
    #: Candidates in the manifest with no recorded evidence. Listed, never
    #: silently dropped — a search that quietly loses candidates is a search
    #: whose count means nothing.
    skipped: list[str]

    @property
    def survivors(self) -> list[Row]:
        return [r for r in self.rows if r.survived]


def missing_token() -> str | None:
    """What a live search needs, or None. Checked before a thread starts.

    Only `GITHUB_TOKEN`: screening calls no model, so an OpenAI key is not
    required to find candidates — only to assess one afterwards. Saying
    otherwise would turn a free feature into one that looks paid.
    """
    from holt import credentials

    if credentials.ensure_token():
        return None
    return "Holt needs a GitHub token to search. Choose this again to add one."


@dataclass
class Search:
    """A live search, running on a worker thread.

    The same shape as `holt.tui.session.Session`, for the same reason: sourcing
    twenty-five repositories and reading a page of pull-request threads from
    each is a minute of network, and an interface that blocks on it looks
    broken. The worker appends; the screen reads what it has not drawn yet.
    There is no message schema and no lock — one writer, append-only, and a
    cursor on the reading side, which is how the run stream already works.

    Rows arrive in the order the search returned them, cut ones included. They
    are deliberately not re-sorted as they land: screening says a candidate is
    worth a closer look, not that it is better than another one, and a list
    that rearranged itself under the cursor would be asserting an order the
    engine never computed.
    """

    profile: Profile
    limit: int = DEFAULT_LIMIT
    rows: list[Row] = field(default_factory=list)
    #: The searches GitHub was actually asked, filled in before any row lands.
    queries: list[str] = field(default_factory=list)
    as_of: datetime | None = None
    #: How many candidates the search sourced. Zero until sourcing returns.
    total: int = 0
    #: Candidates GitHub would not let us read. Listed, never counted as
    #: rejections — "we could not look" is not "we looked and it failed".
    skipped: list[str] = field(default_factory=list)
    error: str | None = None
    finished: bool = False
    cancelled: bool = False
    _thread: threading.Thread | None = None
    _cancel: threading.Event = field(default_factory=threading.Event)

    # ─── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("search already started")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Stop after the candidate in flight. Rows already screened are kept:
        they were free, and they are still true."""
        self._cancel.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def survivors(self) -> list[Row]:
        return [r for r in self.rows if r.survived]

    @property
    def screened(self) -> int:
        return len(self.rows)

    def wait(self, timeout: float | None = None) -> None:
        """Block until the worker exits. Used by tests."""
        if self._thread is not None:
            self._thread.join(timeout)

    def describe(self) -> str:
        """One line of progress, true at every point in the sweep."""
        if self.error:
            return self.error
        if not self.total:
            return "searching GitHub for candidates…"
        head = f"screened {self.screened} of {self.total} at no model cost"
        head += f" · {len(self.survivors)} worth a closer look"
        cut = self.screened - len(self.survivors)
        if cut:
            head += f" · {cut} cut"
        if self.skipped:
            head += f" · {len(self.skipped)} could not be read"
        if self.cancelled:
            head += " · stopped"
        return head

    # ─── the worker ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            search = discover.source_live(self.profile, self.limit)
            # Set before the first row so a screen drawing progress can say
            # what was searched for while the slow half is still running.
            self.queries = list(search.queries)
            self.as_of = search.as_of
            self.total = len(search.candidates)
            for step in search.screen(self._cancel.is_set):
                if step.result is None:
                    self.skipped.append(step.candidate.slug)
                    continue
                self.rows.append(row_for(step.candidate, step.result))
            self.cancelled = self._cancel.is_set()
        except Exception as exc:  # noqa: BLE001 - reported, never a traceback
            from holt.tui.session import readable

            self.error = readable(exc)
        finally:
            self.finished = True


def manifest_path_exists(name: str = DEFAULT_SESSION) -> bool:
    """Whether a recorded session is on disk. Used to skip, never to guess."""
    try:
        return discover.manifest_path(name).is_file()
    except OSError:
        return False


def available() -> list[str]:
    """Recorded session names, newest first by name."""
    try:
        return sorted(p.stem for p in discover.DISCOVER_ROOT.glob("*.json"))
    except OSError:
        return []


def load(name: str = DEFAULT_SESSION, days: int | None = None) -> Session:
    """Replay a recorded session's screening step. No model, no network.

    Raises `FileNotFoundError` when the session is not on disk, which the screen
    turns into a sentence rather than a traceback.
    """
    manifest: dict[str, Any] = json.loads(discover.manifest_path(name).read_text(encoding="utf-8"))
    as_of = datetime.fromisoformat(manifest["as_of"])

    from holt.profile import Profile

    profile = Profile(**manifest["profile"])
    if days:
        profile.days = days

    provider = FixtureProvider(
        Window.PRE_T, root=discover.screen_root(name), cutoff=as_of
    )

    rows: list[Row] = []
    skipped: list[str] = []
    for raw in manifest["candidates"]:
        candidate = discover.Candidate(**raw)
        try:
            records = provider.fetch(candidate.slug)
        except FileNotFoundError:
            skipped.append(candidate.slug)
            continue
        # The rule lives in the engine. This asks it; it does not restate it.
        screened = discover.screen_records(candidate, records, profile.days)
        rows.append(row_for(candidate, screened))

    # Survivors first: they are the ones you can act on. Within each group the
    # search's own order is kept, because reordering would be a claim about
    # which candidate is better and screening does not make one.
    rows.sort(key=lambda r: not r.survived)

    return Session(
        name=name,
        profile_description=profile.describe(),
        queries=list(manifest.get("queries", [])),
        as_of=as_of,
        rows=rows,
        skipped=skipped,
    )
