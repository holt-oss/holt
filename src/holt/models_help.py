"""Help text for `holt models`. Kept next to the CLI so the examples stay in one place."""

from holt.model import PROVIDER_PRESETS

# One working invocation per common provider. Every name here is a key of
# PROVIDER_PRESETS (enforced by tests).
MODELS_HELP_EPILOG = (
    "Examples (one working line per common provider):\n"
    "  holt models --provider gemini --model gemini-2.5-flash\n"
    "  holt models --provider openrouter --model <a model id from openrouter.ai/models>\n"
    "  holt models --provider ollama --model llama3.2\n"
    "  holt models --provider anthropic --model claude-opus-5\n"
    "  holt models --provider openai --model gpt-5-mini"
)

MODELS_HELP_PROVIDERS = ("gemini", "openrouter", "ollama", "anthropic", "openai")

assert set(MODELS_HELP_PROVIDERS) <= set(PROVIDER_PRESETS)
