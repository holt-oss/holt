"""Every model call goes through here.

One seam, four jobs. It records trajectories, which are a required deliverable
and a qualification-gate item. It makes replay possible, so a judge reproduces
the headline result with no key and no spend. It pins a model per *stage* rather
than globally. And it is the only file that touches an LLM at all, which is why
swapping provider took one rewrite instead of a refactor.

Model choice is per stage and evidence-led. Counting and verification run no
model; classification, opportunity and prose run the small one; thread
interpretation is the stage that may need the larger one, and whether it does is
measured rather than assumed.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# Dated ids, not floating aliases: `gpt-5-mini` can be repointed underneath a
# recorded run, and a reproduction claim that drifts is not a claim.
SMALL = "gpt-5-mini-2025-08-07"
LARGE = "gpt-5-2025-08-07"

# USD per million tokens, (input, output). A model not listed here is charged
# at zero and `holt models` says so, rather than inventing a price.
PRICES = {
    SMALL: (0.25, 2.00),
    LARGE: (1.25, 10.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5": (10.00, 50.00),
}

# Floating aliases, and the dated snapshot each one currently points at.
#
# Kept separate from `PRICES` because the two facts have different lifetimes. A
# snapshot's price is fixed for as long as that snapshot exists; where an alias
# points is only true until the provider repoints it. Merging them would state
# the second with the confidence of the first.
#
# This exists for *reporting a rate*, never for pinning a run — `STAGE_MODELS`
# names dated ids precisely so a reproduction cannot drift. Before it, selecting
# `gpt-5` in the interface showed "unpriced — cost recorded as 0" next to
# `gpt-5-2025-08-07` showing "priced", which reads as two different models
# rather than one name for the other.
MODEL_ALIASES: dict[str, str] = {
    "gpt-5": LARGE,
    "gpt-5-mini": SMALL,
}


def resolve_price(model_id: str) -> tuple[tuple[float, float] | None, bool]:
    """`((input, output) per million, exact)`, or `(None, False)` if unknown.

    `exact` is False when the rate came from the snapshot an alias points at.
    Callers say "approximately" in that case rather than asserting a price for
    an id that can be repointed underneath them — the rate is right today and
    nobody can promise it is right tomorrow.
    """
    if model_id in PRICES:
        return PRICES[model_id], True
    target = MODEL_ALIASES.get(model_id)
    if target is not None and target in PRICES:
        return PRICES[target], False
    return None, False

# The per-stage assignment under test. Everything starts on the small model; a
# stage is promoted only if the pilot shows it needs to be.
STAGE_MODELS: dict[str, str] = {
    "baseline": SMALL,
    "baseline_matched": SMALL,
    "classify": SMALL,
    "opportunity": SMALL,
    "outcomes": SMALL,
    "narrate": SMALL,
    "pathfinder": SMALL,
    "profile": SMALL,
    "describe": SMALL,
}

TRAJECTORY_DIR = Path("fixtures/trajectories")

# Long enough for a large reasoning response, short enough that a dead connection
# surfaces as an error in the same session rather than as an unexplained silence.
REQUEST_TIMEOUT_S = 300.0
MAX_RETRIES = 4


# --- provider configuration -------------------------------------------------
#
# The default is the pinned OpenAI models above, and the *library* never reads
# the user's model configuration on its own: every benchmark number, committed
# trajectory and replay was produced under the defaults, and an eval script
# silently inheriting somebody's Ollama config would be the exact reproducibility
# failure this file exists to prevent. Only the CLI (and any front end that
# makes the same deliberate call) opts in, via `enable_user_models_config()`.

PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    # provider -> filled-in defaults; anything the user sets explicitly wins.
    "openai": {"api_key_env": "OPENAI_API_KEY"},
    "anthropic": {"api_key_env": "ANTHROPIC_API_KEY", "model": "claude-opus-5"},
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key_env": "OLLAMA_API_KEY"},
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
    },
    # One key, hundreds of models, several of them free. OpenAI wire protocol.
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "openai-compatible": {"api_key_env": "OPENAI_API_KEY"},
}

#: Where to get a key for each hosted provider, for the setup hint. Gemini is
#: listed first on purpose: its free tier is the cheapest way for a student to
#: get the written explanation.
KEY_URLS: dict[str, str] = {
    "gemini": "https://aistudio.google.com/apikey",
    "openrouter": "https://openrouter.ai/keys",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
}

# Providers that speak the OpenAI wire protocol; everything except anthropic.
_OPENAI_WIRE = {"openai", "ollama", "gemini", "openrouter", "openai-compatible"}


@dataclass(slots=True)
class ModelsConfig:
    provider: str = "openai"
    model: str = ""  # applied to every stage when set; stage overrides win
    base_url: str = ""
    api_key_env: str = ""
    stages: dict[str, str] = field(default_factory=dict)

    def resolved_key_env(self) -> str:
        return self.api_key_env or PROVIDER_PRESETS.get(self.provider, {}).get(
            "api_key_env", "OPENAI_API_KEY"
        )

    def resolved_base_url(self) -> str:
        return self.base_url or PROVIDER_PRESETS.get(self.provider, {}).get("base_url", "")

    def is_default(self) -> bool:
        return self == ModelsConfig()


def models_config_path() -> Path:
    from holt import paths

    return paths.config_dir() / "models.toml"


def load_models_config(path: Path | None = None) -> ModelsConfig:
    import tomllib

    path = path or models_config_path()
    if not path.exists():
        return ModelsConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return ModelsConfig(
        provider=data.get("provider", "openai"),
        model=data.get("model", ""),
        base_url=data.get("base_url", ""),
        api_key_env=data.get("api_key_env", ""),
        stages={k: str(v) for k, v in (data.get("stages") or {}).items()},
    )


def save_models_config(config: ModelsConfig, path: Path | None = None) -> Path:
    path = path or models_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f'provider = "{config.provider}"',
        f'model = "{config.model}"',
        f'base_url = "{config.base_url}"',
        f'api_key_env = "{config.api_key_env}"',
    ]
    if config.stages:
        lines.append("")
        lines.append("[stages]")
        lines += [f'{k} = "{v}"' for k, v in sorted(config.stages.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


_user_config: ModelsConfig | None = None


def enable_user_models_config(config: ModelsConfig | None = None) -> ModelsConfig:
    """Opt this process into the user's model configuration.

    Called by the CLI entry point (and deliberately by any front end that wants
    the same behavior). Library and eval code never call it, so recorded runs
    and replays always resolve against the pinned defaults.
    """
    global _user_config
    _user_config = config if config is not None else load_models_config()
    return _user_config


def active_config() -> ModelsConfig:
    return _user_config if _user_config is not None else ModelsConfig()


def model_ready(config: ModelsConfig | None = None) -> bool:
    """Whether a live model call could be made right now.

    True when the provider's key is in the environment, or when a local server
    (Ollama, or any OpenAI-compatible endpoint on this machine) has been chosen
    deliberately — those take no key. Everything else runs rules-only: the
    verdict needs no model, and a beginner with no key still gets an answer.
    """
    config = config or active_config()
    if os.environ.get(config.resolved_key_env()):
        return True
    base = config.resolved_base_url()
    return bool(base) and ("localhost" in base or "127.0.0.1" in base)


def model_setup_hint() -> str:
    """One paragraph on how to get the written explanation. Plain English."""
    return (
        "This is the rules-only report: the verdict and the numbers, no AI "
        "write-up. To add a written, cited explanation, set up a model once, "
        "for example Gemini, which has a free tier:\n"
        f"  1. Get a key: {KEY_URLS['gemini']}\n"
        "  2. holt models --provider gemini --model gemini-2.5-flash\n"
        "  3. export GEMINI_API_KEY=<your key>   "
        "(PowerShell: $env:GEMINI_API_KEY = \"<your key>\")"
    )


def missing_key_message(config: ModelsConfig | None = None) -> str:
    config = config or active_config()
    key_env = config.resolved_key_env()
    url = KEY_URLS.get(config.provider, "")
    where = f" Get one at {url}." if url else ""
    return (
        f"{key_env} is not set, so the {config.provider} model cannot be called."
        f"{where} Then run:\n"
        f"  export {key_env}=<your key>   (PowerShell: $env:{key_env} = \"<your key>\")\n"
        "Or add --no-model for the free rules-only report."
    )


def model_for(label: str) -> str:
    config = active_config()
    if label in config.stages:
        return config.stages[label]
    if config.model:
        return config.model
    preset_model = PROVIDER_PRESETS.get(config.provider, {}).get("model")
    if preset_model and not config.is_default():
        return preset_model
    return STAGE_MODELS.get(label, SMALL)


def call_key(label: str, system: str, prompt: str) -> str:
    """Stable identity for a call, so a replay matches its recording.

    Covers the prompt text and the model. An edited prompt or a swapped model
    fails loudly instead of quietly serving an answer to a question nobody asked.
    """
    blob = json.dumps(
        [label, model_for(label), system, prompt], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    # Which models actually answered, in first-use order. Recorded here rather
    # than read back off the configuration because this is the one place that
    # sees every call: on replay it is the ids from the recording, not whatever
    # the reader happens to have configured today.
    models: list[str] = field(default_factory=list)

    def add(self, model: str, inp: int, out: int) -> None:
        # Through the alias table: a run on `gpt-5` spends real money, and
        # recording zero for it because the id carries no date would understate
        # the bill rather than decline to guess at it.
        rates, _exact = resolve_price(model)
        rate_in, rate_out = rates or (0.0, 0.0)
        self.input_tokens += inp
        self.output_tokens += out
        self.cost_usd += inp / 1e6 * rate_in + out / 1e6 * rate_out
        if model not in self.models:
            self.models.append(model)


class ModelClient(Protocol):
    replayed: bool
    usage: Usage

    def complete(self, *, label: str, system: str, prompt: str, schema: dict) -> dict: ...


@dataclass
class OpenAIModel:
    """Live calls, recorded as they go."""

    trajectory_path: Path
    replayed: bool = False
    usage: Usage = field(default_factory=Usage)
    _client: Any = None

    def __post_init__(self) -> None:
        from openai import OpenAI

        config = active_config()
        key_env = config.resolved_key_env()
        base_url = config.resolved_base_url()
        api_key = os.environ.get(key_env)
        if not api_key:
            if base_url:
                # Local OpenAI-compatible servers (Ollama, vLLM, LM Studio)
                # accept any key; a missing variable must not block them.
                api_key = "unused"
            else:
                raise RuntimeError(missing_key_message(config))
        # A request with no timeout can hang for hours on a half-open socket, and
        # a recording run that stalls silently is worse than one that fails: the
        # log simply stops and nothing says why. Bounded and retried instead.
        self._client = OpenAI(
            timeout=REQUEST_TIMEOUT_S,
            max_retries=MAX_RETRIES,
            api_key=api_key,
            base_url=base_url or None,
        )
        self.trajectory_path.parent.mkdir(parents=True, exist_ok=True)

    def complete(self, *, label: str, system: str, prompt: str, schema: dict) -> dict:
        model = model_for(label)
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": label, "schema": schema, "strict": True},
            },
        )
        parsed = json.loads(response.choices[0].message.content)
        u = response.usage
        self.usage.add(model, u.prompt_tokens, u.completion_tokens)

        with self.trajectory_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "key": call_key(label, system, prompt),
                        "label": label,
                        "model": model,
                        "system": system,
                        "prompt": prompt,
                        "response": parsed,
                        "usage": {
                            "input_tokens": u.prompt_tokens,
                            "output_tokens": u.completion_tokens,
                        },
                    }
                )
                + "\n"
            )
        return parsed


@dataclass
class AnthropicModel:
    """Live calls against Claude, recorded exactly like the OpenAI ones.

    Structured output goes through `output_config.format` with the same JSON
    schema every stage already declares, so the `complete()` contract -- a dict
    matching the schema -- holds regardless of provider. Safety classifiers can
    decline a request with `stop_reason: "refusal"`; that surfaces as a loud
    error rather than an empty finding.
    """

    trajectory_path: Path
    replayed: bool = False
    usage: Usage = field(default_factory=Usage)
    _client: Any = None

    MAX_TOKENS = 16000  # thinking counts toward this on current Claude models

    def __post_init__(self) -> None:
        if self._client is None:
            import anthropic

            key_env = active_config().resolved_key_env()
            if not os.environ.get(key_env):
                raise RuntimeError(missing_key_message())
            self._client = anthropic.Anthropic(
                timeout=REQUEST_TIMEOUT_S, max_retries=MAX_RETRIES
            )
        self.trajectory_path.parent.mkdir(parents=True, exist_ok=True)

    def complete(self, *, label: str, system: str, prompt: str, schema: dict) -> dict:
        model = model_for(label)
        response = self._client.messages.create(
            model=model,
            max_tokens=self.MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if response.stop_reason == "refusal":
            raise RuntimeError(
                f"{model} declined the {label} request (stop_reason=refusal); "
                "nothing was recorded for it"
            )
        text = next(b.text for b in response.content if b.type == "text")
        parsed = json.loads(text)
        u = response.usage
        self.usage.add(model, u.input_tokens, u.output_tokens)

        with self.trajectory_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "key": call_key(label, system, prompt),
                        "label": label,
                        "model": model,
                        "system": system,
                        "prompt": prompt,
                        "response": parsed,
                        "usage": {
                            "input_tokens": u.input_tokens,
                            "output_tokens": u.output_tokens,
                        },
                    }
                )
                + "\n"
            )
        return parsed


@dataclass
class ReplayModel:
    """Serves recorded responses. No network, no key, no spend.

    A miss raises rather than falling back to a live call: replay that silently
    bills a judge who asked for the free path is not reproduction.
    """

    trajectory_path: Path
    replayed: bool = True
    usage: Usage = field(default_factory=Usage)
    _recorded: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.trajectory_path.exists():
            raise FileNotFoundError(
                f"No trajectory at {self.trajectory_path}. Replay needs a recorded run."
            )
        for line in self.trajectory_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                self._recorded[entry["key"]] = entry

    def _miss(self, label: str, system: str, prompt: str, key: str) -> str:
        """Say which of the three things that identify a call actually differs.

        A miss used to blame "the prompt or the stage's model", naming both and
        diagnosing neither. The recording carries the text it was made with, so
        the answer is available: if some entry holds this exact prompt, the
        model id is what moved, and the usual reason is a model chosen with
        `holt models` after the recording was committed.
        """
        same_text = [
            e for e in self._recorded.values()
            if e["label"] == label and e["system"] == system and e["prompt"] == prompt
        ]
        if same_text:
            recorded = ", ".join(sorted({e["model"] for e in same_text}))
            return (
                f"No recorded response for {label} (key {key}). The prompt is "
                f"unchanged; the model is not. This run resolves {label} to "
                f"{model_for(label)!r}, and the recording was made with "
                f"{recorded!r}. Committed recordings replay only under the pinned "
                f"defaults — clear the choice with `holt models --reset`, or "
                f"re-record with a key."
            )
        if any(e["label"] == label for e in self._recorded.values()):
            return (
                f"No recorded response for {label} (key {key}). A {label} call is "
                "recorded here but was made with different prompt text, so "
                "replaying it would answer a question that is no longer being "
                "asked. Re-record with a key, or check out the committed state."
            )
        return (
            f"No recorded response for {label} (key {key}), and no {label} call "
            f"is recorded in {self.trajectory_path} at all. Re-record with a key."
        )

    def complete(self, *, label: str, system: str, prompt: str, schema: dict) -> dict:
        key = call_key(label, system, prompt)
        entry = self._recorded.get(key)
        if entry is None:
            raise KeyError(self._miss(label, system, prompt, key))
        u = entry.get("usage", {})
        self.usage.add(entry["model"], u.get("input_tokens", 0), u.get("output_tokens", 0))
        return entry["response"]


@dataclass
class PatchModel:
    """Replay where the recording still matches; record live where it does not.

    The cheap way to heal recordings after a change that reaches only some
    prompts — a reworded rule trace, say, which enters the narration prompt for
    some repositories and not others. Unchanged calls replay free; changed
    calls re-record at the pinned models and are appended, so the file becomes
    fully replayable again without paying for a complete re-record. Entries
    orphaned by the change stay in the file and are inert: replay looks up by
    key and never serves them.
    """

    trajectory_path: Path
    replayed: bool = False
    usage: Usage = field(default_factory=Usage)
    patched: int = 0
    _recorded: dict[str, dict] = field(default_factory=dict)
    _live: Any = None

    def __post_init__(self) -> None:
        if self.trajectory_path.exists():
            for line in self.trajectory_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    self._recorded[entry["key"]] = entry
        if self._live is None:
            self._live = OpenAIModel(self.trajectory_path)
        # One usage object: only the live calls cost anything.
        self.usage = self._live.usage

    def complete(self, *, label: str, system: str, prompt: str, schema: dict) -> dict:
        entry = self._recorded.get(call_key(label, system, prompt))
        if entry is not None:
            return entry["response"]
        self.patched += 1
        return self._live.complete(label=label, system=system, prompt=prompt, schema=schema)


def live_client(path: Path) -> ModelClient:
    """The provider dispatch. One place, so nothing else needs to know."""
    if active_config().provider == "anthropic":
        return AnthropicModel(path)
    return OpenAIModel(path)


def build(repo_slug: str, replay: bool) -> ModelClient:
    path = TRAJECTORY_DIR / (repo_slug.replace("/", "__") + ".jsonl")
    return ReplayModel(path) if replay else live_client(path)
