"""What ctrl+p offers.

Textual gives every app a command palette for free, and out of the box it is
entirely the framework's own: Keys, Maximize, Screenshot, Theme. Useful while
building a terminal app, and nothing to do with assessing a repository — someone
who opened it looking for holt's features found a menu about the toolkit holt
happens to be written in.

So holt puts its own commands in front of those. Two kinds, and the second is
the reason this file is worth having:

* **The things the keybindings already do** — assess, discover, models, profile.
  A palette that lists them is how you find a feature whose key you have not
  memorised, which is every feature until you have used it a few times.
* **The things that are true right now** — the runs in flight, and the
  assessments already stored. Those cannot be keybindings, because they are
  data. `stop home-assistant/core` is only offerable while that run exists, and
  the palette is the only surface in the interface that can grow a command for
  it and then lose it again.

The framework's commands are kept, appended after holt's rather than removed:
they cost a line each and someone who wants a screenshot of a verdict should be
able to take one.

They are yielded from *this* provider rather than registered alongside it.
Textual runs every registered provider concurrently and collects hits as they
arrive, and `App.COMMANDS` is a set, so two providers produce an order that
changes between launches — holt's commands on top one time and Textual's the
next. One provider, yielding in a written order, is the only way to say which
comes first and mean it.
"""

from __future__ import annotations

from typing import Callable, Iterable

from textual.command import DiscoveryHit, Hit, Hits, Provider

from holt.tui import store


class HoltCommands(Provider):
    """holt's own entries in the command palette."""

    async def discover(self) -> Hits:
        """What the palette shows before anything is typed."""
        for name, help_text, callback in self._commands():
            yield DiscoveryHit(name, callback, help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, help_text, callback in self._commands():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), callback, help=help_text)

    # ─── the commands themselves ────────────────────────────────────────────

    def _commands(self) -> Iterable[tuple[str, str, Callable[[], None]]]:
        """Name, one-line help, and what it does.

        Rebuilt on every open rather than cached, because half of these are
        about state — a run that has finished must stop being offered as one
        you can stop.
        """
        app = self.app
        yield from self._runs(app)
        yield from self._stored(app)
        yield (
            "assess a repository",
            "type an owner/name and press enter",
            app.go_home,
        )
        yield (
            "find a repository",
            "screen candidates you have not named yet",
            lambda: app.push_screen("discover"),
        )
        yield (
            "models",
            "which model answers each stage, and whether it can be reached",
            lambda: app.push_screen("models"),
        )
        yield (
            "profile",
            "the languages and the time you have, used to rank what to read",
            lambda: app.push_screen("profile"),
        )
        yield ("quit holt", "asks first if a run is still in flight", app.action_quit)
        yield from self._framework(app)

    def _framework(self, app) -> Iterable[tuple[str, str, Callable[[], None]]]:
        """Textual's own commands, last, in the framework's own order."""
        try:
            system = list(app.get_system_commands(self.screen))
        except Exception:  # noqa: BLE001 - the palette opens even if these do not
            return
        for entry in system:
            name, help_text, callback = entry[0], entry[1], entry[2]
            # `discover` is the framework's own flag for "list this before
            # anything is typed". Honoured rather than overridden.
            if len(entry) > 3 and not entry[3]:
                continue
            yield (name, help_text, callback)

    def _runs(self, app) -> Iterable[tuple[str, str, Callable[[], None]]]:
        """One pair of commands per run in flight. First, because they are live."""
        for session in getattr(app, "in_flight", []):
            repo = session.options.repo
            yield (
                f"watch {repo}",
                f"rejoin the assessment in progress · {session.options.mode}",
                lambda s=session: app.watch_run(s),
            )
            yield (
                f"stop {repo}",
                "ends the run and keeps nothing it had computed",
                lambda s=session: app.confirm_stop(s),
            )

    def _stored(self, app) -> Iterable[tuple[str, str, Callable[[], None]]]:
        """Assessments already produced, newest first. Reading one costs nothing."""
        try:
            entries = app.store.all()
        except Exception:  # noqa: BLE001 - a palette must not raise over a bad store
            return
        for entry in entries:
            from holt.report import VERDICT_HEADLINES

            verdict = entry.assessment.verdict
            said = VERDICT_HEADLINES.get(verdict) or str(
                getattr(verdict, "value", verdict)
            ).replace("_", " ")
            age = store.describe_age(entry.age_seconds)
            yield (
                f"open {entry.repo}",
                f"{said} · assessed {age} · {entry.mode}",
                lambda e=entry: app.open_stored(e),
            )
