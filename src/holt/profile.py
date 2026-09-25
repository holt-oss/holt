"""What the contributor tells us, stored so they say it once.

The profile is *stated*, not inferred. An earlier version tried to infer it from
the person's GitHub history and was cut on data: the median contributor in our
pool has one merged pull request and five touched files, and 98% of
cross-repository area overlap was generic-path collisions (`src`, `docs`,
`tests`). Inferring "you work on Python developer tooling" from one pull request
would be invention. Asking is more honest and more accurate.

Every question here maps to something that changes the output, or it is not
asked. Languages and topics are search qualifiers — sourcing only, no claim.
Days feeds `verdict.py`, where the slow-response threshold is `days * 24`.
Contribution type is matched against where outsider work actually landed.
Experience level is deliberately absent: nothing downstream could map it to a
threshold, so asking it would be decoration.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from holt.agent.verdict import DEFAULT_CONTRIBUTOR_DAYS

# Contribution types we can actually check, each against the directories where
# outsider work merged. Anything else would be a question that changes nothing.
CONTRIBUTION_AREAS: dict[str, tuple[str, ...]] = {
    "docs": ("doc", "docs", "documentation", "wiki", "website"),
    "tests": ("test", "tests", "testing", "spec", "specs"),
    "ci": (".github", ".gitlab", "ci", ".ci", "workflows"),
    "code": (),  # the default kind of contribution; every non-docs area counts
}


def config_path() -> Path:
    from holt import paths

    return paths.config_dir() / "profile.toml"


@dataclass(slots=True)
class Profile:
    languages: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    contributions: list[str] = field(default_factory=list)
    days: int = DEFAULT_CONTRIBUTOR_DAYS

    def describe(self) -> str:
        parts = [" + ".join(self.languages + self.topics) or "any repository"]
        parts.append(f"{self.days} day{'s' if self.days != 1 else ''}")
        if self.contributions:
            parts.append(", ".join(self.contributions))
        return ", ".join(parts)


def _csv(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = value.split(",")
    return [v.strip().lower() for v in value if v.strip()]


def load(path: Path | None = None) -> Profile | None:
    path = path or config_path()
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return Profile(
        languages=_csv(data.get("languages")),
        topics=_csv(data.get("topics")),
        contributions=_csv(data.get("contributions")),
        days=int(data.get("days", DEFAULT_CONTRIBUTOR_DAYS)),
    )


def save(profile: Profile, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    def toml_list(values: list[str]) -> str:
        return "[" + ", ".join(f'"{v}"' for v in values) + "]"

    path.write_text(
        f"languages = {toml_list(profile.languages)}\n"
        f"topics = {toml_list(profile.topics)}\n"
        f"contributions = {toml_list(profile.contributions)}\n"
        f"days = {profile.days}\n",
        encoding="utf-8",
    )
    return path


def from_args(args, stored: Profile | None = None) -> Profile:
    """Flags override the stored profile field by field; absent flags fall back."""
    stored = stored or Profile()
    return Profile(
        languages=_csv(getattr(args, "lang", None)) or stored.languages,
        topics=_csv(getattr(args, "topic", None)) or stored.topics,
        contributions=_csv(getattr(args, "contribution", None)) or stored.contributions,
        days=getattr(args, "days", None) or stored.days,
    )


def ask(existing: Profile | None = None) -> Profile:
    """The interactive form. Four questions, each of which changes the output."""
    current = existing or Profile()

    def prompt(question: str, default: str) -> str:
        suffix = f" [{default}]" if default else ""
        answer = input(f"  {question}{suffix} > ").strip()
        return answer or default

    languages = _csv(prompt("Languages you want to work in", ", ".join(current.languages)))
    topics = _csv(prompt("What kind of project (topics)", ", ".join(current.topics)))
    contributions = _csv(prompt(
        f"What you want to contribute ({'/'.join(CONTRIBUTION_AREAS)})",
        ", ".join(current.contributions),
    ))
    days_raw = prompt("How many days you actually have", str(current.days))
    try:
        days = max(1, int(days_raw))
    except ValueError:
        days = current.days
    return Profile(languages=languages, topics=topics,
                   contributions=contributions, days=days)
