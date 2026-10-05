"""holt models --help names a working example for each common provider (issue #20)
and names every provider in PROVIDER_PRESETS (issue #277)."""

import pytest

from holt import cli
from holt.model import PROVIDER_PRESETS
from holt.models_help import MODELS_HELP_EPILOG, MODELS_HELP_PROVIDERS


def test_models_help_names_an_example_per_common_provider(capsys):
    with pytest.raises(SystemExit):
        cli.main(["models", "--help"])
    text = capsys.readouterr().out
    for line in MODELS_HELP_EPILOG.splitlines():
        assert line in text, line
    assert set(MODELS_HELP_PROVIDERS) <= set(PROVIDER_PRESETS)


def test_models_help_names_every_provider(capsys):
    with pytest.raises(SystemExit):
        cli.main(["models", "--help"])
    # argparse may wrap a long option's help across lines, so compare without
    # whitespace to assert the provider is named rather than a line layout.
    text = "".join(capsys.readouterr().out.split())
    for provider in PROVIDER_PRESETS:
        assert provider in text, provider
