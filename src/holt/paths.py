"""Where Holt keeps things on this machine.

Nothing here is relative to the current directory. Holt is installed from PyPI
far more often than it is run from a clone, and a tool that writes `.holt/` or
`runs/` into whatever folder you happened to be standing in is one that litters
your projects.

* **config** — small files you choose: the model, your profile, a saved token.
  `~/.config/holt` on Linux and macOS (or `$XDG_CONFIG_HOME/holt`),
  `%APPDATA%\\holt` on Windows.
* **data** — what Holt produces: past assessments and run recordings.
  `~/.local/share/holt` on Linux (or `$XDG_DATA_HOME/holt`),
  `~/Library/Application Support/holt` on macOS, `%LOCALAPPDATA%\\holt` on
  Windows.

`HOLT_CONFIG_DIR` and `HOLT_DATA_DIR` override both, which is what the test suite
uses so it never touches a real home directory. No dependency: the three
platforms' conventions fit in a dozen lines.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP = "holt"


def config_dir() -> Path:
    if override := os.environ.get("HOLT_CONFIG_DIR"):
        return Path(override)
    if os.environ.get("XDG_CONFIG_HOME"):
        return Path(os.environ["XDG_CONFIG_HOME"]) / APP
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP
    return Path.home() / ".config" / APP


def data_dir() -> Path:
    if override := os.environ.get("HOLT_DATA_DIR"):
        return Path(override)
    if os.environ.get("XDG_DATA_HOME"):
        return Path(os.environ["XDG_DATA_HOME"]) / APP
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP
    return Path.home() / ".local" / "share" / APP


def assessments_dir() -> Path:
    """Past assessments the interface opens on."""
    return data_dir() / "assessments"


def runs_dir() -> Path:
    """Recordings of model calls made on this machine. Never the committed ones."""
    return data_dir() / "runs"
