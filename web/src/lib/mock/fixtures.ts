// Realistic fixtures for MOCK_API=1. Numbers and sentences follow the shape of
// real Holt reports; issue and PR links point at real GitHub URLs.
import type { EvidenceItem, Report, StarterIssue, Verdict } from "../types";

interface Seed {
  repo: string;
  verdict: Verdict;
  description: string;
  language: string;
  stars: number;
  hacktoberfest: boolean;
  stats: Report["stats"];
  decided_by: string[];
  unknowns: string[];
  landing: Report["landing"];
  never_landed: Report["never_landed"];
  evidence: [kind: string, pr: number, text: string, quote: string | null][];
  issues: Omit<StarterIssue, "url" | "created_at">[];
  summary: string;
}

const SEEDS: Seed[] = [
  {
    repo: "pallets/flask",
    verdict: "viable",
    description: "The Python micro framework for building web applications.",
    language: "Python",
    stars: 69800,
    hacktoberfest: true,
    stats: {
      outsider_attempts: 64, outsider_merged: 17, distinct_outsiders: 51,
      first_time_merged_authors: 12, no_reply: 9, median_first_response_hours: 3.2, bot_share: 0.12,
    },
    decided_by: [
      "12 people got their first pull request merged here in the period Holt read.",
      "Maintainers usually reply to outside pull requests within a few hours.",
      "Merged pull requests got a real human review, not a rubber stamp.",
    ],
    unknowns: ["Holt can't see discussions that happened on Discord or in private."],
    landing: [
      { path: "docs", merged: 8, attempted: 14 },
      { path: "src/flask", merged: 6, attempted: 31 },
      { path: "tests", merged: 3, attempted: 9 },
    ],
    never_landed: [{ path: "examples", attempted: 4 }],
    evidence: [
      ["onboarding", 5578, "A first-time contributor fixed a typo in the tutorial; merged the same day.", "Thanks! Merging."],
      ["review", 5601, "A maintainer asked for a test, the contributor added it, and it was merged.", "Could you add a test for the empty case? Then this is good to go."],
      ["merged", 5612, "Docs clarification from a newcomer merged after one review round.", null],
      ["reply", 5623, "First reply came 40 minutes after the pull request was opened.", "Nice catch, looking now."],
      ["closed", 5590, "A large refactor from an outsider was closed with an explanation and a pointer to the design discussion.", "We'd rather not change this API; see the discussion in #5480."],
      ["guidance", 5540, "CONTRIBUTING explains how to run the tests and which issues are good to start with.", null],
      ["onboarding", 5634, "A student's first pull request improving an error message was merged.", "This message is much clearer, thank you!"],
      ["no_reply", 5519, "A feature pull request sat without a reply for three weeks, then was closed as stale.", null],
    ],
    issues: [
      { number: 5642, title: "Document how to test streaming responses", labels: ["docs", "good first issue"], comments: 0, why: ["Labelled good first issue", "Touches docs/, where 8 of 14 outsider pull requests were merged"] },
      { number: 5629, title: "Clarify `url_for` behaviour with `_external` in the API docs", labels: ["docs"], comments: 2, why: ["Small, well-scoped docs change", "A maintainer described the fix in a comment"] },
      { number: 5617, title: "Improve error message when `SECRET_KEY` is missing", labels: ["good first issue"], comments: 1, why: ["Labelled good first issue", "Error-message fixes from newcomers were merged 3 times recently"] },
    ],
    summary:
      "Flask is a good place for a first contribution. Outside pull requests usually get a reply within a few hours, and 12 people got their first pull request merged recently. Docs changes land most often; big API changes are usually declined, so start small.",
  },
  {
    repo: "NixOS/nixpkgs",
    verdict: "viable",
    description: "Nix Packages collection & NixOS.",
    language: "Nix",
    stars: 21300,
    hacktoberfest: true,
    stats: {
      outsider_attempts: 100, outsider_merged: 15, distinct_outsiders: 72,
      first_time_merged_authors: 15, no_reply: 63, median_first_response_hours: 0.8, bot_share: 0.085,
    },
    decided_by: [
      "15 people got their first pull request merged here in the period Holt read.",
      "The typical first reply arrives within an hour.",
      "Most merged newcomer work lands in pkgs/by-name, so there is a clear route in.",
    ],
    unknowns: [
      "63 outside pull requests got no reply. Holt can't tell whether they were duplicates.",
      "Holt only read the most recent 100 outside pull requests in a very busy repository.",
    ],
    landing: [
      { path: "pkgs/by-name", merged: 13, attempted: 62 },
      { path: "nixos/modules", merged: 2, attempted: 19 },
    ],
    never_landed: [
      { path: "pkgs/applications", attempted: 6 },
      { path: "pkgs/development", attempted: 5 },
    ],
    evidence: [
      ["onboarding", 526518, "A newcomer's package update in pkgs/by-name was merged within a day.", "LGTM, thanks for the update!"],
      ["onboarding", 526102, "First-time contributor added a new package; a maintainer guided them through the checklist.", "Please squash the commits and use the `pkgs/by-name` layout."],
      ["no_reply", 525871, "Update to a package outside by-name got no reply before the period ended.", null],
      ["reply", 526330, "A maintainer replied 12 minutes after the pull request was opened.", "Can you run nixpkgs-review on this?"],
      ["merged", 526211, "Version bump from an outside contributor merged after automated checks.", null],
      ["closed", 525990, "A NixOS module change was closed because a larger rewrite is in progress.", "Superseded by #525400."],
      ["guidance", 525650, "CONTRIBUTING.md explains the by-name layout and commit conventions for new packages.", null],
    ],
    issues: [
      { number: 526601, title: "Package request: `typos-lsp`", labels: ["0.kind: packaging request", "good first issue"], comments: 1, why: ["New packages go in pkgs/by-name, where 13 of 62 outsider PRs were merged", "Labelled good first issue"] },
      { number: 526420, title: "`hello-unfree` meta.description is out of date", labels: ["6.topic: documentation"], comments: 0, why: ["One-line fix", "Nobody has claimed it yet"] },
    ],
    summary:
      "nixpkgs is busy, but newcomers do get in, mostly by adding or updating packages under pkgs/by-name. Replies are fast when you follow the checklist. Many pull requests elsewhere go unanswered, so stick to the by-name route for a first contribution.",
  },
  {
    repo: "psf/requests",
    verdict: "viable",
    description: "A simple, yet elegant, HTTP library.",
    language: "Python",
    stars: 52900,
    hacktoberfest: false,
    stats: {
      outsider_attempts: 38, outsider_merged: 7, distinct_outsiders: 33,
      first_time_merged_authors: 6, no_reply: 11, median_first_response_hours: 20, bot_share: 0.05,
    },
    decided_by: [
      "6 people got their first pull request merged here in the period Holt read.",
      "A first reply usually comes within a day, which fits a week of spare time.",
    ],
    unknowns: ["The project says it is feature-frozen; Holt can't tell which fixes maintainers still want."],
    landing: [
      { path: "docs", merged: 4, attempted: 9 },
      { path: "src/requests", merged: 3, attempted: 22 },
    ],
    never_landed: [{ path: "tests", attempted: 3 }],
    evidence: [
      ["onboarding", 6790, "A first-time contributor's docs fix was merged after a short review.", "Thanks for the fix."],
      ["closed", 6781, "A new feature was declined because the project is feature-frozen.", "Requests is feature-frozen; we won't be adding this."],
      ["merged", 6802, "A small bug fix from an outsider merged with a test.", null],
      ["reply", 6795, "Maintainer replied the next morning with review notes.", null],
    ],
    issues: [
      { number: 6810, title: "Docs: `Session.mount` example uses a deprecated adapter argument", labels: ["Documentation"], comments: 0, why: ["Docs changes are merged 4 out of 9 times here", "Nobody has claimed it yet"] },
    ],
    summary:
      "requests welcomes small fixes and docs improvements, but not new features. Expect a reply within about a day.",
  },
  {
    repo: "pytorch/pytorch",
    verdict: "not_viable",
    description: "Tensors and dynamic neural networks in Python with strong GPU acceleration.",
    language: "Python",
    stars: 91200,
    hacktoberfest: false,
    stats: {
      outsider_attempts: 100, outsider_merged: 3, distinct_outsiders: 88,
      first_time_merged_authors: 2, no_reply: 71, median_first_response_hours: 190, bot_share: 0.31,
    },
    decided_by: [
      "71 of 100 outside pull requests drew no reply, and only 3 were merged.",
      "The typical first reply takes about 8 days, longer than a week of spare time allows.",
    ],
    unknowns: ["Some outside work may land through internal imports that Holt can't see."],
    landing: [{ path: "docs/source", merged: 2, attempted: 12 }],
    never_landed: [
      { path: "torch", attempted: 54 },
      { path: "aten/src", attempted: 17 },
      { path: "test", attempted: 9 },
    ],
    evidence: [
      ["no_reply", 136201, "A first-time contributor's bug fix in torch/ got no reply for a month.", null],
      ["closed", 136044, "An outside pull request was closed by a bot as stale.", "Looks like this PR hasn't been updated in a while so we're going to go ahead and mark this as Stale."],
      ["merged", 136310, "A docs typo fix from an outsider was merged.", null],
      ["no_reply", 136122, "A test fix from a newcomer received only automated comments.", null],
      ["policy", 135980, "Many changes need a CLA and internal CI approval before a human looks.", null],
    ],
    issues: [
      { number: 136455, title: "Typo in `torch.nn.functional.interpolate` docstring", labels: ["module: docs", "triaged"], comments: 1, why: ["Docs are the only place outsider work landed recently"] },
    ],
    summary:
      "PyTorch is a hard place for a first contribution right now. Most outside pull requests get no human reply, and replies that do come take about a week. If you want to try, a docs fix is your best bet.",
  },
  {
    repo: "aden-hive/hive",
    verdict: "not_viable",
    description: "Agent runtime for building production agents.",
    language: "Python",
    stars: 1800,
    hacktoberfest: false,
    stats: {
      outsider_attempts: 41, outsider_merged: 0, distinct_outsiders: 37,
      first_time_merged_authors: 0, no_reply: 29, median_first_response_hours: null, bot_share: 0.02,
    },
    decided_by: ["29 of 41 outside pull requests drew no response and none were merged."],
    unknowns: [],
    landing: [],
    never_landed: [
      { path: "core", attempted: 22 },
      { path: "docs", attempted: 11 },
    ],
    evidence: [
      ["no_reply", 412, "A first-time contributor's docs fix received no reply.", null],
      ["closed", 398, "Outside pull request closed without a comment.", null],
      ["no_reply", 405, "A bug fix with tests sat unanswered for five weeks.", null],
    ],
    issues: [],
    summary:
      "No outside pull request was merged in the period Holt read, and most got no reply. Spend your time somewhere else for now.",
  },
  {
    repo: "canonical/ubuntu-cloud-docs",
    verdict: "viable",
    description: "Documentation for Ubuntu on public clouds.",
    language: "Python",
    stars: 90,
    hacktoberfest: true,
    stats: {
      outsider_attempts: 12, outsider_merged: 6, distinct_outsiders: 10,
      first_time_merged_authors: 5, no_reply: 1, median_first_response_hours: 26, bot_share: 0.0,
    },
    decided_by: ["5 people got their first pull request merged here in the period Holt read."],
    unknowns: ["This is a small project; a few pull requests make up the whole picture."],
    landing: [{ path: "aws", merged: 3, attempted: 5 }, { path: "google", merged: 2, attempted: 4 }],
    never_landed: [],
    evidence: [
      ["onboarding", 301, "A newcomer fixed a broken link; merged the next day.", "Thank you!"],
      ["merged", 296, "Outside contributor updated an outdated CLI example.", null],
    ],
    issues: [
      { number: 318, title: "Update screenshots in the AWS quickstart", labels: ["good first issue", "hacktoberfest"], comments: 0, why: ["Labelled good first issue", "aws/ is where 3 of 5 outsider PRs were merged"] },
    ],
    summary: "A small, friendly docs project. Most newcomer pull requests get merged within a couple of days.",
  },
];

// Extra welcoming repos for /find results.
const FIND_ONLY: Seed[] = [
  {
    repo: "excalidraw/excalidraw", verdict: "viable", description: "Virtual whiteboard for sketching hand-drawn like diagrams.",
    language: "TypeScript", stars: 98000, hacktoberfest: true,
    stats: { outsider_attempts: 58, outsider_merged: 14, distinct_outsiders: 49, first_time_merged_authors: 10, no_reply: 12, median_first_response_hours: 9, bot_share: 0.04 },
    decided_by: [], unknowns: [], landing: [{ path: "packages/excalidraw", merged: 12, attempted: 44 }], never_landed: [], evidence: [],
    issues: [
      { number: 9721, title: "Tooltip for the eraser tool is cut off on small screens", labels: ["good first issue", "UX"], comments: 0, why: ["Labelled good first issue", "UI fixes from newcomers were merged 6 times recently"] },
      { number: 9688, title: "Add missing aria-label to the library button", labels: ["accessibility", "good first issue"], comments: 1, why: ["One-file change", "A maintainer confirmed the fix"] },
    ],
    summary: "",
  },
  {
    repo: "charmbracelet/bubbletea", verdict: "viable", description: "A powerful little TUI framework.",
    language: "Go", stars: 31000, hacktoberfest: true,
    stats: { outsider_attempts: 30, outsider_merged: 9, distinct_outsiders: 26, first_time_merged_authors: 7, no_reply: 6, median_first_response_hours: 14, bot_share: 0.1 },
    decided_by: [], unknowns: [], landing: [{ path: "examples", merged: 5, attempted: 9 }], never_landed: [], evidence: [],
    issues: [
      { number: 1203, title: "Example: add a spinner with a progress bar", labels: ["good first issue", "examples"], comments: 0, why: ["examples/ is where 5 of 9 outsider PRs were merged"] },
    ],
    summary: "",
  },
  {
    repo: "rust-lang/rustlings", verdict: "viable", description: "Small exercises to get you used to reading and writing Rust code.",
    language: "Rust", stars: 57000, hacktoberfest: true,
    stats: { outsider_attempts: 44, outsider_merged: 15, distinct_outsiders: 40, first_time_merged_authors: 13, no_reply: 5, median_first_response_hours: 6, bot_share: 0.02 },
    decided_by: [], unknowns: [], landing: [{ path: "exercises", merged: 9, attempted: 20 }], never_landed: [], evidence: [],
    issues: [
      { number: 2150, title: "Hint for `iterators3` mentions a function that was renamed", labels: ["good first issue"], comments: 0, why: ["Labelled good first issue", "Hint fixes are merged almost every time"] },
      { number: 2141, title: "Typo in the `structs2` exercise comment", labels: ["good first issue", "typo"], comments: 2, why: ["One-line fix"] },
    ],
    summary: "",
  },
  {
    repo: "freeCodeCamp/devdocs", verdict: "viable", description: "API documentation browser.",
    language: "JavaScript", stars: 38000, hacktoberfest: true,
    stats: { outsider_attempts: 36, outsider_merged: 12, distinct_outsiders: 31, first_time_merged_authors: 9, no_reply: 4, median_first_response_hours: 30, bot_share: 0.06 },
    decided_by: [], unknowns: [], landing: [{ path: "lib/docs/scrapers", merged: 7, attempted: 15 }], never_landed: [], evidence: [],
    issues: [
      { number: 2311, title: "Update the Vite documentation to v7", labels: ["good first issue", "docs update"], comments: 1, why: ["Scraper updates are the most-merged newcomer change here"] },
    ],
    summary: "",
  },
  {
    repo: "go-gitea/gitea", verdict: "viable", description: "Painless self-hosted all-in-one software development service.",
    language: "Go", stars: 49000, hacktoberfest: false,
    stats: { outsider_attempts: 80, outsider_merged: 21, distinct_outsiders: 60, first_time_merged_authors: 11, no_reply: 14, median_first_response_hours: 11, bot_share: 0.07 },
    decided_by: [], unknowns: [], landing: [{ path: "templates", merged: 8, attempted: 20 }], never_landed: [], evidence: [],
    issues: [
      { number: 35412, title: "Dark theme: diff line numbers have low contrast", labels: ["good first issue", "topic/ui"], comments: 0, why: ["templates/ is where 8 of 20 outsider PRs were merged"] },
    ],
    summary: "",
  },
];

function hoursAgo(h: number): string {
  return new Date(Date.now() - h * 3_600_000).toISOString();
}

function toIssues(repo: string, seed: Seed["issues"]): StarterIssue[] {
  return seed.map((i, n) => ({
    ...i,
    url: `https://github.com/${repo}/issues/${i.number}`,
    created_at: hoursAgo(30 + n * 41),
  }));
}

function toEvidence(repo: string, ev: Seed["evidence"]): EvidenceItem[] {
  return ev.map(([kind, pr, text, quote]) => ({
    id: `pr:${repo}#${pr}:${kind}`,
    url: `https://github.com/${repo}/pull/${pr}`,
    kind,
    value: kind === "no_reply" || kind === "closed" ? "negative" : "substantive",
    text,
    quote,
  }));
}

const HEADLINES: Record<Verdict, string> = {
  viable: "Worth your time",
  not_viable: "Not worth your time",
  insufficient_evidence: "Not enough evidence",
};

function fromSeed(seed: Seed, mode: "rules" | "ai", days: number): Report {
  return {
    repo: seed.repo,
    mode,
    days,
    verdict: seed.verdict,
    headline: HEADLINES[seed.verdict],
    summary: mode === "ai" ? seed.summary : null,
    stats: seed.stats,
    decided_by: seed.decided_by,
    unknowns: seed.unknowns,
    landing: seed.landing,
    never_landed: seed.never_landed,
    evidence: toEvidence(seed.repo, seed.evidence),
    evidence_until: new Date(Date.now() - 86_400_000).toISOString().slice(0, 10) + "T00:00:00Z",
    generated_at: hoursAgo(2),
    cost: mode === "ai" ? { model: "anthropic/claude-sonnet-5", input_tokens: 9120, output_tokens: 1480 } : null,
  };
}

// Deterministic pseudo-random numbers from a repo name, so any repo "works" in mock mode.
function rng(seedText: string) {
  let h = 2166136261;
  for (const c of seedText.toLowerCase()) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

function generated(repo: string, mode: "rules" | "ai", days: number): Report {
  const r = rng(repo);
  const lower = repo.toLowerCase();
  const roll = r();
  const verdict: Verdict = /tiny|empty|new-/.test(lower)
    ? "insufficient_evidence"
    : roll < 0.55 ? "viable" : roll < 0.85 ? "not_viable" : "insufficient_evidence";
  const attempts = verdict === "insufficient_evidence" ? 2 + Math.floor(r() * 3) : 20 + Math.floor(r() * 80);
  const merged = verdict === "viable" ? Math.max(3, Math.floor(attempts * (0.12 + r() * 0.25)))
    : verdict === "not_viable" ? Math.floor(attempts * r() * 0.05) : Math.floor(r() * 2);
  const noReply = verdict === "viable" ? Math.floor(attempts * (0.05 + r() * 0.25)) : Math.floor(attempts * (0.5 + r() * 0.3));
  const firstTimers = Math.max(0, Math.min(merged, Math.floor(merged * (0.5 + r() * 0.5))));
  const reply = verdict === "not_viable" ? (r() < 0.3 ? null : 100 + r() * 300) : 0.5 + r() * 40;
  const dirs = ["docs", "src", "tests", "examples", "lib", "packages/core"];
  const seed: Seed = {
    repo, verdict, description: "", language: "", stars: 0, hacktoberfest: false,
    stats: {
      outsider_attempts: attempts, outsider_merged: merged, distinct_outsiders: Math.max(1, Math.floor(attempts * 0.8)),
      first_time_merged_authors: firstTimers, no_reply: noReply,
      median_first_response_hours: reply == null ? null : Math.round(reply * 10) / 10,
      bot_share: Math.round(r() * 200) / 1000,
    },
    decided_by:
      verdict === "viable"
        ? [`${firstTimers} people got their first pull request merged here in the period Holt read.`, "Outside pull requests usually get a reply from a maintainer."]
        : verdict === "not_viable"
          ? [`${noReply} of ${attempts} outside pull requests drew no response, and only ${merged} were merged.`]
          : ["Too few outside contributors tried in the period Holt read to judge from."],
    unknowns: verdict === "insufficient_evidence" ? ["With so few pull requests, one good or bad experience would change the picture."] : [],
    landing: verdict === "viable"
      ? [{ path: dirs[0], merged: Math.ceil(merged * 0.6), attempted: Math.ceil(attempts * 0.3) }, { path: dirs[1], merged: Math.floor(merged * 0.4), attempted: Math.floor(attempts * 0.5) }]
      : [],
    never_landed: verdict === "viable" ? [{ path: dirs[3], attempted: 3 }] : verdict === "not_viable" ? [{ path: dirs[1], attempted: Math.floor(attempts * 0.6) }] : [],
    evidence: [
      [verdict === "viable" ? "onboarding" : "no_reply", 100 + Math.floor(r() * 900), verdict === "viable" ? "A first-time contributor's pull request was merged after one review." : "A newcomer's pull request got no reply.", verdict === "viable" ? "Thanks, merged!" : null],
      ["reply", 100 + Math.floor(r() * 900), "Maintainer response on an outside pull request.", null],
    ],
    issues: verdict === "viable"
      ? [{ number: 10 + Math.floor(r() * 500), title: "Improve the getting-started section of the README", labels: ["good first issue", "documentation"], comments: 0, why: ["Labelled good first issue", `${dirs[0]}/ is where most outsider work lands`] }]
      : [],
    summary: verdict === "viable"
      ? "This project replies to outside contributors and merges their work. Start with a small docs or test change."
      : verdict === "not_viable"
        ? "Outside pull requests here mostly go unanswered. Look for a more responsive project first."
        : "There isn't enough recent outside activity to say whether this project is a good bet.",
  };
  return fromSeed(seed, mode, days);
}

const ALL = [...SEEDS, ...FIND_ONLY];
const byName = new Map(ALL.map((s) => [s.repo.toLowerCase(), s]));

export function canonicalName(repo: string): string {
  return byName.get(repo.toLowerCase())?.repo ?? repo;
}

export function mockReport(repo: string, mode: "rules" | "ai", days: number): Report {
  const seed = byName.get(repo.toLowerCase());
  return seed ? fromSeed(seed, mode, days) : generated(repo, mode, days);
}

export function mockIssues(repo: string): StarterIssue[] {
  const seed = byName.get(repo.toLowerCase());
  if (seed) return toIssues(seed.repo, seed.issues);
  const report = generated(repo, "rules", 7);
  if (report.verdict !== "viable") return [];
  const r = rng(repo + "#issues");
  return toIssues(repo, [
    { number: 10 + Math.floor(r() * 500), title: "Improve the getting-started section of the README", labels: ["good first issue", "documentation"], comments: 0, why: ["Labelled good first issue", "Docs are where most outsider work lands here"] },
    { number: 10 + Math.floor(r() * 500), title: "Add a test for the empty-input case", labels: ["help wanted", "tests"], comments: 1, why: ["Small, self-contained change"] },
  ]);
}

/** Repos preloaded in the mock cache, so their pages render instantly. */
export const PRECACHED = ["pallets/flask", "NixOS/nixpkgs", "psf/requests", "pytorch/pytorch"];

export function mockFindPool() {
  return ALL.filter((s) => s.verdict === "viable").map((s) => ({
    seed: s,
    issues: toIssues(s.repo, s.issues),
  }));
}

export function isMockNotFound(repo: string): boolean {
  return /(^|\/)(doesnotexist|private)/i.test(repo);
}
