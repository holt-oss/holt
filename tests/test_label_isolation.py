"""Labels must not be able to see the agent that is being graded against them.

`CONTRIBUTING.md` states this rule and three module docstrings claim a test enforces
it. Until this file existed, none did — the guarantee was documented and
unenforced, which is worse than an undocumented one, because a reader trusts it.

The check is structural rather than behavioural: an import is read out of the
source with `ast`, so it fails even for an import that is never executed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

LABELS = Path("eval/labels")
FORBIDDEN = "holt.agent"


def label_modules() -> list[Path]:
    return sorted(LABELS.glob("*.py"))


def test_there_is_something_to_check():
    """A glob that silently matches nothing would make every test below pass."""
    assert len(label_modules()) >= 2


@pytest.mark.parametrize("path", label_modules(), ids=lambda p: p.name)
def test_a_label_module_does_not_import_the_agent(path: Path):
    tree = ast.parse(path.read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    offending = [m for m in imported if m == FORBIDDEN or m.startswith(FORBIDDEN + ".")]
    assert not offending, (
        f"{path} imports {offending}. Ground truth computed with help from the "
        f"thing being graded is not ground truth."
    )
