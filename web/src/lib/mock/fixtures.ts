// Realistic fixtures for MOCK_API=1. For the repos in SEEDS, the verdict, the
// stats and the "decided by" lines are the real engine's on 28 Sep 2026
// (`holt analyze <repo> --live --no-model`), so a mock page never shows a
// verdict the live site contradicts. Landing counts, evidence, issues and
// summaries are illustrative: their links are real GitHub URLs, but the pull
// requests behind them are not the ones described.
import type { EvidenceItem, Report, StarterIssue, Verdict } from "../types";
import { withDerived } from "./derived";

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
  issues: Omit<StarterIssue, "url" | "created_at" | "beginner" | "areas">[];
  summary: string;
}

const SEEDS: Seed[] = [
  {
    repo: "home-assistant/core",
    verdict: "viable",
    description: "Open source home automation that puts local control and privacy first.",
    language: "Python",
    stars: 91200,
    hacktoberfest: true,
    stats: {
      outsider_attempts: 58, outsider_merged: 43, distinct_outsiders: 40,
      first_time_merged_authors: 30, no_reply: 8, median_first_response_hours: 14.7, bot_share: 0.052, still_open: 75, closed_silently: 4
    },
    decided_by: [
      "75 pull requests from outside contributors were opened in the last 14 days, too recently to know how they will end, so they aren't counted yet.",
      "4 pull requests from outside contributors were closed without a reply. That's often how maintainers clear out spam, so they aren't counted as ignored.",
      "43 pull requests from outside contributors were merged, by 30 different people, out of 58 attempts by 40 people. Of those who got a reply, half heard back within 14.7 hours. 8 attempts got no reply at all and weren't merged.",
    ],
    unknowns: ["Holt can't see discussions that happened on Discord or in the forums."],
    landing: [
      { path: "homeassistant/components", merged: 41, attempted: 55, is_file: false },
      { path: "tests/components", merged: 27, attempted: 38, is_file: false },
      { path: "(root)", merged: 14, attempted: 18, is_file: false },
    ],
    never_landed: [{ path: "homeassistant/brands", attempted: 2, is_file: false }],
    evidence: [
      ["onboarding", 153210, "A first-time contributor's fix to one integration was merged after a single review.", "Thanks for the fix!"],
      ["review", 153118, "A maintainer asked for a test, the contributor added it, and it was merged.", "Please add a test for the new option, then this is good to go."],
      ["merged", 153302, "A new sensor for an existing integration from a newcomer merged within two days.", null],
      ["reply", 153276, "First reply came about three hours after the pull request was opened.", "Nice, looking now."],
      ["closed", 152990, "A change to core helpers from an outsider was closed with a pointer to the architecture discussion.", "This needs an architecture decision first; see the discussion."],
      ["guidance", 152877, "The developer docs explain how to set up a dev environment and run one integration's tests.", null],
      ["no_reply", 152804, "A pull request for a little-used integration got no reply before the period ended.", null],
    ],
    issues: [
      { number: 173724, title: "Roborock - is not a valid code for B01_Q10_DP", labels: ["good first issue", "integration: roborock"], comments: 5, why: ["Labelled good first issue", "Touches homeassistant/components, where 41 of 55 outside pull requests were merged"] },
    ],
    summary:
      "Home Assistant is a good place for a first contribution. Most outside pull requests are merged (43 of 58 recently), and 30 people got their first one in. Fixes to a single integration land most often; changes to the core itself need a discussion first.",
  },
  {
    repo: "pallets/flask",
    verdict: "not_viable",
    description: "The Python micro framework for building web applications.",
    language: "Python",
    stars: 74800,
    hacktoberfest: false,
    stats: {
      outsider_attempts: 171, outsider_merged: 5, distinct_outsiders: 147,
      first_time_merged_authors: 4, no_reply: 0, median_first_response_hours: 0.7, bot_share: 0, still_open: 0, closed_silently: 99
    },
    decided_by: [
      "99 pull requests from outside contributors were closed without a reply. That's often how maintainers clear out spam, so they aren't counted as ignored.",
      "5 pull requests from outside contributors were merged, by 4 different people, out of 171 attempts by 147 people. Of those who got a reply, half heard back within 42 minutes.",
      "Only 5 of 171 pull requests from outside contributors were merged, about 1 in 34. Most outside work here is never merged, so yours would be a long shot.",
    ],
    unknowns: ["Holt can't tell how many of the pull requests closed without a reply were spam."],
    landing: [
      { path: "(root)", merged: 2, attempted: 45, is_file: false },
      { path: "src/flask", merged: 2, attempted: 73, is_file: false },
      { path: "docs/tutorial", merged: 1, attempted: 4, is_file: false },
      { path: "tests/test_testing.py", merged: 1, attempted: 5, is_file: true },
    ],
    never_landed: [
      { path: "docs/patterns", attempted: 13, is_file: false },
      { path: "docs/quickstart.rst", attempted: 11, is_file: true },
      { path: "tests/test_config.py", attempted: 8, is_file: true },
    ],
    evidence: [
      ["closed", 5590, "A docs change from a first-time contributor was closed without a comment.", null],
      ["closed", 5601, "A large refactor from an outsider was closed with a pointer to the design discussion.", "We'd rather not change this API; please open a discussion first."],
      ["reply", 5623, "First reply came 40 minutes after the pull request was opened, and closed it.", "Closing, this isn't something we'd change."],
      ["merged", 5612, "A small test fix from a newcomer was merged after one review round.", null],
      ["guidance", 5540, "CONTRIBUTING asks for an issue or discussion before a pull request.", null],
    ],
    issues: [
      { number: 6146, title: "Add Cloudflare to Flask Hosting Platforms docs?", labels: [], comments: 3, why: ["Looks like a small docs change", "3 comments to give you context"] },
    ],
    summary:
      "Flask is well run, but outside pull requests rarely land right now: 5 of the last 171 were merged, and 99 were closed without a word. Replies are quick when they come. If you still want to try, ask on an issue before writing code.",
  },
  {
    repo: "NixOS/nixpkgs",
    verdict: "viable",
    description: "Nix Packages collection & NixOS.",
    language: "Nix",
    stars: 21300,
    hacktoberfest: true,
    stats: {
      outsider_attempts: 57, outsider_merged: 35, distinct_outsiders: 23,
      first_time_merged_authors: 12, no_reply: 9, median_first_response_hours: 16.8, bot_share: 0.083, still_open: 133, closed_silently: 1
    },
    decided_by: [
      "133 pull requests from outside contributors were opened in the last 14 days, too recently to know how they will end, so they aren't counted yet.",
      "35 pull requests from outside contributors were merged, by 12 different people, out of 57 attempts by 23 people. Of those who got a reply, half heard back within 16.8 hours. 9 attempts got no reply at all and weren't merged.",
      "Most pull requests from outside contributors here are package updates; that's real maintenance work, but it's different from contributing to the software itself.",
    ],
    unknowns: [
      "Holt read two weeks of pull requests in a very busy repository; most of the newest ones haven't had time for an answer yet.",
    ],
    landing: [
      { path: "pkgs/by-name", merged: 28, attempted: 41, is_file: false },
      { path: "nixos/modules", merged: 4, attempted: 9, is_file: false },
    ],
    never_landed: [
      { path: "pkgs/applications", attempted: 6, is_file: false },
      { path: "pkgs/development", attempted: 5, is_file: false },
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
      { number: 526601, title: "Package request: `typos-lsp`", labels: ["0.kind: packaging request", "good first issue"], comments: 1, why: ["New packages go in pkgs/by-name, where 28 of 41 outsider PRs were merged", "Labelled good first issue"] },
      { number: 526420, title: "`hello-unfree` meta.description is out of date", labels: ["6.topic: documentation"], comments: 0, why: ["One-line fix", "Nobody has claimed it yet"] },
    ],
    summary:
      "nixpkgs is busy, but newcomers do get in, mostly by adding or updating packages under pkgs/by-name. Replies are fast when you follow the checklist. Work elsewhere lands less often, so stick to the by-name route for a first contribution.",
  },
  {
    repo: "psf/requests",
    verdict: "viable",
    description: "A simple, yet elegant, HTTP library.",
    language: "Python",
    stars: 52900,
    hacktoberfest: false,
    stats: {
      outsider_attempts: 120, outsider_merged: 14, distinct_outsiders: 81,
      first_time_merged_authors: 11, no_reply: 13, median_first_response_hours: 3, bot_share: 0.115, still_open: 0, closed_silently: 68
    },
    decided_by: [
      "68 pull requests from outside contributors were closed without a reply. That's often how maintainers clear out spam, so they aren't counted as ignored.",
      "14 pull requests from outside contributors were merged, by 11 different people, out of 120 attempts by 81 people. Of those who got a reply, half heard back within 3 hours. 13 attempts got no reply at all and weren't merged.",
    ],
    unknowns: ["The project says it is feature-frozen; Holt can't tell which fixes maintainers still want."],
    landing: [
      { path: "docs", merged: 4, attempted: 9, is_file: false },
      { path: "src/requests", merged: 3, attempted: 22, is_file: false },
    ],
    never_landed: [{ path: "tests", attempted: 3, is_file: false }],
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
      "requests welcomes small fixes and docs improvements, but not new features, and most outside pull requests don't land. Replies usually come within a few hours.",
  },
  {
    repo: "pytorch/pytorch",
    verdict: "viable",
    description: "Tensors and dynamic neural networks in Python with strong GPU acceleration.",
    language: "Python",
    stars: 91200,
    hacktoberfest: false,
    stats: {
      outsider_attempts: 35, outsider_merged: 4, distinct_outsiders: 25,
      first_time_merged_authors: 4, no_reply: 10, median_first_response_hours: 163.6, bot_share: 0.037, still_open: 62, closed_silently: 7
    },
    decided_by: [
      "62 pull requests from outside contributors were opened in the last 14 days, too recently to know how they will end, so they aren't counted yet.",
      "4 pull requests from outside contributors were merged, by 4 different people, out of 35 attempts by 25 people. Of those who got a reply, half heard back within 6.8 days. 10 attempts got no reply at all and weren't merged.",
      "All merged pull requests from outside contributors were landed by the project's merge bot, so GitHub shows them as closed rather than merged. They're counted as merged here.",
    ],
    unknowns: ["Some outside work may land through internal imports that Holt can't see."],
    landing: [{ path: "docs/source", merged: 2, attempted: 12, is_file: false }],
    never_landed: [
      { path: "torch/_inductor", attempted: 9, is_file: false },
      { path: "aten/src", attempted: 6, is_file: false },
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
      "PyTorch does merge outside work, but the odds are long: 4 of 35 recent outside pull requests landed, and the typical first reply takes about a week. A docs fix is your best bet.",
  },
  {
    repo: "aden-hive/hive",
    verdict: "not_viable",
    description: "Agent runtime for building production agents.",
    language: "Python",
    stars: 1800,
    hacktoberfest: false,
    stats: {
      outsider_attempts: 183, outsider_merged: 2, distinct_outsiders: 82,
      first_time_merged_authors: 2, no_reply: 42, median_first_response_hours: null, bot_share: 0, still_open: 5, closed_silently: 139
    },
    decided_by: [
      "139 pull requests from outside contributors were closed without a reply. That's often how maintainers clear out spam, so they aren't counted as ignored.",
      "2 pull requests from outside contributors were merged, by 2 different people, out of 183 attempts by 82 people. 42 attempts got no reply at all and weren't merged.",
      "Only 2 of 183 pull requests from outside contributors were merged, about 1 in 92. Most outside work here is never merged, so yours would be a long shot.",
    ],
    unknowns: [],
    landing: [{ path: "core", merged: 2, attempted: 96, is_file: false }],
    never_landed: [{ path: "docs", attempted: 31, is_file: false }],
    evidence: [
      ["no_reply", 412, "A first-time contributor's docs fix received no reply.", null],
      ["closed", 398, "Outside pull request closed without a comment.", null],
      ["no_reply", 405, "A bug fix with tests sat unanswered for five weeks.", null],
    ],
    issues: [],
    summary:
      "Only 2 of 183 outside pull requests were merged in the period Holt read, and most were closed without a word. Spend your time somewhere else for now.",
  },
  {
    repo: "canonical/ubuntu-cloud-docs",
    verdict: "viable",
    description: "Documentation for Ubuntu on public clouds.",
    language: "Python",
    stars: 90,
    hacktoberfest: true,
    stats: {
      outsider_attempts: 31, outsider_merged: 29, distinct_outsiders: 11,
      first_time_merged_authors: 10, no_reply: 0, median_first_response_hours: 2.6, bot_share: 0.0, still_open: 0, closed_silently: 1
    },
    decided_by: ["29 pull requests from outside contributors were merged, by 10 different people, out of 31 attempts by 11 people. Of those who got a reply, half heard back within 2.6 hours."],
    unknowns: ["This is a small project; a few pull requests make up the whole picture."],
    landing: [{ path: "aws", merged: 3, attempted: 5, is_file: false }, { path: "google", merged: 2, attempted: 4, is_file: false }],
    never_landed: [],
    evidence: [
      ["onboarding", 301, "A newcomer fixed a broken link; merged the next day.", "Thank you!"],
      ["merged", 296, "Outside contributor updated an outdated CLI example.", null],
    ],
    issues: [
      { number: 318, title: "Update screenshots in the AWS quickstart", labels: ["good first issue", "hacktoberfest"], comments: 0, why: ["Labelled good first issue", "aws/ is where 3 of 5 outsider PRs were merged"] },
    ],
    summary: "A small, friendly docs project. Almost every outside pull request gets merged, and replies come within a few hours.",
  },
];

// Extra welcoming repos for /find results.
const FIND_ONLY: Seed[] = [
  {
    repo: "microsoft/vscode", verdict: "viable", description: "Visual Studio Code",
    language: "TypeScript", stars: 193000, hacktoberfest: false,
    stats: { outsider_attempts: 38, outsider_merged: 11, distinct_outsiders: 23, first_time_merged_authors: 4, no_reply: 20, median_first_response_hours: 121.4, bot_share: 0.093, still_open: 64, closed_silently: 6 },
    decided_by: [], unknowns: [], landing: [{ path: "src/vs", merged: 9, attempted: 30, is_file: false }], never_landed: [], evidence: [],
    issues: [
      { number: 244138, title: "Disabled and enabled (workspace) extension Disable button dropdown contains both \"Disable\" and \"Disable (Workspace)\" items", labels: ["good first issue", "bug"], comments: 40, why: ["Labelled good first issue", "A maintainer confirmed the bug"] },
    ],
    summary: "",
  },
  {
    repo: "charmbracelet/bubbletea", verdict: "viable", description: "A powerful little TUI framework.",
    language: "Go", stars: 31000, hacktoberfest: true,
    stats: { outsider_attempts: 111, outsider_merged: 23, distinct_outsiders: 79, first_time_merged_authors: 21, no_reply: 53, median_first_response_hours: 67.5, bot_share: 0.16, still_open: 11, closed_silently: 21 },
    decided_by: [], unknowns: [], landing: [{ path: "examples", merged: 5, attempted: 9, is_file: false }], never_landed: [], evidence: [],
    issues: [
      { number: 1203, title: "Example: add a spinner with a progress bar", labels: ["good first issue", "examples"], comments: 0, why: ["examples/ is where 5 of 9 outsider PRs were merged"] },
    ],
    summary: "",
  },
  {
    repo: "rust-lang/rustlings", verdict: "viable", description: "Small exercises to get you used to reading and writing Rust code.",
    language: "Rust", stars: 57000, hacktoberfest: true,
    stats: { outsider_attempts: 166, outsider_merged: 45, distinct_outsiders: 136, first_time_merged_authors: 44, no_reply: 4, median_first_response_hours: 65.5, bot_share: 0.005, still_open: 1, closed_silently: 54 },
    decided_by: [], unknowns: [], landing: [{ path: "exercises", merged: 9, attempted: 20, is_file: false }], never_landed: [], evidence: [],
    issues: [
      { number: 2150, title: "Hint for `iterators3` mentions a function that was renamed", labels: ["good first issue"], comments: 0, why: ["Labelled good first issue", "Hint fixes are merged almost every time"] },
      { number: 2141, title: "Typo in the `structs2` exercise comment", labels: ["good first issue", "typo"], comments: 2, why: ["One-line fix"] },
    ],
    summary: "",
  },
  {
    repo: "freeCodeCamp/devdocs", verdict: "viable", description: "API documentation browser.",
    language: "JavaScript", stars: 38000, hacktoberfest: true,
    stats: { outsider_attempts: 85, outsider_merged: 67, distinct_outsiders: 43, first_time_merged_authors: 30, no_reply: 6, median_first_response_hours: 90.2, bot_share: 0.435, still_open: 3, closed_silently: 3 },
    decided_by: [], unknowns: [], landing: [{ path: "lib/docs/scrapers", merged: 7, attempted: 15, is_file: false }], never_landed: [], evidence: [],
    issues: [
      { number: 2311, title: "Update the Vite documentation to v7", labels: ["good first issue", "docs update"], comments: 1, why: ["Scraper updates are the most-merged newcomer change here"] },
    ],
    summary: "",
  },
  {
    repo: "go-gitea/gitea", verdict: "viable", description: "Painless self-hosted all-in-one software development service.",
    language: "Go", stars: 49000, hacktoberfest: false,
    stats: { outsider_attempts: 47, outsider_merged: 25, distinct_outsiders: 33, first_time_merged_authors: 17, no_reply: 7, median_first_response_hours: 7, bot_share: 0.098, still_open: 48, closed_silently: 4 },
    decided_by: [], unknowns: [], landing: [{ path: "templates", merged: 8, attempted: 20, is_file: false }], never_landed: [], evidence: [],
    issues: [
      { number: 35412, title: "Dark theme: diff line numbers have low contrast", labels: ["good first issue", "topic/ui"], comments: 0, why: ["templates/ is where 8 of 20 outsider PRs were merged"] },
    ],
    summary: "",
  },
];

function hoursAgo(h: number): string {
  return new Date(Date.now() - h * 3_600_000).toISOString();
}

// A rough copy of the server's `beginner` and `areas` (holt.starter), enough for mock pages.
const AREAS: [StarterIssue["areas"][number], RegExp][] = [
  ["docs", /\b(docs?|documentation|readme|typo)/i],
  ["tests", /\btests?\b/i],
  ["design", /\b(ui|ux|design|css|screenshots?)\b/i],
  ["translations", /\b(translations?|i18n)\b/i],
];

function toIssues(repo: string, seed: Seed["issues"]): StarterIssue[] {
  return seed.map((i, n) => ({
    ...i,
    beginner: i.labels.some((l) => /good first|first-timers|beginner/i.test(l)),
    areas: ((a) => (a.length ? a : ["code" as const]))(AREAS.filter(([, re]) => i.labels.some((l) => re.test(l)) || re.test(i.title)).map(([k]) => k)),
    url: `https://github.com/${repo}/issues/${i.number}`,
    created_at: hoursAgo(30 + n * 41),
  }));
}

// API.md: rules mode lists the newcomer PRs behind the counts (kind
// "outsider_pr", value "merged" | "no_reply"); AI mode cites model claims
// ("outcome" per PR, or the engine field a claim is about).
const RULES_VALUE: Record<string, string> = { onboarding: "merged", merged: "merged", review: "merged", no_reply: "no_reply" };
const AI_CLAIM: Record<string, [kind: string, value: string]> = {
  onboarding: ["outcome", "merged_first_contribution"],
  review: ["outcome", "merged_after_review"],
  merged: ["outcome", "merged"],
  reply: ["outcome", "replied_quickly"],
  closed: ["outcome", "closed_with_reason"],
  no_reply: ["outcome", "no_reply"],
  guidance: ["onboarding", "documented"],
  policy: ["outsider_posture", "gated"],
};

function toEvidence(repo: string, ev: Seed["evidence"], mode: "rules" | "ai"): EvidenceItem[] {
  if (mode === "rules") {
    return ev
      .filter(([kind]) => RULES_VALUE[kind])
      .map(([kind, pr, text]) => ({
        id: `pr:${repo}#${pr}:opened`,
        url: `https://github.com/${repo}/pull/${pr}`,
        kind: "outsider_pr",
        value: RULES_VALUE[kind],
        text,
        quote: null,
      }));
  }
  return ev.map(([k, pr, text, quote]) => {
    const [kind, value] = AI_CLAIM[k] ?? ["outcome", k];
    return { id: `pr:${repo}#${pr}:${value}`, url: `https://github.com/${repo}/pull/${pr}`, kind, value, text, quote };
  });
}

// The AI report's two-sentence lead, as the model writes it (addressed to "you").
const BOTTOM_LINE: Record<Verdict, string> = {
  viable: "You'd likely get a reply and a real review here. Start with something small, like a docs or test fix.",
  not_viable: "Your pull request would probably sit without an answer here. Your time is better spent on a more responsive project.",
  insufficient_evidence: "Too few outsiders have tried here lately to say how you'd be treated. If you try, keep your first change very small.",
};

function fromSeed(seed: Seed, mode: "rules" | "ai", days: number): Report {
  return withDerived({
    repo: seed.repo,
    mode,
    days,
    verdict: seed.verdict,
    bottom_line: mode === "ai" ? BOTTOM_LINE[seed.verdict] : null,
    summary: mode === "ai" ? seed.summary : null,
    stats: seed.stats,
    decided_by: seed.decided_by,
    unknowns: seed.unknowns,
    landing: seed.landing,
    never_landed: seed.never_landed,
    evidence: toEvidence(seed.repo, seed.evidence, mode),
    evidence_until: new Date(Date.now() - 86_400_000).toISOString().slice(0, 10) + "T00:00:00Z",
    generated_at: hoursAgo(2),
    cost: mode === "ai" ? { model: "openai/gpt-5-mini", input_tokens: 9120, output_tokens: 1480, usd: 0.00524, seconds: 41.3 } : null,
    holt_users: HOLT_USERS[seed.repo] ?? null,
    outdated: false,
  });
}

// "Holt users who sent pull requests here": only repos where 5+ people would make it up.
const HOLT_USERS: Record<string, Report["holt_users"]> = {
  "home-assistant/core": { people: 9, pull_requests: 12, merged: 7, closed: 2, waiting: 3, window_days: 365, computed_at: hoursAgo(5) },
};

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
      bot_share: Math.round(r() * 200) / 1000, still_open: 0, closed_silently: 0
    },
    decided_by:
      verdict === "viable"
        ? [`${firstTimers} people got their first pull request merged here in the period Holt read.`, "Outside pull requests usually get a reply from a maintainer."]
        : verdict === "not_viable"
          ? [`${noReply} of ${attempts} outside pull requests drew no response, and only ${merged} were merged.`]
          : ["Too few outside contributors tried in the period Holt read to judge from."],
    unknowns: verdict === "insufficient_evidence" ? ["With so few pull requests, one good or bad experience would change the picture."] : [],
    landing: verdict === "viable"
      ? [{ path: dirs[0], merged: Math.ceil(merged * 0.6), attempted: Math.ceil(attempts * 0.3), is_file: false }, { path: dirs[1], merged: Math.floor(merged * 0.4), attempted: Math.floor(attempts * 0.5), is_file: false }]
      : [],
    never_landed: verdict === "viable" ? [{ path: dirs[3], attempted: 3, is_file: false }] : verdict === "not_viable" ? [{ path: dirs[1], attempted: Math.floor(attempts * 0.6), is_file: false }] : [],
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
export const PRECACHED = ["home-assistant/core", "pallets/flask", "NixOS/nixpkgs", "psf/requests", "pytorch/pytorch"];

export function mockFindPool() {
  return ALL.filter((s) => s.verdict === "viable").map((s) => ({
    seed: s,
    issues: toIssues(s.repo, s.issues),
  }));
}

export function isMockNotFound(repo: string): boolean {
  return /(^|\/)(doesnotexist|private)/i.test(repo);
}
