"""holt models --help names a working example for each common provider (issue #20)."""

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
    for provider in MODELS_HELP_PROVIDERS:
        assert provider in PROVIDER_PRESETS
