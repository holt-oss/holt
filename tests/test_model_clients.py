"""Live model clients: recording is opt-in and redacted; config is honoured."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from holt import model

SECRET = "ghp_" + "a" * 36


class FakeOpenAI:
    def __init__(self, content: dict) -> None:
        self.content = content
        completions = SimpleNamespace(create=self._create)
        self.chat = SimpleNamespace(completions=completions)

    def _create(self, **kwargs):
        message = SimpleNamespace(content=json.dumps(self.content))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


class FakeAnthropic:
    def __init__(self, content: dict) -> None:
        self.content = content
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(self.content))],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def call(client):
    return client.complete(label="classify", system="s", prompt=f"p {SECRET}", schema={})


@pytest.fixture(autouse=True)
def default_config(monkeypatch):
    monkeypatch.delenv(model.RECORD_ENV, raising=False)
    monkeypatch.setattr(model, "_user_config", None)


@pytest.mark.parametrize("cls, fake", [(model.OpenAIModel, FakeOpenAI),
                                       (model.AnthropicModel, FakeAnthropic)])
def test_live_calls_write_nothing_by_default(tmp_path, monkeypatch, cls, fake):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "t.jsonl"
    client = cls(path, _client=fake({"ok": 1}))
    assert call(client) == {"ok": 1}
    assert not path.exists()
    assert not (tmp_path / "fixtures").exists()


@pytest.mark.parametrize("cls, fake", [(model.OpenAIModel, FakeOpenAI),
                                       (model.AnthropicModel, FakeAnthropic)])
def test_recording_is_opt_in_and_redacted(tmp_path, monkeypatch, cls, fake):
    monkeypatch.setenv(model.RECORD_ENV, "1")
    path = tmp_path / "deep" / "t.jsonl"
    client = cls(path, _client=fake({"echo": SECRET}))
    call(client)
    text = path.read_text(encoding="utf-8")
    assert SECRET not in text
    entry = json.loads(text)
    assert entry["key"] == model.call_key("classify", "s", f"p {SECRET}")


def test_a_redacted_recording_still_replays(tmp_path):
    path = tmp_path / "t.jsonl"
    call(model.OpenAIModel(path, record=True, _client=FakeOpenAI({"answer": 42})))
    assert call(model.ReplayModel(path)) == {"answer": 42}


def test_recording_without_a_path_is_refused():
    with pytest.raises(ValueError):
        model.OpenAIModel(None, record=True, _client=FakeOpenAI({}))


def test_build_live_does_not_touch_the_committed_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = model.build("a/b", replay=False)
    assert client.record is False
    assert not (tmp_path / "fixtures").exists()


def test_build_takes_a_trajectory_directory(tmp_path):
    (tmp_path / "a__b.jsonl").write_text("", encoding="utf-8")
    client = model.build("a/b", replay=True, trajectory_dir=tmp_path)
    assert client.trajectory_path == tmp_path / "a__b.jsonl"


def test_anthropic_uses_the_configured_key_variable_and_base_url(monkeypatch):
    model.enable_user_models_config(model.ModelsConfig(
        provider="anthropic", api_key_env="MY_CLAUDE_KEY", base_url="https://proxy.example/v1",
    ))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MY_CLAUDE_KEY", "sk-ant-xyz")
    kwargs = model.anthropic_client_kwargs()
    assert kwargs["api_key"] == "sk-ant-xyz"
    assert kwargs["base_url"] == "https://proxy.example/v1"

    import anthropic

    client = model.AnthropicModel(None)
    assert isinstance(client._client, anthropic.Anthropic)
    assert client._client.api_key == "sk-ant-xyz"
    assert str(client._client.base_url).startswith("https://proxy.example/v1")


def test_anthropic_without_its_key_says_which_variable(monkeypatch):
    model.enable_user_models_config(model.ModelsConfig(provider="anthropic",
                                                       api_key_env="MY_CLAUDE_KEY"))
    monkeypatch.delenv("MY_CLAUDE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MY_CLAUDE_KEY"):
        model.AnthropicModel(None)
