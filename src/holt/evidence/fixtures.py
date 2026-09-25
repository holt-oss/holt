"""Committed evidence, so the eval runs with no token and no rate limits.

Fixtures are the reason a judge can reproduce the headline number from a clean
clone with no credentials. They are also where the holdout is easiest to break
by accident — a hand-edited file, a re-capture against the wrong window — so the
loader re-asserts the date bounds on every read rather than trusting the file.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from holt.evidence.provider import EvidenceProvider
from holt.evidence.redact import redact_payload
from holt.types import T_CUTOFF, EvidenceRecord, Window

# Committed evidence lives in a repository clone, relative to its root. Only
# fixture (replay) runs read it; a live run never does. `HOLT_FIXTURE_ROOT`
# points an installed copy, or a server, at a checkout elsewhere.
FIXTURE_ROOT = Path("fixtures")


def fixture_root() -> Path:
    return Path(os.environ.get("HOLT_FIXTURE_ROOT") or FIXTURE_ROOT)


def slug_to_filename(repo_slug: str) -> str:
    return repo_slug.replace("/", "__") + ".json"


def record_to_dict(record: EvidenceRecord) -> dict[str, Any]:
    return {
        "evidence_id": record.evidence_id,
        "source": record.source,
        "url": record.url,
        "timestamp": record.timestamp.isoformat(),
        "payload": record.payload,
    }


def record_from_dict(data: dict[str, Any]) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=data["evidence_id"],
        source=data["source"],
        url=data["url"],
        timestamp=datetime.fromisoformat(data["timestamp"]),
        payload=data["payload"],
    )


def content_hash(records: Iterable[EvidenceRecord]) -> str:
    """Stable over evidence content, independent of capture order or metadata."""
    blob = json.dumps(
        sorted((record_to_dict(r) for r in records), key=lambda d: d["evidence_id"]),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def redact_records(records: Iterable[EvidenceRecord]) -> tuple[list[EvidenceRecord], int]:
    """Strip third-party credentials from evidence on its way to disk.

    Public issues contain leaked keys. Reading them is unavoidable; shipping them
    in a committed fixture is a choice, and this is the point where we decline it.
    """
    out, removed = [], 0
    for record in records:
        payload, hits = redact_payload(record.payload)
        removed += hits
        out.append(
            record if not hits else EvidenceRecord(
                evidence_id=record.evidence_id,
                source=record.source,
                url=record.url,
                timestamp=record.timestamp,
                payload=payload,
            )
        )
    return out, removed


def write_fixture(
    repo_slug: str,
    window: Window,
    records: Iterable[EvidenceRecord],
    root: Path | None = None,
    cutoff: datetime = T_CUTOFF,
) -> Path:
    # Scrubbed before the hash is taken, so the committed hash describes the
    # committed bytes and a later re-capture of the same evidence reproduces it.
    records, removed = redact_records(records)
    root = fixture_root() if root is None else Path(root)
    path = root / window.value / slug_to_filename(repo_slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "repo": repo_slug,
                "window": window.value,
                "cutoff": cutoff.isoformat(),
                "captured_at": datetime.now(UTC).isoformat(),
                "content_sha256": content_hash(records),
                "credentials_redacted": removed,
                "records": [record_to_dict(r) for r in records],
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


class FixtureProvider(EvidenceProvider):
    """Reads committed evidence. No network, no token, no rate limit."""

    # A frozen capture; see `EvidenceProvider.judges_recency`.
    judges_recency = False

    def __init__(
        self,
        window: Window,
        root: Path | None = None,
        cutoff: datetime = T_CUTOFF,
    ) -> None:
        super().__init__(window, cutoff)
        self.root = fixture_root() if root is None else Path(root)
        self._loaded: dict[str, EvidenceRecord] = {}

    def path_for(self, repo_slug: str) -> Path:
        return self.root / self.window.value / slug_to_filename(repo_slug)

    def _fetch_raw(self, request: str, /, **params: object) -> Iterable[EvidenceRecord]:
        path = self.path_for(request)
        if not path.exists():
            raise FileNotFoundError(
                f"No {self.window.value} fixture for {request} at {path}. "
                "Capture it in live mode first; fixture mode never reaches the network."
            )
        data = json.loads(path.read_text(encoding="utf-8"))

        if data["window"] != self.window.value:
            raise ValueError(
                f"{path} holds {data['window']} evidence but was opened as "
                f"{self.window.value}; the holdout sides must not be mixed"
            )

        records = [record_from_dict(r) for r in data["records"]]
        expected = data.get("content_sha256")
        if expected and (actual := content_hash(records)) != expected:
            raise ValueError(
                f"{path} content hash mismatch: recorded {expected[:12]}, "
                f"computed {actual[:12]}. The fixture was edited after capture."
            )
        self._loaded.update({r.evidence_id: r for r in records})
        return records

    def _resolve_raw(self, evidence_id: str) -> EvidenceRecord | None:
        return self._loaded.get(evidence_id)
