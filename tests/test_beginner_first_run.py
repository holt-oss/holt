"""What someone who installed Holt from PyPI meets on their first run.

No clone, no fixtures, no API key, maybe no GitHub token. Every path here has to
end in either an answer or one plain sentence with the command that fixes it.
None of these tests touch the network.
"""

from __future__ import annotations

import json
import os
import stat
import sys

import httpx
import pytest

from holt import cli, credentials, model, paths
from holt.report import Assessment, Claim, Verdict


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOLT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("HOLT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("HOLT_DISABLE_GH", "1")
    return tmp_path


# ─── where things live ──────────────────────────────────────────────────────


def test_nothing_is_relative_to_the_current_directory(home):
    from holt.tui import store
    from holt.tui.session import RunOptions

    for path in (paths.config_dir(), paths.data_dir(), store.Store().root,
                 RunOptions(repo="a/b", replay=False).run_root,
                 model.models_config_path(), credentials.token_path()):
        assert path.is_absolute(), path


def test_platform_defaults(monkeypatch, tmp_path):
    for name in ("HOLT_CONFIG_DIR", "HOLT_DATA_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)

    monkeypatch.setattr(sys, "platform", "linux")
    assert paths.data_dir() == tmp_path / ".local" / "share" / "holt"
    assert paths.config_dir() == tmp_path / ".config" / "holt"

    monkeypatch.setattr(sys, "platform", "darwin")
    assert paths.data_dir() == tmp_path / "Library" / "Application Support" / "holt"

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert paths.config_dir() == tmp_path / "Roaming" / "holt"
    assert paths.data_dir() == tmp_path / "Local" / "holt"


# ─── the GitHub token ───────────────────────────────────────────────────────


def test_a_saved_token_is_private_and_used(home):
    path = credentials.save_token("ghp_example")
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    os.environ.pop("GITHUB_TOKEN", None)
    assert credentials.find_token() == ("ghp_example", str(path))
    assert credentials.ensure_token()
    assert os.environ["GITHUB_TOKEN"] == "ghp_example"


def test_the_environment_wins_over_a_saved_token(home, monkeypatch):
    credentials.save_token("saved")
    monkeypatch.setenv("GITHUB_TOKEN", "exported")
    assert credentials.find_token() == ("exported", "GITHUB_TOKEN")


def test_gh_is_the_last_resort(home, monkeypatch):
    monkeypatch.delenv("HOLT_DISABLE_GH")
    monkeypatch.setattr(credentials, "gh_token", lambda: "from-gh")
    assert credentials.find_token() == ("from-gh", "gh auth token")


def test_a_garbage_token_is_refused(home):
    with pytest.raises(ValueError):
        credentials.save_token('bad"token')
    with pytest.raises(ValueError):
        credentials.save_token("   ")


def test_no_token_is_a_sentence_with_the_link(home, capsys):
    code = cli.main(["analyze", "nobody-has/this-fixture", "--live"])
    err = capsys.readouterr().err
    assert code == 2
    assert credentials.TOKEN_URL in err
    assert "holt token" in err
    assert "Traceback" not in err


# ─── rules-only is the default ──────────────────────────────────────────────


def test_no_model_set_up_means_rules_only(home, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    code = cli.main(["analyze", "NixOS/nixpkgs"])
    out, err = capsys.readouterr()
    assert code == 0
    assert "Worth your time" in out or "worth your time" in out.lower()
    assert "rules-only" in err
    assert "Gemini" in err


def test_json_output(home, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["analyze", "NixOS/nixpkgs", "--json"]) == 0
    out, err = capsys.readouterr()
    data = json.loads(out)
    assert data["repo"] == "NixOS/nixpkgs"
    assert data["mode"] == "rules"
    assert data["headline"] in {"Worth your time", "Not worth your time",
                                "Not enough evidence"}
    assert data["stats"]["outsider_attempts"] > 0
    assert err == ""  # nothing chatty around machine-readable output


def test_compare_shows_headlines_not_enum_names(home, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert cli.main(["compare", "NixOS/nixpkgs", "is-a-dev/register"]) == 0
    out = capsys.readouterr().out
    assert "not_viable" not in out and "| viable" not in out
    assert "worth your time" in out.lower()


def test_openrouter_is_a_named_provider(monkeypatch):
    config = model.ModelsConfig(provider="openrouter")
    assert config.resolved_base_url() == "https://openrouter.ai/api/v1"
    assert config.resolved_key_env() == "OPENROUTER_API_KEY"
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert not model.model_ready(config)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    assert model.model_ready(config)


def test_a_local_model_needs_no_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    assert model.model_ready(model.ModelsConfig(provider="ollama"))


# ─── errors never reach the reader as tracebacks ───────────────────────────


def _status(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.github.com/graphql")
    return httpx.HTTPStatusError("x", request=request, response=httpx.Response(code, request=request))


@pytest.mark.parametrize(
    "exc,expected",
    [
        (_status(401), "holt token"),
        (_status(403), "rate limit"),
        (_status(502), "Try again"),
        (httpx.ConnectError("boom"), "internet connection"),
        (RuntimeError("a/b not found or not public"), "could not find a/b"),
        (RuntimeError("GITHUB_TOKEN is not set. Live mode needs a token"), credentials.TOKEN_URL),
        (ZeroDivisionError("weird"), "report it"),
    ],
)
def test_errors_are_plain_english(exc, expected):
    message = cli.friendly_error(exc, "a/b")
    assert expected.lower() in message.lower()
    for jargon in ("fixture", "replay", "pre_t", "Stage D", "Traceback"):
        assert jargon not in message


def test_typed_github_errors_are_reworded():
    from holt.evidence import errors

    assert "holt token" in cli.friendly_error(errors.AuthError(), "a/b")
    assert "could not find a/b" in cli.friendly_error(errors.RepoNotFound("a/b"), "a/b").lower()
    assert "holt analyze a/b" in cli.friendly_error(errors.RateLimited(120), "a/b")
    assert "holt analyze a/b" in cli.friendly_error(errors.UpstreamError(), "a/b")


def test_retry_hints_name_the_command_that_failed():
    from holt.evidence import errors

    assert "holt start a/b" in cli.friendly_error(errors.RateLimited(60), "a/b", "start")
    assert "holt start --lang python" in cli.friendly_error(errors.UpstreamError(), None, "start")
    assert "holt analyze a/b" in cli.friendly_error(errors.UpstreamError(), "a/b", "models")


def test_start_uses_a_saved_token(home, monkeypatch, capsys):
    from holt import starter

    credentials.save_token("saved-token")
    monkeypatch.delenv("GITHUB_TOKEN")
    seen = {}

    def fake_find(languages, topics, hacktoberfest, token, **kw):
        seen["token"] = token
        raise starter.RateLimited(60)

    monkeypatch.setattr(starter, "find", fake_find)
    assert cli.main(["start", "--lang", "python"]) == 1
    assert seen["token"] == "saved-token"
    err = capsys.readouterr().err
    assert "holt start --lang python" in err and "Traceback" not in err


def test_a_bad_repository_name_says_what_to_type(capsys):
    assert cli.main(["analyze", "gitlab.com/a/b"]) == 1
    err = capsys.readouterr().err
    assert "pallets/flask" in err and "Traceback" not in err


def test_main_catches_what_a_command_raises(home, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(cli.pipeline, "analyze", boom)
    code = cli.main(["analyze", "NixOS/nixpkgs", "--no-model"])
    err = capsys.readouterr().err
    assert code == 1
    assert "internet connection" in err
    assert "Traceback" not in err


def test_help_has_no_statistics_jargon(capsys):
    for argv in (["--help"], ["analyze", "--help"], ["compare", "--help"],
                 ["next", "--help"], ["discover", "--help"], ["models", "--help"]):
        with pytest.raises(SystemExit):
            cli.main(argv)
        text = capsys.readouterr().out
        for jargon in ("MCC", "p-value", "hit@", "Stage D", "fixture"):
            assert jargon not in text, (argv, jargon)


# ─── the report ─────────────────────────────────────────────────────────────


def test_markdown_is_plain_when_piped(capsys):
    cli.emit_markdown("# Title\n\n**bold**")
    assert capsys.readouterr().out.startswith("# Title")


def test_evidence_in_the_report_is_clickable():
    out = Assessment(
        repo="a/b", verdict=Verdict.VIABLE, summary="s",
        claims=[Claim("merged", "pr:a/b#9:opened")],
    ).render()
    assert "https://github.com/a/b/pull/9" in out
