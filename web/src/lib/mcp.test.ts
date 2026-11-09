import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { CHECK_WAIT_MS, checkRepo, COMPARE_STARTS, COMPARE_WAIT_MS, compareRepos, MAX_REPORT_AGE_DAYS, mergedShare, type McpDeps, starterIssues } from "./mcp.ts";
import { mcpServer } from "./mcp-server.ts";
import type { AnalysisStart, ApiError, JobStatus, Report, Result, StarterIssue, Stats, Verdict } from "./types.ts";

const SITE = "https://githolt.com";

const HEADLINE: Record<Verdict, string> = {
  viable: "Worth your time",
  long_shot: "Long shot",
  not_viable: "Not worth your time",
  insufficient_evidence: "Not enough evidence",
  personal: "Personal project",
  catalogue: "A list, not code",
};

function stats(over: Partial<Stats> = {}): Stats {
  return {
    outsider_attempts: 100, outsider_merged: 20, distinct_outsiders: 70, first_time_merged_authors: 9, no_reply: 10,
    median_first_response_hours: 14, bot_share: 0, still_open: 5, closed_silently: 3, closed_by_bot: 0, withdrawn: 1, too_old: 0,
    timing: null, ...over,
  };
}

function report(repo: string, verdict: Verdict = "viable", o: { stats?: Partial<Stats>; odds?: "good" | "fair" | "long" | null; outdated?: boolean; at?: string } = {}): Report {
  const odds = o.odds === undefined ? (verdict === "viable" ? "good" : null) : o.odds;
  return {
    repo, mode: "rules", days: 7, verdict, headline: HEADLINE[verdict], tone: "good",
    verdict_line: `Reason for ${repo}.`, numbers_line: "numbers", first_timer_line: null, next_step: "next",
    stat_line: null, counted: [], how_long: [],
    odds: odds ? { level: odds, tone: "good", text: `${odds} odds` } : null,
    bottom_line: null, summary: null, stats: stats(o.stats), decided_by: [], rule_codes: [], unknowns: [], landing: [], never_landed: [],
    evidence: [{ id: "pr:x#1:opened", url: "https://github.com/x/1", kind: "onboarding", value: "substantive", text: "secret evidence", quote: null }],
    evidence_until: null, generated_at: o.at ?? "2026-11-01T00:00:00Z", sample: null, asks: [], budget_independent: true, cost: null,
    holt_users: null, about: null, outdated: o.outdated ?? false,
  } as unknown as Report;
}

const err = (status: number, code: string, message = "nope"): Result<never> => ({ ok: false, status, error: { code, message } as ApiError });

interface Fake {
  deps: McpDeps;
  started: string[];
  slept: number;
}

/**
 * A mocked server and clock. `cached`: what GET /v1/reports answers. `start`:
 * what POST /v1/analyses answers (default: queue a job). `polls`: how many
 * polls a job takes to finish (Infinity: never), and the report it ends with.
 */
function fake(o: {
  cached?: Record<string, Report>;
  start?: (repo: string) => Result<AnalysisStart>;
  polls?: (repo: string) => number;
  done?: (repo: string) => Report | { error: ApiError };
  issues?: (repo: string, limit: number) => Result<{ repo: string; issues: StarterIssue[] }>;
} = {}): Fake {
  let t = Date.parse("2026-11-09T00:00:00Z");
  const jobs = new Map<string, { repo: string; polls: number }>();
  const f: Fake = {
    started: [],
    slept: 0,
    deps: {
      siteUrl: SITE,
      now: () => t,
      sleep: async (ms) => {
        t += ms;
        f.slept += ms;
      },
      getReport: async (repo) => {
        const r = o.cached?.[repo.toLowerCase()];
        return r ? { ok: true, data: r } : err(404, "not_found");
      },
      startAnalysis: async (repo) => {
        f.started.push(repo);
        if (o.start) return o.start(repo);
        const id = `job_${jobs.size}`;
        jobs.set(id, { repo, polls: 0 });
        return { ok: true, data: { status: "queued", job_id: id } };
      },
      jobStatus: async (id): Promise<Result<JobStatus>> => {
        const j = jobs.get(id);
        if (!j) return err(404, "not_found");
        j.polls++;
        if (j.polls < (o.polls?.(j.repo) ?? 2)) return { ok: true, data: { status: "running", stage: "Reading pull requests", progress: 0.4, report: null, error: null } };
        const end = o.done?.(j.repo) ?? report(j.repo);
        if ("error" in end) return { ok: true, data: { status: "error", stage: null, progress: 1, report: null, error: end.error } };
        return { ok: true, data: { status: "done", stage: "Done", progress: 1, report: end, error: null } };
      },
      starterIssues: async (repo, limit) => (o.issues ? o.issues(repo, limit) : err(404, "not_found")),
    },
  };
  return f;
}

// --- check_repo ---------------------------------------------------------------------

test("check_repo: a cached report answers at once, with no new check", async () => {
  const f = fake({ cached: { "pallets/flask": report("pallets/flask", "viable", { stats: { timing: { last_outside_merge: "2026-10-30" } as Stats["timing"] } }) } });
  const a = await checkRepo(f.deps, { repo: "https://github.com/pallets/flask/pulls" });
  assert.equal(a.isError, false);
  assert.deepEqual(f.started, []);
  const r = a.structured;
  assert.equal(r.status, "checked");
  assert.equal(r.verdict, "Worth your time");
  assert.equal(r.reason, "Reason for pallets/flask.");
  assert.equal(r.odds, "good odds");
  assert.equal(r.link, "https://githolt.com/pallets/flask");
  assert.deepEqual(r.numbers, {
    outside_prs: 100, outside_prs_merged: 20, merged_percent: 20, typical_first_reply: "14 hours", typical_first_reply_hours: 14,
    no_reply: 10, first_timers_merged: 9, closed_without_a_word: 3, last_outside_merge: "2026-10-30", still_open: 5, older_than_a_year: 0,
  });
  // Nothing from the full report: no evidence in the answer.
  assert.doesNotMatch(JSON.stringify(a), /secret evidence/);
  assert.match(a.text, /^pallets\/flask: Worth your time\. Checked 1 Nov 2026\./);
  assert.match(a.text, /20 of 100 outside pull requests merged \(20%\)/);
  assert.match(a.text, /https:\/\/githolt\.com\/pallets\/flask$/);
});

test("check_repo: a cold repo is checked, and the answer waits for it", async () => {
  const f = fake({ polls: () => 3 });
  const a = await checkRepo(f.deps, { repo: "octo/cold" });
  assert.deepEqual(f.started, ["octo/cold"]);
  assert.equal(a.structured.status, "checked");
  assert.equal(a.structured.verdict, "Worth your time");
  assert.ok(f.slept < CHECK_WAIT_MS);
});

test("check_repo: a check still running after the wait says to call again", async () => {
  const f = fake({ polls: () => Infinity });
  const a = await checkRepo(f.deps, { repo: "octo/slow" });
  assert.equal(a.isError, false);
  assert.equal(a.structured.status, "checking");
  assert.equal(a.structured.verdict, null);
  assert.match(a.structured.note ?? "", /call again/i);
  assert.equal(a.structured.link, "https://githolt.com/octo/slow");
  // Bounded: never past the wait.
  assert.ok(f.slept <= CHECK_WAIT_MS, `slept ${f.slept}`);
  assert.ok(f.slept >= CHECK_WAIT_MS - 2_000);
});

test("check_repo: over the MCP budget is 'busy' with the link, not an error dump", async () => {
  const f = fake({ start: () => err(429, "rate_limited", "You've checked a lot of repositories in the last hour. Please wait a bit, or sign in for a higher limit.") });
  const a = await checkRepo(f.deps, { repo: "octo/cold" });
  assert.equal(a.isError, false);
  assert.equal(a.structured.status, "busy");
  assert.match(a.structured.note ?? "", /Holt is busy/);
  // The server's own words (meant for the site) don't leak through.
  assert.doesNotMatch(a.text, /sign in/i);
  assert.match(a.text, /https:\/\/githolt\.com\/octo\/cold/);
});

test("check_repo: a bad repo name is refused without calling the server", async () => {
  const f = fake();
  for (const repo of ["not a repo", "", "https://example.com/x", "octo/.."]) {
    const a = await checkRepo(f.deps, { repo });
    assert.equal(a.isError, true, repo);
    assert.equal(a.structured.status, "invalid");
    assert.match(a.text, /owner\/name/);
  }
  assert.deepEqual(f.started, []);
});

test("check_repo: a repo GitHub doesn't have is an answer, not a failure", async () => {
  const f = fake({ start: () => err(404, "not_found") });
  const a = await checkRepo(f.deps, { repo: "octo/missing" });
  assert.equal(a.isError, false);
  assert.equal(a.structured.status, "not_found");
});

test("check_repo: a check that fails on GitHub's side is an error with a plain message", async () => {
  const f = fake({ done: () => ({ error: { code: "upstream", message: "GitHub didn't answer in time." } as ApiError }) });
  const a = await checkRepo(f.deps, { repo: "octo/flaky" });
  assert.equal(a.isError, true);
  assert.equal(a.structured.status, "error");
  assert.equal(a.structured.note, "GitHub didn't answer in time.");
});

test("check_repo: an outdated report starts a fresh check and shows the old verdict meanwhile", async () => {
  const f = fake({ cached: { "octo/old": report("octo/old", "long_shot", { outdated: true }) }, polls: () => Infinity });
  const a = await checkRepo(f.deps, { repo: "octo/old" });
  assert.deepEqual(f.started, ["octo/old"]);
  assert.equal(a.structured.status, "outdated");
  assert.equal(a.structured.verdict, "Long shot");
  assert.match(a.text, /older version of Holt/);
});

test("check_repo: an outdated report whose fresh check finishes in time shows the new verdict", async () => {
  const f = fake({ cached: { "octo/old": report("octo/old", "long_shot", { outdated: true }) }, done: (r) => report(r, "viable") });
  const a = await checkRepo(f.deps, { repo: "octo/old" });
  assert.equal(a.structured.status, "checked");
  assert.equal(a.structured.verdict, "Worth your time");
});

test("every verdict says its date in the text, not only in checked_at", async () => {
  const f = fake({ cached: { "a/b": report("a/b", "viable", { at: "2026-10-20T09:00:00Z" }), "c/d": report("c/d", "long_shot", { at: "2026-11-02T09:00:00Z" }) } });
  const one = await checkRepo(f.deps, { repo: "a/b" });
  assert.equal(one.structured.checked_at, "2026-10-20T09:00:00Z");
  assert.match(one.text, /Checked 20 Oct 2026/);
  const many = await compareRepos(f.deps, { repos: ["a/b", "c/d"] });
  assert.match(many.text, /a\/b: Worth your time, checked 20 Oct 2026\./);
  assert.match(many.text, /c\/d: Long shot, checked 2 Nov 2026\./);
});

test("a report past 30 days starts a check and shows the old verdict with its date meanwhile", async () => {
  const f = fake({ cached: { "o/year": report("o/year", "viable", { at: "2025-10-01T00:00:00Z" }) }, polls: () => Infinity });
  const a = await checkRepo(f.deps, { repo: "o/year" });
  assert.deepEqual(f.started, ["o/year"]);
  assert.equal(a.isError, false);
  assert.equal(a.structured.status, "old");
  assert.equal(a.structured.verdict, "Worth your time");
  assert.equal(a.structured.checked_at, "2025-10-01T00:00:00Z");
  assert.match(a.structured.note ?? "", /1 Oct 2025/);
  assert.match(a.structured.note ?? "", /fresh check is running/);
  assert.doesNotMatch(a.structured.note ?? "", /older version/);
  assert.match(a.text, /Checked 1 Oct 2025/);
});

test("a report past 30 days whose check finishes in time shows the new verdict", async () => {
  const f = fake({ cached: { "o/year": report("o/year", "viable", { at: "2025-10-01T00:00:00Z" }) }, done: (r) => report(r, "long_shot") });
  const a = await checkRepo(f.deps, { repo: "o/year" });
  assert.equal(a.structured.status, "checked");
  assert.equal(a.structured.verdict, "Long shot");
});

test("30 days is the line: under it starts nothing, past it starts a check", async () => {
  const day = 86_400_000;
  const at = (ms: number) => new Date(Date.parse("2026-11-09T00:00:00Z") - ms).toISOString();
  assert.equal(MAX_REPORT_AGE_DAYS, 30);
  const under = fake({ cached: { "a/b": report("a/b", "viable", { at: at(30 * day) }) } });
  const a = await checkRepo(under.deps, { repo: "a/b" });
  assert.equal(a.structured.status, "checked");
  assert.deepEqual(under.started, []);
  const past = fake({ cached: { "a/b": report("a/b", "viable", { at: at(30 * day + 1000) }) }, polls: () => Infinity });
  const b = await checkRepo(past.deps, { repo: "a/b" });
  assert.equal(b.structured.status, "old");
  assert.deepEqual(past.started, ["a/b"]);
});

test("the 30 days match the monthly refresh the server is deployed with", () => {
  const settings = readFileSync(new URL("../../../server/holt_server/settings.py", import.meta.url), "utf-8");
  assert.match(settings, /refresh_monthly_hours: float = Field\(720,/);
  assert.equal(720 / 24, MAX_REPORT_AGE_DAYS);
});

test("compare_repos: old reports go through the per-call cap and the budget", async () => {
  const cached: Record<string, Report> = {};
  const names = Array.from({ length: 7 }, (_, i) => `o/r${i}`);
  for (const n of names) cached[n] = report(n, "viable", { at: "2025-10-01T00:00:00Z" });
  const f = fake({ cached, polls: () => Infinity });
  const a = await compareRepos(f.deps, { repos: names });
  assert.equal(f.started.length, COMPARE_STARTS);
  assert.ok(a.structured.repos.every((r) => r.status === "old" && r.verdict === "Worth your time"));
  // Running or not yet started: all want another call.
  assert.deepEqual(a.structured.call_again, names);
  assert.match(a.structured.repos.find((r) => r.repo === "o/r6")!.note ?? "", /Call again/);

  const over = fake({ cached, start: () => err(429, "rate_limited") });
  const b = await compareRepos(over.deps, { repos: names });
  assert.deepEqual(over.started, ["o/r0"]);
  assert.ok(b.structured.repos.every((r) => r.status === "old" && r.verdict === "Worth your time"));
  assert.deepEqual(b.structured.call_again, []);
});

// --- a re-check that fails -------------------------------------------------------------

const OLD_KINDS: [string, { outdated?: boolean; at?: string }, string][] = [
  ["outdated", { outdated: true }, "outdated"],
  ["past 30 days", { at: "2025-10-01T00:00:00Z" }, "old"],
];

for (const [name, kind, status] of OLD_KINDS) {
  test(`check_repo: a failed re-check of a report ${name} keeps the old verdict, with a note and no error`, async () => {
    const failures: Record<string, Partial<Parameters<typeof fake>[0]>> = {
      "the start fails": { start: () => err(502, "upstream", "Holt's analysis server isn't answering right now.") },
      "the job fails": { done: () => ({ error: { code: "upstream", message: "GitHub didn't answer in time." } as ApiError }) },
      "the budget is used up": { start: () => err(429, "rate_limited") },
    };
    for (const [how, o] of Object.entries(failures)) {
      const f = fake({ cached: { "o/r": report("o/r", "long_shot", kind) }, ...o });
      const a = await checkRepo(f.deps, { repo: "o/r" });
      assert.equal(a.isError, false, how);
      assert.equal(a.structured.status, status, how);
      assert.equal(a.structured.verdict, "Long shot", how);
      assert.ok(a.structured.note, how);
      assert.match(a.text, /Long shot/, how);
    }
  });

  test(`check_repo: a re-check of a report ${name} saying not_found wins: the repo is gone or private`, async () => {
    for (const o of [
      { start: () => err(404, "not_found") },
      { done: () => ({ error: { code: "not_found", message: "gone" } as ApiError }) },
    ]) {
      const f = fake({ cached: { "o/r": report("o/r", "viable", kind) }, ...o });
      const a = await checkRepo(f.deps, { repo: "o/r" });
      assert.equal(a.structured.status, "not_found");
      assert.equal(a.structured.verdict, null);
      assert.equal(a.isError, false);
    }
  });
}

test("a job that can't be found again isn't 'no such repo': the old verdict stays", async () => {
  const f = fake({ cached: { "o/r": report("o/r", "viable", { outdated: true }) } });
  f.deps.jobStatus = async () => err(404, "not_found", "We couldn't find that check. It may have expired.");
  const a = await checkRepo(f.deps, { repo: "o/r" });
  assert.equal(a.structured.status, "outdated");
  assert.equal(a.structured.verdict, "Worth your time");

  const cold = fake();
  cold.deps.jobStatus = f.deps.jobStatus;
  const b = await checkRepo(cold.deps, { repo: "o/cold" });
  assert.equal(b.structured.status, "error");
  assert.doesNotMatch(b.text, /can't find this repository/);
});

test("compare_repos: a failed re-check is ranked by its old verdict and not asked for again", async () => {
  const f = fake({
    cached: {
      "o/failed": report("o/failed", "viable", { outdated: true }),
      "o/gone": report("o/gone", "viable", { outdated: true }),
      "o/long": report("o/long", "long_shot", { odds: "long" }),
    },
    start: (r) => (r === "o/gone" ? err(404, "not_found") : err(502, "upstream")),
  });
  const a = await compareRepos(f.deps, { repos: ["o/long", "o/gone", "o/failed"] });
  assert.equal(a.isError, undefined);
  assert.deepEqual(a.structured.repos.map((r) => [r.repo, r.status]), [["o/failed", "outdated"], ["o/long", "checked"], ["o/gone", "not_found"]]);
  assert.equal(a.structured.repos[0].verdict, "Worth your time");
  assert.deepEqual(a.structured.call_again, []);
});

test("the notes never promise the link has a newer verdict", async () => {
  for (const kind of [{ outdated: true }, { at: "2025-10-01T00:00:00Z" }]) {
    for (const o of [{ start: () => err(429, "rate_limited") }, { start: () => err(502, "upstream") }]) {
      const a = await checkRepo(fake({ cached: { "o/r": report("o/r", "viable", kind) }, ...o }).deps, { repo: "o/r" });
      assert.doesNotMatch(a.text, /current one/i);
      assert.match(a.structured.note ?? "", /linked report may show this same older verdict/);
    }
  }
});

// --- what the numbers say --------------------------------------------------------------

test("a repo with recent outside pull requests isn't described as having none", async () => {
  const noDecided = report("o/new", "insufficient_evidence", { stats: { outsider_attempts: 0, outsider_merged: 0, still_open: 12, median_first_response_hours: null } });
  const a = await checkRepo(fake({ cached: { "o/new": noDecided } }).deps, { repo: "o/new" });
  assert.equal(a.structured.numbers?.still_open, 12);
  assert.doesNotMatch(a.text, /no outside pull requests/);
  assert.match(a.text, /12 outside pull requests opened in the last 14 days, too recent to count/);

  const one = report("o/one", "insufficient_evidence", { stats: { outsider_attempts: 0, outsider_merged: 0, still_open: 1, median_first_response_hours: null } });
  assert.match((await checkRepo(fake({ cached: { "o/one": one } }).deps, { repo: "o/one" })).text, /1 outside pull request opened in the last 14 days, too recent to count/);

  const old = report("o/old", "insufficient_evidence", { stats: { outsider_attempts: 0, outsider_merged: 0, still_open: 0, too_old: 4, median_first_response_hours: null } });
  const c = await checkRepo(fake({ cached: { "o/old": old } }).deps, { repo: "o/old" });
  assert.doesNotMatch(c.text, /no outside pull requests/);
  assert.match(c.text, /4 outside pull requests, all older than a year/);

  const none = report("o/none", "insufficient_evidence", { stats: { outsider_attempts: 0, outsider_merged: 0, still_open: 0, too_old: 0, median_first_response_hours: null } });
  assert.match((await checkRepo(fake({ cached: { "o/none": none } }).deps, { repo: "o/none" })).text, /no outside pull requests in what Holt read/);

  // Recent and year-old together: neither is called none.
  const mixed = report("o/mixed", "not_viable", { stats: { outsider_attempts: 0, outsider_merged: 0, still_open: 2, too_old: 90, median_first_response_hours: null } });
  const m = await checkRepo(fake({ cached: { "o/mixed": mixed } }).deps, { repo: "o/mixed" });
  assert.doesNotMatch(m.text, /none older|none recent/);
  assert.match(m.text, /2 outside pull requests opened in the last 14 days, too recent to count, and 90 older than a year; none in between to go on/);

  // With decided ones too, the recent ones are named beside them.
  const both = await checkRepo(fake({ cached: { "o/both": report("o/both", "viable", { stats: { still_open: 5 } }) } }).deps, { repo: "o/both" });
  assert.match(both.text, /20 of 100 outside pull requests merged \(20%\).*5 more too recent to count/);
});

// --- starter_issues' promise -----------------------------------------------------------

test("starter_issues says some may be taken and tells the model to pass on_it on", async () => {
  const server = mcpServer(fake().deps);
  const [x, y] = InMemoryTransport.createLinkedPair();
  await server.connect(x);
  const client = new Client({ name: "test", version: "0" });
  await client.connect(y);
  const { tools } = await client.listTools();
  const d = tools.find((t) => t.name === "starter_issues")!.description ?? "";
  assert.doesNotMatch(d, /nobody has taken/);
  assert.match(d, /free ones first/i);
  assert.match(d, /may already be taken/);
  assert.match(d, /on_it/);
  const check = tools.find((t) => t.name === "check_repo")!.description ?? "";
  assert.doesNotMatch(check, /lately/);
  assert.match(check, /30 days/);
  await client.close();
  await server.close();
  const docs = readFileSync(new URL("../../../docs/MCP.md", import.meta.url), "utf-8");
  assert.doesNotMatch(docs, /nobody has taken/);
  assert.match(docs, /may already be taken/);
});

// --- compare_repos ------------------------------------------------------------------

test("compare_repos: 30 repos in mixed states, best first, a few new checks per call", async () => {
  const cached: Record<string, Report> = {};
  const add = (r: Report) => (cached[r.repo.toLowerCase()] = r);
  add(report("a/viable-fair", "viable", { odds: "fair", stats: { outsider_merged: 60 } }));
  add(report("a/viable-good-small", "viable", { odds: "good", stats: { outsider_attempts: 8, outsider_merged: 6 } }));
  add(report("a/viable-good-big", "viable", { odds: "good", stats: { outsider_attempts: 105, outsider_merged: 60 } }));
  add(report("a/long", "long_shot", { odds: "long" }));
  add(report("a/not", "not_viable"));
  add(report("a/thin", "insufficient_evidence"));
  add(report("a/mine", "personal"));
  add(report("a/list", "catalogue"));
  add(report("a/outdated", "long_shot", { outdated: true }));
  const repos = [
    "a/list", "a/mine", "a/not", "a/thin", "a/long", "a/viable-fair", "a/viable-good-small", "a/viable-good-big",
    "a/outdated", "not a repo", "A/Viable-Fair",
    // Cold: the first COMPARE_STARTS get checks, one never finishes, one doesn't exist.
    ...Array.from({ length: 19 }, (_, i) => `cold/r${i}`),
  ];
  assert.equal(repos.length, 30);
  const f = fake({
    cached,
    polls: (r) => (r === "cold/r2" ? Infinity : 2),
    start: undefined,
    done: (r) => report(r, "long_shot", { odds: "fair" }),
  });
  const realStart = f.deps.startAnalysis;
  f.deps.startAnalysis = async (r) => (r === "cold/r3" ? (f.started.push(r), err(404, "not_found")) : realStart(r));

  const a = await compareRepos(f.deps, { repos });
  const rows = a.structured.repos;
  // One row per distinct repo (the duplicate in other casing is dropped), the invalid one included.
  assert.equal(rows.length, 29);
  // At most COMPARE_STARTS new checks; the outdated one counted among them.
  assert.equal(f.started.length, COMPARE_STARTS);
  assert.deepEqual(f.started, ["a/outdated", "cold/r0", "cold/r1", "cold/r2", "cold/r3"]);
  assert.ok(f.slept <= COMPARE_WAIT_MS);

  const order = rows.map((r) => r.repo);
  // Verdict first; among "Worth your time", the odds, then the merged share
  // with a small sample pulled toward typical (60 of 105 beats 6 of 8).
  assert.deepEqual(order.slice(0, 3), ["a/viable-good-big", "a/viable-good-small", "a/viable-fair"]);
  assert.ok(mergedShare({ outsider_merged: 60, outsider_attempts: 105 }) > mergedShare({ outsider_merged: 6, outsider_attempts: 8 }));
  // Then the long shots: fair odds (the finished cold checks) before long.
  const verdicts = rows.filter((r) => r.verdict).map((r) => r.verdict);
  const rank = ["Worth your time", "Long shot", "Not enough evidence", "Not worth your time", "Personal project", "A list, not code"];
  assert.deepEqual([...verdicts].sort((x, y) => rank.indexOf(x!) - rank.indexOf(y!)), verdicts);
  assert.equal(rows.find((r) => r.repo === "a/outdated")!.status, "checked"); // its refresh finished
  assert.equal(rows.find((r) => r.repo === "cold/r0")!.status, "checked");
  assert.equal(rows.find((r) => r.repo === "cold/r2")!.status, "checking");
  assert.equal(rows.find((r) => r.repo === "cold/r3")!.status, "not_found");
  assert.equal(rows.find((r) => r.repo === "cold/r4")!.status, "not_checked");
  // Without a verdict, after every verdict; the invalid entry last.
  const firstEmpty = rows.findIndex((r) => !r.verdict);
  assert.ok(rows.slice(firstEmpty).every((r) => !r.verdict));
  assert.equal(rows.at(-1)!.status, "invalid");
  // What to ask again for: the running one and those not started.
  assert.deepEqual(a.structured.call_again, ["cold/r2", ...Array.from({ length: 15 }, (_, i) => `cold/r${i + 4}`)]);
  assert.match(a.text, /^1\. a\/viable-good-big: Worth your time, checked 1 Nov 2026\./);
  assert.match(a.text, /Call compare_repos again in a minute with: cold\/r2, cold\/r4/);
  assert.doesNotMatch(JSON.stringify(a), /secret evidence/);
});

test("compare_repos: once the budget is used up, nothing more is started and the rest are 'busy'", async () => {
  const f = fake({ cached: { "a/old": report("a/old", "viable", { outdated: true }) }, start: () => err(429, "rate_limited") });
  const a = await compareRepos(f.deps, { repos: ["c/one", "c/two", "a/old", "c/three"] });
  assert.deepEqual(f.started, ["c/one"]);
  const by = Object.fromEntries(a.structured.repos.map((r) => [r.repo, r]));
  assert.equal(by["c/one"].status, "busy");
  assert.equal(by["c/three"].status, "busy");
  // An outdated report is still worth showing, marked as such.
  assert.equal(by["a/old"].status, "outdated");
  assert.equal(by["a/old"].verdict, "Worth your time");
  assert.equal(a.structured.repos[0].repo, "a/old");
  assert.deepEqual(a.structured.call_again, []);
});

test("compare_repos: the text gives each verdict's reason, as check_repo's does", async () => {
  const f = fake({ cached: { "a/b": report("a/b", "not_viable", { stats: { outsider_merged: 50 } }) } });
  const a = await compareRepos(f.deps, { repos: ["a/b"] });
  assert.match(a.text, /^1\. a\/b: Not worth your time, checked 1 Nov 2026\. Reason for a\/b\. 50 of 100 outside pull requests merged/);
});

test("compare_repos: all cached is all at once", async () => {
  const f = fake({ cached: { "a/b": report("a/b", "long_shot"), "c/d": report("c/d") } });
  const a = await compareRepos(f.deps, { repos: ["a/b", "c/d"] });
  assert.deepEqual(f.started, []);
  assert.equal(f.slept, 0);
  assert.deepEqual(a.structured.repos.map((r) => r.repo), ["c/d", "a/b"]);
  assert.deepEqual(a.structured.call_again, []);
});

// --- starter_issues -----------------------------------------------------------------

const issue = (n: number, over: Partial<StarterIssue> = {}): StarterIssue =>
  ({ number: n, title: `Issue ${n}`, url: `https://github.com/a/b/issues/${n}`, labels: ["good first issue"], comments: 0, created_at: null, open_prs: 0, people: 0, on_it: "Nobody on it yet", why: ["labelled good first issue"], areas: ["code"], beginner: true, ...over }) as StarterIssue;

test("starter_issues: the server's list, cut to the limit, with a next step each", async () => {
  let asked = 0;
  const f = fake({ issues: (repo, limit) => ((asked = limit), { ok: true, data: { repo: "a/B", issues: [issue(1), issue(2, { open_prs: 1, on_it: "1 open pull request" }), issue(3)] } }) });
  const a = await starterIssues(f.deps, { repo: "a/b", limit: 2 });
  assert.equal(asked, 2);
  assert.equal(a.structured.status, "ok");
  assert.equal(a.structured.repo, "a/B");
  assert.equal(a.structured.link, "https://githolt.com/a/B");
  assert.equal(a.structured.issues.length, 2);
  assert.match(a.structured.issues[1].next_step, /open pull request/);
  assert.match(a.text, /#2 Issue 2 \(1 open pull request\)/);
  // Out of range limits are clamped.
  await starterIssues(f.deps, { repo: "a/b", limit: 500 });
  assert.equal(asked, 20);
  await starterIssues(f.deps, { repo: "a/b" });
  assert.equal(asked, 5);
});

test("starter_issues: busy, not shipped and bad names are plain answers", async () => {
  const busy = await starterIssues(fake({ issues: () => err(429, "rate_limited") }).deps, { repo: "a/b" });
  assert.equal(busy.structured.status, "busy");
  assert.equal(busy.isError, false);
  const off = await starterIssues(fake({ issues: () => err(501, "not_implemented") }).deps, { repo: "a/b" });
  assert.equal(off.structured.status, "unavailable");
  const bad = await starterIssues(fake().deps, { repo: "nope" });
  assert.equal(bad.structured.status, "invalid");
  assert.equal(bad.isError, true);
});

// --- through the SDK --------------------------------------------------------------

test("the MCP server lists three read-only tools and its answers match their output schemas", async () => {
  const f = fake({
    cached: { "pallets/flask": report("pallets/flask") },
    polls: (r) => (r === "octo/slow" ? Infinity : 2),
    issues: () => ({ ok: true, data: { repo: "pallets/flask", issues: [issue(7)] } }),
  });
  const server = mcpServer(f.deps);
  const [a, b] = InMemoryTransport.createLinkedPair();
  await server.connect(a);
  const client = new Client({ name: "test", version: "0" });
  await client.connect(b);
  try {
    const { tools } = await client.listTools();
    assert.deepEqual(tools.map((t) => t.name).sort(), ["check_repo", "compare_repos", "starter_issues"]);
    for (const t of tools) {
      assert.equal(t.annotations?.readOnlyHint, true, t.name);
      assert.equal(t.annotations?.destructiveHint, false, t.name);
      assert.ok(t.outputSchema, t.name);
      assert.ok((t.description ?? "").length > 80, t.name);
    }
    assert.match(client.getInstructions() ?? "", /don't swap in a verdict of your own/);
    // The client checks structuredContent against each tool's outputSchema.
    const one = await client.callTool({ name: "check_repo", arguments: { repo: "pallets/flask" } });
    assert.equal((one.structuredContent as { verdict: string }).verdict, "Worth your time");
    assert.equal((one.content as { type: string }[])[0].type, "text");
    const slow = await client.callTool({ name: "check_repo", arguments: { repo: "octo/slow" } });
    assert.equal((slow.structuredContent as { status: string }).status, "checking");
    const bad = await client.callTool({ name: "check_repo", arguments: { repo: "nope" } });
    assert.equal(bad.isError, true);
    const many = await client.callTool({ name: "compare_repos", arguments: { repos: ["pallets/flask", "octo/new", "nope"] } });
    assert.equal((many.structuredContent as { repos: unknown[] }).repos.length, 3);
    const iss = await client.callTool({ name: "starter_issues", arguments: { repo: "pallets/flask", limit: 3 } });
    assert.equal((iss.structuredContent as { issues: unknown[] }).issues.length, 1);
    // More than 30 repos is refused by the input schema.
    const tooMany = await client.callTool({ name: "compare_repos", arguments: { repos: Array.from({ length: 31 }, (_, i) => `a/r${i}`) } });
    assert.equal(tooMany.isError, true);
  } finally {
    await client.close();
    await server.close();
  }
});
