"""Session-wide safety rails for the test suite.

`HOLT_NO_NETWORK` is set before any test runs, for the whole session, and not
per module. The model switcher can list a provider and probe a chosen model, and
a probe is a real inference request — against a local endpoint that means
loading a model into RAM on whatever machine is running the tests. Someone
running the suite on a laptop mid-way through an evaluation should not have it
taken out from under them by a test.

It is set here rather than in the one module that needs it so that a test added
later cannot reach the network by forgetting to opt out.
"""

from __future__ import annotations

import os

os.environ.setdefault("HOLT_NO_NETWORK", "1")

# Motion off for the same reason it is off in the TUI tests: an assertion should
# never race an animation frame.
os.environ.setdefault("HOLT_TUI_NO_ANIMATION", "1")

# Never read or write the real home directory. Config and data go to a throwaway
# directory for the session (tests that care point them somewhere narrower), the
# GitHub CLI is never asked for the developer's own token, and a token exported
# in the shell running the suite does not leak into a test's idea of "no token".
import tempfile as _tempfile

_home = _tempfile.mkdtemp(prefix="holt-tests-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_home, "config")
os.environ["HOLT_DATA_DIR"] = os.path.join(_home, "data")
os.environ.pop("HOLT_CONFIG_DIR", None)
os.environ["HOLT_DISABLE_GH"] = "1"
for _name in ("GITHUB_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
              "OPENROUTER_API_KEY"):
    os.environ.pop(_name, None)
