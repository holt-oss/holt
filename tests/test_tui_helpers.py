"""Boundary coverage for pure terminal-interface text helpers."""

import pytest

from holt.tui.screens.home import _looks_like_repo
from holt.tui.widgets.candidates import _slug
from holt.tui.widgets.evidence import elide
from holt.tui.widgets.recent import _repo


@pytest.mark.parametrize("shorten", [_slug, _repo])
@pytest.mark.parametrize(
    ("value", "width", "expected"),
    [
        ("o/r", 8, "o/r"),
        ("owner/repo", 10, "owner/repo"),
        ("long-owner/name", 8, "…/name"),
        ("very-long-owner/repository", 8, "…/repos…"),
        ("repository", 8, "reposit…"),
        ("所有者/名前", 6, "所有者/名前"),
        ("長い所有者/名前", 5, "…/名前"),
        ("長い所有者/リポジトリ名", 6, "…/リポジ…"),
    ],
)
def test_repository_shortening(shorten, value, width, expected):
    result = shorten(value, width)
    assert result == expected
    assert len(result) <= width


@pytest.mark.parametrize(
    ("value", "width", "expected"),
    [
        ("id", 8, "id"),
        ("evidence", 8, "evidence"),
        ("abcdefghijk", 8, "ab…ghijk"),
        ("所有者の証拠番号です", 6, "所…番号です"),
        ("abcdefgh", 3, "abc"),
        ("abcdefgh", 1, "a"),
        ("abcdefgh", 0, ""),
    ],
)
def test_evidence_elision(value, width, expected):
    assert elide(value, width) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("o/r", True),
        ("owner/repository", True),
        ("long-owner/long-repository-name", True),
        ("所有者/名前", True),
        ("", False),
        ("repo", False),
        ("/repo", False),
        ("owner/", False),
        (" /repo", False),
        ("owner/ ", False),
        ("owner/repo/extra", False),
        ("https://github.com/owner/repo", False),
    ],
)
def test_repository_input_shape(value, expected):
    assert _looks_like_repo(value) is expected
