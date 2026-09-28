"""No committed fixture may carry someone else's credential.

Public GitHub issues contain leaked API keys — in bug reports, and in the test
fixtures of secret-scanning projects. Crawling them is unavoidable. Shipping them
inside a submitted artifact is a choice, and this file is where that choice is
enforced rather than remembered.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from holt.evidence.fixtures import FixtureProvider, redact_records, write_fixture
from holt.evidence.redact import CREDENTIAL_PATTERNS, MARKER, redact_payload
from holt.types import T_CUTOFF, EvidenceRecord, Window

BEFORE = T_CUTOFF - timedelta(days=1)
LIVE_LOOKING_PAT = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


def record(payload):
    return EvidenceRecord("issue:a/b#1:opened", "github", "https://x", BEFORE, payload)


def test_a_token_in_an_issue_body_does_not_survive_capture():
    payload, hits = redact_payload({"body": f"my key is {LIVE_LOOKING_PAT} please help"})
    assert hits >= 1
    assert LIVE_LOOKING_PAT not in payload["body"]
    assert MARKER in payload["body"]


def test_the_record_says_it_was_redacted():
    """A reader must be able to tell scrubbed evidence from evidence as captured."""
    payload, _ = redact_payload({"body": LIVE_LOOKING_PAT})
    assert payload["redacted"] is True


def test_evidence_without_credentials_is_left_exactly_alone():
    """Over-eager scrubbing would quietly destroy the evidence being cited."""
    original = {
        "body": "see commit 183cfa71568e398c8b419f9a763442344b352eda for the fix",
        "title": "sk- is a prefix, not a key",
        "labels": ["good first issue"],
    }
    payload, hits = redact_payload(dict(original))
    assert hits == 0
    assert payload == original
    assert "redacted" not in payload


def test_an_obfuscated_token_beside_a_real_one_goes_too():
    """One captured issue printed its token backwards next to the real one.

    A format matcher cannot catch the reversed copy, so a record already known to
    be leaking gets the blunter treatment as well.
    """
    reversed_copy = "8od7BGNsQ1z0BJk8iMNLxqrDVPTOH1X0B7rf"
    payload, _ = redact_payload({"body": f"{LIVE_LOOKING_PAT} reversed: {reversed_copy}"})
    assert reversed_copy not in payload["body"]


def test_capture_scrubs_before_hashing(tmp_path):
    """The committed hash must describe the committed bytes, not the crawled ones."""
    path = write_fixture("a/b", Window.PRE_T, [record({"body": LIVE_LOOKING_PAT})], root=tmp_path)
    on_disk = json.loads(path.read_text())
    assert on_disk["credentials_redacted"] == 1
    assert LIVE_LOOKING_PAT not in path.read_text()
    # Loads without a hash complaint: scrub and hash happened in the right order.
    loaded = FixtureProvider(Window.PRE_T, root=tmp_path).fetch("a/b")
    assert MARKER in loaded[0].payload["body"]


def test_redaction_preserves_evidence_identity():
    """A scrubbed record keeps its id, so every citation still resolves."""
    scrubbed, _ = redact_records([record({"body": LIVE_LOOKING_PAT})])
    assert scrubbed[0].evidence_id == "issue:a/b#1:opened"
    assert scrubbed[0].timestamp == BEFORE


# The scan is split so pytest-xdist can spread it over workers: the fixtures
# are ~300 MB and one test reading all of them was the slowest in the suite.
SHARDS = 8
FIXTURES = sorted(Path("fixtures").rglob("*.json"))
# Every tier-1 pattern matches only ASCII letters, digits, `_` and `-`, which
# JSON never escapes, so a credential in any decoded string also matches the
# raw file. A file with no raw match needs no parsing; one with a match (a
# possible false alarm, say inside a key) gets the full check below.
RAW = [re.compile(p.pattern.encode()) for p in CREDENTIAL_PATTERNS]


def test_the_raw_prefilter_sees_every_credential_json_can_hold():
    """The shortcut above is only safe if it never hides a hit from the full check."""
    for text in (f"é\n{LIVE_LOOKING_PAT}\t\"x\"", f"\\{LIVE_LOOKING_PAT}", f"<{LIVE_LOOKING_PAT}>"):
        for ascii_only in (True, False):
            raw = json.dumps({"payload": {"body": text}}, ensure_ascii=ascii_only).encode()
            assert any(p.search(raw) for p in RAW), (text, ascii_only)


@pytest.mark.parametrize("shard", range(SHARDS))
def test_no_committed_fixture_carries_a_credential(shard):
    """The guard that would have caught this before it was ever committed."""
    assert len(FIXTURES) > 50
    offenders = []
    for path in FIXTURES[shard::SHARDS]:
        raw = path.read_bytes()
        if not any(p.search(raw) for p in RAW):
            continue
        data = json.loads(raw)
        if "records" not in data:
            continue
        _, hits = redact_records(
            EvidenceRecord(
                r["evidence_id"], r["source"], r["url"], BEFORE, r["payload"]
            )
            for r in data["records"]
        )
        if hits:
            offenders.append(f"{path} ({hits})")
    assert not offenders, (
        "credential-shaped strings in committed evidence: "
        + ", ".join(offenders)
        + " — run `uv run python scripts/redact_fixtures.py`"
    )
