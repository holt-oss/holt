"""What a person pastes becomes `owner/repo`, or a sentence saying what to type."""

from __future__ import annotations

import pytest

from holt import cli
from holt.reponame import normalise


@pytest.mark.parametrize("text", [
    "pallets/flask",
    "  pallets/flask  ",
    "pallets/flask/",
    "https://github.com/pallets/flask",
    "http://github.com/pallets/flask/",
    "https://www.github.com/pallets/flask",
    "github.com/pallets/flask",
    "github.com/pallets/flask.git",
    "https://github.com/pallets/flask.git",
    "https://github.com/pallets/flask/tree/main/src/flask",
    "https://github.com/pallets/flask/blob/main/README.md",
    "https://github.com/pallets/flask?tab=readme-ov-file",
    "https://github.com/pallets/flask#readme",
    "https://github.com/pallets/flask/?tab=readme-ov-file#readme",
    "https://github.com/pallets/flask/pulls",
    "git@github.com:pallets/flask.git",
])
def test_accepts_what_people_paste(text):
    assert normalise(text) == "pallets/flask"


def test_keeps_dots_and_underscores_in_names():
    assert normalise("https://github.com/vercel/next.js") == "vercel/next.js"
    assert normalise("some-org/my_repo.py") == "some-org/my_repo.py"


@pytest.mark.parametrize("text, words", [
    ("https://gitlab.com/gitlab-org/gitlab", "GitLab"),
    ("gitlab.com/a/b", "GitLab"),
    ("https://bitbucket.org/a/b", "Bitbucket"),
    ("flask", "owner and the name"),
    ("", "enter a GitHub repository"),
    ("https://github.com/pallets", "account"),
    ("a/b/c", "too many parts"),
    ("-bad/x", "not a GitHub account name"),
    ("owner/bad name", "not a valid repository name"),
])
def test_rejects_other_things_in_plain_english(text, words):
    with pytest.raises(ValueError) as exc:
        normalise(text)
    message = str(exc.value)
    assert words in message
    assert "Traceback" not in message


def test_cli_prints_the_message_instead_of_a_traceback(capsys):
    assert cli.main(["analyze", "https://gitlab.com/a/b", "--no-model"]) == 1
    assert "only reads GitHub" in capsys.readouterr().err


def test_cli_normalise_stays_lenient_for_the_tui():
    assert cli.normalise("https://github.com/pallets/flask/tree/main") == "pallets/flask"
    assert cli.normalise("flask") == "flask"
