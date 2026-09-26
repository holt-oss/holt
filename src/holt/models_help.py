"""Help text for `holt models`.

`holt models --help` should name one working model id per common provider.
The examples live here so they can be checked against PROVIDER_PRESETS.
"""

from __future__ import annotations

import argparse

from holt.model import PROVIDER_PRESETS

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

_installed = False


def attach(parser: argparse.ArgumentParser) -> None:
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = MODELS_HELP_EPILOG


def install() -> None:
    """Ensure the models subparser gets the provider examples epilog."""
    global _installed
    if _installed:
        return
    original = argparse._SubParsersAction.add_parser

    def add_parser(self, name, **kwargs):  # type: ignore[no-untyped-def]
        parser = original(self, name, **kwargs)
        if name == "models":
            attach(parser)
        return parser

    argparse._SubParsersAction.add_parser = add_parser  # type: ignore[method-assign]
    _installed = True


install()
