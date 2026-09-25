"""The model seam stays one seam: providers swap, the contract and the pinned
defaults do not.

The load-bearing property is replay safety: every committed trajectory and
benchmark number was recorded under the pinned OpenAI ids, so the library must
resolve to them unless a caller explicitly opts into the user's configuration.
An eval script inheriting somebody's Ollama config would be a reproducibility
failure that never announces itself.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from holt import model as model_mod
from holt.model import (
    SMALL,
    AnthropicModel,
    ModelsConfig,
    call_key,
    load_models_config,
    model_for,
    save_models_config,
)


@pytest.fixture(autouse=True)
def pinned_defaults():
    """Every test starts and ends on the defaults, like library code does."""
    model_mod._user_config = None
    yield
    model_mod._user_config = None


def test_library_resolves_pinned_defaults_even_if_a_config_file_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_models_config(ModelsConfig(provider="ollama", model="llama3.3"))
    # No enable_user_models_config() call: the library never reads the file.
    assert model_for("narrate") == SMALL
    assert model_for("classify") == SMALL


def test_replay_keys_are_stable_under_the_defaults():
    before = call_key("narrate", "sys", "prompt")
    model_mod.enable_user_models_config(ModelsConfig())  # explicit defaults
    assert call_key("narrate", "sys", "prompt") == before


def test_opting_in_applies_global_then_stage_overrides():
    model_mod.enable_user_models_config(
        ModelsConfig(model="llama3.3", stages={"narrate": "claude-opus-5"})
    )
    assert model_for("classify") == "llama3.3"
    assert model_for("narrate") == "claude-opus-5"


def test_anthropic_provider_defaults_to_opus_5():
    model_mod.enable_user_models_config(ModelsConfig(provider="anthropic"))
    assert model_for("narrate") == "claude-opus-5"
    assert model_mod.active_config().resolved_key_env() == "ANTHROPIC_API_KEY"


def test_config_round_trips_through_toml(tmp_path):
    path = tmp_path / "models.toml"
    config = ModelsConfig(provider="openai-compatible", model="qwen3",
                          base_url="http://box:8000/v1", api_key_env="VLLM_KEY",
                          stages={"narrate": "qwen3-large"})
    save_models_config(config, path)
    assert load_models_config(path) == config


def test_missing_config_file_is_the_defaults(tmp_path):
    assert load_models_config(tmp_path / "absent.toml") == ModelsConfig()


def _fake_anthropic_response(payload: dict, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=100, output_tokens=20),
    )


class _FakeAnthropic:
    def __init__(self, response):
        self.messages = SimpleNamespace(create=lambda **kw: response)
        self.last_kwargs = None


def test_anthropic_client_honors_the_complete_contract(tmp_path):
    model_mod.enable_user_models_config(ModelsConfig(provider="anthropic"))
    fake = _FakeAnthropic(_fake_anthropic_response({"verdict": "viable"}))
    # Recording is opt-in; this test is about the recorded shape, so it asks.
    client = AnthropicModel(tmp_path / "t.jsonl", _client=fake, record=True)
    out = client.complete(label="classify", system="s", prompt="p",
                          schema={"type": "object"})
    assert out == {"verdict": "viable"}
    # Recorded in the same shape as every other trajectory, keyed for replay.
    entry = json.loads((tmp_path / "t.jsonl").read_text(encoding="utf-8"))
    assert entry["key"] == call_key("classify", "s", "p")
    assert entry["model"] == "claude-opus-5"
    assert entry["response"] == {"verdict": "viable"}
    # Priced from the table, not invented.
    assert client.usage.cost_usd == pytest.approx(100 / 1e6 * 5.00 + 20 / 1e6 * 25.00)


def test_anthropic_refusal_raises_instead_of_recording(tmp_path):
    model_mod.enable_user_models_config(ModelsConfig(provider="anthropic"))
    fake = _FakeAnthropic(_fake_anthropic_response({}, stop_reason="refusal"))
    client = AnthropicModel(tmp_path / "t.jsonl", _client=fake)
    with pytest.raises(RuntimeError, match="refusal"):
        client.complete(label="classify", system="s", prompt="p", schema={})
    assert not (tmp_path / "t.jsonl").exists()


def test_live_dispatch_picks_the_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    model_mod.enable_user_models_config(ModelsConfig(provider="anthropic"))
    assert isinstance(model_mod.live_client(tmp_path / "t.jsonl"), AnthropicModel)


def test_local_server_needs_no_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    model_mod.enable_user_models_config(ModelsConfig(provider="ollama"))
    client = model_mod.OpenAIModel(tmp_path / "t.jsonl")  # must not raise
    assert client._client.base_url.host == "localhost"


def test_patch_model_replays_hits_and_records_only_misses(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({
        "key": call_key("classify", "s", "old prompt"),
        "label": "classify", "model": SMALL, "system": "s", "prompt": "old prompt",
        "response": {"kept": True}, "usage": {"input_tokens": 1, "output_tokens": 1},
    }) + "\n")

    calls = []

    class FakeLive:
        usage = model_mod.Usage()
        patched = 0

        def complete(self, **kw):
            calls.append(kw["prompt"])
            return {"fresh": True}

    client = model_mod.PatchModel(path, _live=FakeLive())
    assert client.complete(label="classify", system="s", prompt="old prompt",
                           schema={}) == {"kept": True}
    assert calls == []  # the hit cost nothing and touched no network
    assert client.complete(label="classify", system="s", prompt="new prompt",
                           schema={}) == {"fresh": True}
    assert calls == ["new prompt"]
    assert client.patched == 1


def test_usage_records_which_models_answered_in_first_use_order():
    usage = model_mod.Usage()
    usage.add(SMALL, 10, 1)
    usage.add("llama3.2:latest", 10, 1)
    usage.add(SMALL, 10, 1)
    assert usage.models == [SMALL, "llama3.2:latest"]


def test_a_replay_reports_the_recorded_model_not_the_configured_one(tmp_path):
    """The footer has to describe the run the reader is looking at.

    A recording made on one model, replayed by someone configured for another,
    must still name the model whose words are on the page.
    """
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({
        "key": call_key("classify", "s", "p"),
        "label": "classify", "model": SMALL, "system": "s", "prompt": "p",
        "response": {"kept": True}, "usage": {"input_tokens": 1, "output_tokens": 1},
    }) + "\n")
    client = model_mod.ReplayModel(path)
    client.complete(label="classify", system="s", prompt="p", schema={})
    assert client.usage.models == [SMALL]


def test_cli_models_warns_when_config_diverges_from_the_recorded_defaults(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from holt.cli import main

    assert main(["models"]) == 0
    out = capsys.readouterr().out
    assert SMALL in out
    assert "Not the defaults" not in out

    assert main(["models", "--provider", "anthropic"]) == 0
    out = capsys.readouterr().out
    assert "claude-opus-5" in out
    assert "Not the defaults" in out  # replay warning is printed with the change

    assert main(["models", "--reset"]) == 0
    assert main(["models"]) == 0
    assert "Not the defaults" not in capsys.readouterr().out
