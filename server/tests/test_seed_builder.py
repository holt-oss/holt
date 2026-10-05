"""scripts/build_seed_list.py: hygiene, search paging and programme mapping, GitHub faked."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_seed_list.py"
spec = importlib.util.spec_from_file_location("build_seed_list", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def repo(name="octo/one", stars=500, **over):
    return {"nameWithOwner": name, "description": "A web framework", "isArchived": False, "isFork": False, "isMirror": False,
            "pushedAt": "2026-09-20T00:00:00Z", "stargazerCount": stars,
            "hasPullRequestsEnabled": True, "pullRequestCreationPolicy": "ALL"} | over


def test_drop_reasons():
    assert builder.drop_reason(repo()) is None
    assert builder.drop_reason(None) == "gone"
    assert builder.drop_reason(repo(isArchived=True)) == "archived"
    assert builder.drop_reason(repo(isFork=True)) == "fork or mirror"
    assert builder.drop_reason(repo(isMirror=True)) == "fork or mirror"
    assert builder.drop_reason(repo(stars=19)) == "under 20 stars"
    assert builder.drop_reason(repo(pushedAt="2026-05-31T23:59:59Z")) == "no push since 2026-06-01"
    closed = "closed to outside pull requests"
    assert builder.drop_reason(repo(hasPullRequestsEnabled=False)) == closed
    assert builder.drop_reason(repo(pullRequestCreationPolicy="COLLABORATORS_ONLY")) == closed


def test_catalogues_and_farms_are_skipped_by_name():
    assert builder.skipped("someone/awesome-python")
    assert builder.skipped("someone/first-contributions")
    assert builder.skipped("swisskyrepo/PayloadsAllTheThings")
    assert builder.skipped("someone/dotfiles")
    assert builder.skipped("someone/React-projects-for-beginners")
    assert builder.skipped("someone/30-Days-Of-Rust")
    assert not builder.skipped("pallets/flask")
    assert not builder.skipped("scikit-learn/scikit-learn")


def test_catalogues_practice_repos_and_mirrors_are_dropped_by_description():
    def why(description):
        return builder.drop_reason(repo(description=description))

    for description in ("[MIRROR] Package management system",
                        "Read-only mirror of the project on GitLab.",
                        "Addons. This is a mirror of the repository at git.example.org"):
        assert why(description) == "fork or mirror"
    for description in ("⚙️ A curated list of static analysis tools",
                        "A list of job related sites for people in tech",
                        "Collection of free resources like icons and images",
                        "Make your first GitHub pull request.",
                        "Beginners book on Python",
                        "Personal portfolio website, built with Next.js"):
        assert why(description) == "catalogue or farm"
    for description in (None, "", "Hiero Mirror Node archives data from consensus nodes",
                        "A ZSH quickstart with a curated list of extra plugins",
                        "Cargo plugin to generate list of all licenses for a crate",
                        "A Hugo theme for personal portfolio"):
        assert why(description) is None


class FakeSearch:
    """A search index of repos by star count, 100 a page and 1,000 a query like GitHub's."""

    def __init__(self, stars):
        self.repos = sorted((repo(f"octo/r{i}", s) for i, s in enumerate(stars)),
                            key=lambda n: -n["stargazerCount"])
        self.queries = []

    def graphql(self, query, variables):
        q = variables["q"]
        self.queries.append(q)
        band = next(t for t in q.split() if t.startswith("stars:")).removeprefix("stars:")
        low, high = (int(band[2:]), None) if band.startswith(">=") else map(int, band.split(".."))
        hits = [n for n in self.repos
                if n["stargazerCount"] >= low and (high is None or n["stargazerCount"] <= high)]
        start = int(variables["after"] or 0)
        end = min(start + 100, 1000, len(hits))
        return {"search": {"repositoryCount": len(hits), "nodes": hits[start:end],
                           "pageInfo": {"hasNextPage": end < min(len(hits), 1000),
                                        "endCursor": str(end)}}}


def test_search_walks_down_the_star_ranges_past_the_cap():
    gh = FakeSearch(range(20, 2520))
    found = {n["nameWithOwner"] for n in builder.search(gh, "topic:hacktoberfest", 20)}
    assert len(found) == 2500
    assert len(gh.queries) == 10 + 10 + 6  # 1,000 + 1,000 + 502 results, one page per 100
    assert all("sort:stars-desc" in q for q in gh.queries)


def test_search_gets_past_a_thousand_repos_with_the_same_stars():
    gh = FakeSearch([50] * 1200 + [30] * 5)
    found = {n["nameWithOwner"] for n in builder.search(gh, "x", 20)}
    assert {f"octo/r{i}" for i in range(1200, 1205)} <= found


def test_search_stops_as_soon_as_the_caller_has_enough():
    gh = FakeSearch(range(20, 2520))
    results = builder.search(gh, "x", 20)
    assert [next(results)["stargazerCount"] for _ in range(150)][-1] == 2370
    assert len(gh.queries) == 2


def test_gsoc_maps_repos_hand_mapped_orgs_and_bare_orgs(monkeypatch):
    orgs = [{"source_code": "https://github.com/octo/one/"},
            {"source_code": "https://github.com/ceph"},
            {"source_code": "https://github.com/orgs/unmapped-org/repositories"},
            {"source_code": "https://github.com/another-org/.github"},
            {"source_code": "https://gitlab.com/somewhere/else"},
            {"source_code": "https://python-gsoc.org/"},
            {"source_code": None}]
    monkeypatch.setattr(builder, "get", lambda url: json.dumps(orgs).encode())
    assert builder.gsoc(2024) == ["octo/one", "ceph/ceph", "unmapped-org", "another-org",
                                  "python/cpython"]


def test_lfx_takes_recent_github_links(monkeypatch):
    def project(link, created="2025-01-01 00:00:00 +0000"):
        return {"_source": {"repoLink": link, "createdOn": created}}

    pages = {0: [project("https://github.com/octo/one/tree/main/docs"),
                 project("https://github.com/octo/old", "2022-05-01 00:00:00 +0000"),
                 project("https://gitlab.com/octo/elsewhere"),
                 project("https://github.com/some-org")],
             4: []}

    def get(url):
        start = int(url.split("from=")[1].split("&")[0])
        return json.dumps({"hits": {"hits": pages[start]}}).encode()

    monkeypatch.setattr(builder, "get", get)
    assert builder.lfx() == ["octo/one", "some-org"]


def test_outreachy_reads_only_community_names(monkeypatch):
    index = '<a href="/alums/2022-12/">x</a><a href="/alums/2024-05/">y</a>'
    page = ("<h4>Some Intern</h4><BR>Wagtail mentor(s): A and B <BR>Project: p"
            "<h4>Other Intern</h4><BR>Perl &amp; Raku mentor(s): C <BR>"
            "<h4>Third</h4><BR>Debian mentor(s): D <BR>")
    fetched = []

    def get(url):
        fetched.append(url)
        return (index if url.endswith("/alums/") else page).encode()

    monkeypatch.setattr(builder, "get", get)
    assert builder.outreachy() == ["wagtail/wagtail", "Perl/perl5", "rakudo/rakudo"]
    assert fetched == [builder.OUTREACHY_URL, builder.OUTREACHY_URL + "2024-05/"]


class FakeGitHub:
    """Answers the builder's searches from `found` (keyed by what the query is about)
    and its hygiene pass from `repos`."""

    found: dict[str, list[dict]] = {}
    repos: dict[str, dict] = {}

    def __init__(self, token):
        self.points = 0

    def graphql(self, query, variables=None):
        q = (variables or {}).get("q")
        if q is None:
            asked = re.findall(r'(r\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\)', query)
            return {alias: self.repos.get(f"{owner}/{name}") for alias, owner, name in asked}
        if "language:" in q:
            key = re.search(r'language:"([^"]+)"', q).group(1)
        elif "topic:" in q:
            key = re.search(r"topic:(\S+)", q).group(1)
        else:
            key = "any language"
            assert builder.ANY_LANGUAGE_TERMS in q
        hits = self.found.get(key, [])
        return {"search": {"repositoryCount": len(hits), "nodes": hits,
                           "pageInfo": {"hasNextPage": False, "endCursor": None}}}


def build(monkeypatch, tmp_path, target):
    seeds = tmp_path / "repos.txt"
    seeds.write_text(f"# by hand\nkept/by-hand\n\n{builder.MARKER}\n\nold/generated\n",
                     encoding="utf-8")
    monkeypatch.setattr(builder, "SEEDS", seeds)
    monkeypatch.setattr(builder, "GitHub", FakeGitHub)
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    for source in ("lfx", "outreachy", "gfi", "afb"):
        monkeypatch.setattr(builder, source, lambda: [])
    monkeypatch.setattr(builder, "gsoc", lambda year: [])
    monkeypatch.setattr(builder, "ufg", lambda: ["listed/up-for-grabs"])
    monkeypatch.setattr("sys.argv", ["build_seed_list.py", "--check", "--target", str(target)])
    assert builder.main() == 0
    text = seeds.read_text(encoding="utf-8")
    blocks, name = {}, None
    for line in text.partition(builder.MARKER)[2].splitlines():
        if line.startswith("# source: "):
            name = line.removeprefix("# source: ").split(" (")[0]
            blocks[name] = []
        elif line:
            blocks[name].append(line)
    return text, blocks


def test_build_adds_the_beginner_searches_and_keeps_every_filter(monkeypatch, tmp_path):
    monkeypatch.setattr(FakeGitHub, "repos", {"listed/up-for-grabs": repo("listed/up-for-grabs")})
    monkeypatch.setattr(FakeGitHub, "found", {
        "Python": [repo("py/project")],
        "help-wanted": [repo("topic/project"), repo("topic/awesome-things"),
                        repo("kept/by-hand")],
        "any language": [repo("any/project"), repo("py/project"), repo("listed/up-for-grabs"),
                         repo("any/archived", isArchived=True),
                         repo("any/closed", pullRequestCreationPolicy="COLLABORATORS_ONLY"),
                         repo("any/first-contributions"), repo("any/dotfiles", stars=19)],
        "hacktoberfest": [repo("fest/big", 900), repo("any/project", 500),
                          repo("fest/mid", 300), repo("fest/small", 40)],
    })
    text, blocks = build(monkeypatch, tmp_path, target=7)

    assert text.startswith(f"# by hand\nkept/by-hand\n\n{builder.MARKER}\n")
    assert list(blocks)[0] == "hacktoberfest-topic"
    assert blocks["good-first-issues Python"] == ["py/project"]
    assert blocks["up-for-grabs"] == ["listed/up-for-grabs"]
    assert blocks["topic help-wanted"] == ["topic/project"]
    assert blocks["good-first-issues any language"] == ["any/project"]
    # Five from the sources above, so the topic fills the last two from the top.
    assert blocks["hacktoberfest-topic"] == ["fest/big", "fest/mid"]
    assert "old/generated" not in text
