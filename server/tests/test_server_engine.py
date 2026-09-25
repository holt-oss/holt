"""The real engine behind the API, over the committed replay fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from holt_server import crypto, engine, repos
from holt_server import report as report_mod
from holt_server.errors import ApiError

from holt.agent import pipeline
from holt.evidence.errors import AuthError, RateLimited, RepoNotFound, UpstreamError
from holt.evidence.fixtures import FixtureProvider
from holt.model import ReplayModel
from holt.report import Assessment, Claim, Verdict
from holt.types import T_CUTOFF, Window

ROOT = Path(__file__).resolve().parents[2]
REPO = "NixOS/nixpkgs"
TRAJECTORY = ROOT / "fixtures" / "trajectories" / "NixOS__nixpkgs.jsonl"


def fixture_provider(repo=None, as_of=None):
    return FixtureProvider(Window.PRE_T, root=ROOT / "fixtures")


def replay_harness(make_harness, **overrides):
    h = make_harness(OPENROUTER_API_KEY="sk-unused", **overrides)
    h.svc.analysis_fn = engine.analyze
    h.svc.provider_factory = fixture_provider
    h.svc.model_factory = lambda spec: ReplayModel(TRAJECTORY)
    return h


def check_report_shape(report: dict, mode: str) -> None:
    keys = {"repo", "mode", "days", "verdict", "headline", "summary", "stats",
            "decided_by", "unknowns", "landing", "never_landed", "evidence",
            "evidence_until", "generated_at", "cost"}
    assert set(report) == keys
    assert report["repo"] == REPO and report["mode"] == mode
    assert report["verdict"] in ("viable", "not_viable", "insufficient_evidence")
    assert set(report["stats"]) == {
        "outsider_attempts", "outsider_merged", "distinct_outsiders",
        "first_time_merged_authors", "no_reply", "median_first_response_hours", "bot_share"}
    for item in report["evidence"]:
        assert item["url"].startswith("https://github.com/"), item
        assert set(item) == {"id", "url", "kind", "value", "text", "quote"}
    for area in report["landing"]:
        assert set(area) == {"path", "merged", "attempted"}
    for area in report["never_landed"]:
        assert set(area) == {"path", "attempted"}
    assert report["evidence_until"] == "2026-06-01T00:00:00Z"
    # What a beginner reads is plain English. (`kind`/`value` are machine keys.)
    prose = " ".join([report["headline"], report["summary"] or "", *report["decided_by"],
                      *report["unknowns"], *(e["text"] for e in report["evidence"])])
    for jargon in ("not_viable", "MCC", "repo_kind", "insufficient_evidence"):
        assert jargon not in prose


def test_rules_report_end_to_end(make_harness):
    h = replay_harness(make_harness)
    job = h.post("/v1/analyses", {"repo": "nixos/NIXPKGS"}).json()["job_id"]
    body = h.wait(job)
    assert body["status"] == "done", body
    report = body["report"]
    check_report_shape(report, "rules")

    expected, trace = pipeline.analyze_without_model(
        REPO, fixture_provider(), 7, as_of=T_CUTOFF)
    assert report["verdict"] == expected.verdict.value
    assert report["stats"]["outsider_attempts"] == trace.signals.outsider_threads
    assert report["summary"] is None and report["cost"] is None
    assert report["landing"], "nixpkgs has well-known landing areas"
    # Even with no AI, the counts come with pull requests to click through to.
    values = [e["value"] for e in report["evidence"] if e["kind"] == "outsider_pr"]
    assert values.count("merged") == 4 and values.count("no_reply") == 4
    assert all("/pull/" in e["url"] for e in report["evidence"])
    assert report["decided_by"]


def test_ai_report_end_to_end(make_harness):
    h = replay_harness(make_harness)
    job = h.post("/v1/analyses", {"repo": REPO, "mode": "ai"}, user="u1").json()["job_id"]
    body = h.wait(job)
    assert body["status"] == "done", body
    report = body["report"]
    check_report_shape(report, "ai")
    assert report["summary"]
    assert report["evidence"], "replayed run cites evidence"
    assert report["cost"]["input_tokens"] > 0
    assert any(e["kind"] == "outcome" for e in report["evidence"])
    assert all(e["url"].startswith("https://github.com/NixOS/nixpkgs")
               for e in report["evidence"])


# --- serializer ---------------------------------------------------------------


def test_claim_parsing():
    records = {}
    item = report_mod.evidence_item(
        "merged after review — “thanks, merging”", "pr:o/r#5:opened", records)
    assert item == {"id": "pr:o/r#5:opened", "url": "https://github.com/o/r/pull/5",
                    "kind": "outcome", "value": "merged_after_review",
                    "text": "Merged after review", "quote": "thanks, merging"}
    item = report_mod.evidence_item("ignored, nothing said", "pr:o/r#6:opened", records)
    assert item["kind"] == "outcome" and item["quote"] is None
    item = report_mod.evidence_item(
        "onboarding: substantive (AI's reading, not a quote: CONTRIBUTING explains setup)",
        "repo:o/r:contributing", records)
    assert (item["kind"], item["value"], item["text"]) == (
        "onboarding", "substantive", "CONTRIBUTING explains setup")
    assert item["url"] == "https://github.com/o/r"
    assert report_mod.evidence_item("x", None, records) is None
    item = report_mod.evidence_item("is archived: True", "repo:o/r:meta", records)
    assert (item["kind"], item["value"], item["text"]) == (
        "is_archived", "True", "Is archived: True")


def test_ai_all_claims_dropped_is_stated():
    from holt.agent.signals import compute

    a = Assessment(repo="o/r", verdict=Verdict.VIABLE, summary="s", claims=[],
                   dropped_claims=3, limits="Could not tell X.\nCould not tell Y.",
                   as_of=datetime(2026, 6, 1, tzinfo=UTC))
    out = report_mod.build(repo="o/r", mode="ai", assessment=a, signals=compute({}),
                           records=[], cost=None)
    assert out["unknowns"][0] == report_mod.ALL_DROPPED_UNKNOWN
    assert "Could not tell X." in out["unknowns"]
    assert out["headline"] == "Worth your time"


def test_claim_without_url_is_left_out():
    item = report_mod.evidence_item("a: b", "weird-id", {})
    assert item is None
    a = Assessment(repo="o/r", verdict=Verdict.VIABLE, summary="",
                   claims=[Claim("a: b", "weird-id")])
    from holt.agent.signals import compute

    out = report_mod.build(repo="o/r", mode="rules", assessment=a, signals=compute({}),
                           records=[])
    assert out["evidence"] == []


# --- progress ------------------------------------------------------------------


def test_progress_never_goes_backwards_and_holds_done():
    seen = []
    p = engine.Progress(lambda s, v: seen.append((s, v)))
    p("A", 0.5)
    p("B", 0.2)
    p("B", 0.2)
    p("C", 1.5)
    p("Done", 1.0)
    assert seen == [("A", 0.5), ("B", 0.5), ("C", 0.99)]


def test_engine_stages_reach_the_job():
    calls = []
    report = engine.analyze(repo=REPO, mode="rules", days=7, provider=fixture_provider(),
                            model=None, emit=lambda s, v: calls.append((s, v)),
                            as_of=T_CUTOFF)
    stages = [s for s, _ in calls]
    assert stages[0] == "Fetching pull requests"
    assert stages[-1] == engine.FINAL_STAGE and "Done" not in stages
    assert [v for _, v in calls] == sorted(v for _, v in calls)
    assert report["repo"] == REPO


class Failing:
    def __init__(self, exc):
        self.exc = exc

    def fetch(self, repo):
        raise self.exc


@pytest.mark.parametrize("exc, code, retry", [
    (RepoNotFound("o/r"), "not_found", None),
    (RateLimited(42.4), "rate_limited", 42),
    (RateLimited(None), "rate_limited", 600),
    (AuthError("401"), "upstream", None),
    (UpstreamError("HTTP 502"), "upstream", None),
    (ZeroDivisionError(), "internal", None),
])
def test_engine_errors_map_to_api_codes(exc, code, retry):
    with pytest.raises(ApiError) as err:
        engine.analyze(repo="o/r", mode="rules", days=7, provider=Failing(exc), model=None,
                       emit=lambda *a: None, as_of=T_CUTOFF)
    assert (err.value.code, err.value.retry_after) == (code, retry)
    assert "GITHUB_TOKEN" not in err.value.message


# --- small pieces ----------------------------------------------------------------


@pytest.mark.parametrize("raw", [
    "pallets/flask", "https://github.com/pallets/flask", "github.com/pallets/flask.git",
    "https://github.com/pallets/flask/tree/main/src?tab=readme", "http://www.github.com/pallets/flask/",
    "git@github.com:pallets/flask.git", "  pallets/flask  ",
])
def test_repo_normalisation(raw):
    assert repos.normalize(raw) == "pallets/flask"


@pytest.mark.parametrize("raw", ["", "flask", "https://gitlab.com", "a b/c", "-x/y", "o/..",
                                 "https://github.com/pallets"])
def test_repo_rejects(raw):
    with pytest.raises(ApiError) as err:
        repos.normalize(raw)
    assert err.value.code == "invalid_repo"


def test_crypto_roundtrip_and_binding():
    import base64
    import os

    from cryptography.exceptions import InvalidTag

    for secret in ("a passphrase", base64.b64encode(os.urandom(32)).decode()):
        token = crypto.encrypt(secret, "sk-live-1", "user-a")
        assert "sk-live-1" not in token
        assert crypto.decrypt(secret, token, "user-a") == "sk-live-1"
        with pytest.raises(InvalidTag):
            crypto.decrypt(secret, token, "user-b")
        with pytest.raises(InvalidTag):
            crypto.decrypt(secret + "x", token, "user-a")
    with pytest.raises(crypto.SecretKeyMissing):
        crypto.encrypt("", "k", "u")


def test_rate_limiter_window():
    from holt_server.ratelimit import RateLimiter

    t = [0.0]
    rl = RateLimiter(clock=lambda: t[0])
    rl.hit("k", 2)
    rl.hit("k", 2)
    with pytest.raises(ApiError) as err:
        rl.hit("k", 2)
    assert err.value.retry_after == 3600
    t[0] = 3601
    rl.hit("k", 2)


def test_rate_limiter_forgets_idle_keys():
    from holt_server.ratelimit import RateLimiter

    t = [0.0]
    rl = RateLimiter(clock=lambda: t[0])
    for i in range(50):
        rl.hit(f"ip:{i}", 5)
    t[0] = 4000
    rl.hit("ip:new", 5)
    assert len(rl) == 1


def test_model_spec_hides_the_key():
    from holt_server.llm import ModelSpec

    assert "sk-secret" not in repr(ModelSpec("openrouter", "m", "sk-secret"))
