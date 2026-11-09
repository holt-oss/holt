// What Holt's MCP connector (app/mcp/route.ts, API.md "MCP") answers: the
// three tools' logic, apart from the SDK (lib/mcp-server.ts) and the API
// client (lib/api.ts), so it runs under `node --test` with the server mocked.
//
// A chat gets what a signed-out visitor's teaser and the browser extension
// already get: the verdict, its reason, the odds and the headline numbers,
// plus the link to the report. No evidence, README, playbook or AI text.
// The verdict is the engine's (the rules report); nothing here changes it.
import { humanHours, nextStep, pct, shortDate } from "./format.ts";
import { parseRepoInput } from "./repo.ts";
import type { AnalysisStart, ApiError, JobStatus, Report, Result, StarterIssue, Verdict } from "./types.ts";

/** The server, as the connector uses it. lib/api.ts in production, a mock in tests. */
export interface McpDeps {
  getReport(repo: string): Promise<Result<Report>>;
  startAnalysis(repo: string): Promise<Result<AnalysisStart>>;
  jobStatus(jobId: string): Promise<Result<JobStatus>>;
  starterIssues(repo: string, limit: number): Promise<Result<{ repo: string; issues: StarterIssue[] }>>;
  /** The site's address, for the report links: https://githolt.com. */
  siteUrl: string;
  sleep(ms: number): Promise<void>;
  now(): number;
}

/** How long check_repo waits for a new check (one usually takes about 20 seconds). */
export const CHECK_WAIT_MS = 25_000;
/** How long compare_repos waits for the checks it started. */
export const COMPARE_WAIT_MS = 20_000;
export const POLL_MS = 1_500;
export const MAX_COMPARE = 30;
/** New checks one compare_repos call may start; the rest wait for the next call. */
export const COMPARE_STARTS = 5;
export const MAX_ISSUES = 20;
/**
 * A report older than this gets a new check, as an outdated one does. The same
 * age as the warm pass's monthly refresh (HOLT_REFRESH_MONTHLY_HOURS, 720), so
 * a chat doesn't re-read what the refresh would soon read anyway.
 */
export const MAX_REPORT_AGE_DAYS = 30;
const DAY_MS = 86_400_000;

/**
 * Where a repo stands, for the model:
 * - `checked`: the verdict comes from a report under 30 days old by this version of Holt; `checked_at` says when.
 * - `outdated`: the verdict came from an older version of Holt; a fresh check
 *   is running, waiting or couldn't run (`note` says which), and the old verdict is shown meanwhile.
 * - `old`: the same for a report more than 30 days old.
 * - `checking`: a check is running; call again in a minute.
 * - `not_checked`: nothing started in this call (compare_repos starts a few at a time); call again.
 * - `busy`: Holt is starting no new checks from chats right now; try later, or open the link.
 * - `not_found`: no such public repository.
 * - `invalid`: not a GitHub repository name.
 * - `error`: something failed; `note` says what.
 */
export type RepoStatus = "checked" | "outdated" | "old" | "checking" | "not_checked" | "busy" | "not_found" | "invalid" | "error";

export interface Numbers {
  /** Decided pull requests from people outside the project's team: opened more than 14 days before the report. Every other count but the last two is out of these. */
  outside_prs: number;
  outside_prs_merged: number;
  /** outside_prs_merged as a whole percentage of outside_prs. */
  merged_percent: number;
  /** "14 hours"; null when nobody outside got a reply. */
  typical_first_reply: string | null;
  typical_first_reply_hours: number | null;
  /** Outside pull requests that never got a reply. */
  no_reply: number;
  /** People whose first pull request here was merged. */
  first_timers_merged: number;
  /** Outside pull requests closed without a word. */
  closed_without_a_word: number;
  /** The date (YYYY-MM-DD) an outside pull request was last merged; null when unknown. */
  last_outside_merge: string | null;
  /** Outside pull requests opened in the 14 days before the report: too recent to count in the numbers above. */
  still_open: number;
  /** Outside pull requests opened more than a year ago: read, and in no count. */
  older_than_a_year: number;
}

export interface RepoRow {
  repo: string;
  status: RepoStatus;
  /** As the site says it: "Worth your time", "Long shot", "Not worth your time", "Not enough evidence", "Personal project", "A list, not code". */
  verdict: string | null;
  /** The one-sentence reason for the verdict. */
  reason: string | null;
  /** How likely an outside pull request is to get anywhere, in words; null for verdicts that have none. */
  odds: string | null;
  numbers: Numbers | null;
  /** When the report was made (ISO 8601). */
  checked_at: string | null;
  /** The full report on Holt. */
  link: string;
  /** What to do about the status, in plain English; null when there is nothing to add. */
  note: string | null;
}

export interface CompareOut {
  /** Best first: verdict, then the odds and how often outside work is merged, as Holt's own boards rank. Repos without a verdict last. */
  repos: RepoRow[];
  /** Repos to pass to compare_repos again, in a minute, for their verdicts. */
  call_again: string[];
}

export interface IssueRow {
  number: number;
  title: string;
  url: string;
  labels: string[];
  /** "Nobody on it yet", "1 open pull request", …; null when unknown. */
  on_it: string | null;
  /** Why it suits a newcomer. */
  why: string[];
  next_step: string;
}

export interface IssuesOut {
  repo: string;
  status: "ok" | "busy" | "not_found" | "invalid" | "unavailable" | "error";
  issues: IssueRow[];
  link: string;
  note: string | null;
}

export interface ToolAnswer<T> {
  structured: T;
  text: string;
  isError?: boolean;
}

// --- notes -------------------------------------------------------------------------

const NOTE = {
  checking: "Holt is still checking this repo. Call again in a minute.",
  notChecked: "Not checked yet: Holt checks a few new repos per call. Call again with the repos in call_again.",
  busy: "Holt is busy and isn't starting new checks from chats right now. Try again later, or open the link to check it on the site.",
  notFound: "Holt can't find this repository on GitHub. It may be private, renamed or misspelled.",
  invalid: "That isn't a GitHub repository. Use owner/name, like pallets/flask, or a github.com link.",
} as const;

const LABELS: Record<Verdict, string> = {
  viable: "Worth your time",
  long_shot: "Long shot",
  not_viable: "Not worth your time",
  insufficient_evidence: "Not enough evidence",
  personal: "Personal project",
  catalogue: "A list, not code",
};

// --- rows ------------------------------------------------------------------------------

export function reportLink(siteUrl: string, repo: string): string {
  return `${siteUrl.replace(/\/$/, "")}/${repo}`;
}

/** The repo as typed, made into owner/name, or null. */
export function repoName(input: string): string | null {
  const ref = parseRepoInput(String(input ?? "").slice(0, 300));
  return ref ? `${ref.owner}/${ref.repo}` : null;
}

export function numbersOf(r: Pick<Report, "stats">): Numbers {
  const s = r.stats;
  const reply = s.median_first_response_hours ?? null;
  return {
    outside_prs: s.outsider_attempts,
    outside_prs_merged: s.outsider_merged,
    merged_percent: pct(s.outsider_merged, s.outsider_attempts),
    typical_first_reply: reply == null ? null : humanHours(reply),
    typical_first_reply_hours: reply == null ? null : Math.round(reply * 10) / 10,
    no_reply: s.no_reply,
    first_timers_merged: s.first_time_merged_authors,
    closed_without_a_word: s.closed_silently,
    last_outside_merge: s.timing?.last_outside_merge ?? null,
    still_open: s.still_open ?? 0,
    older_than_a_year: s.too_old ?? 0,
  };
}

function emptyRow(siteUrl: string, repo: string, status: RepoStatus, note: string | null): RepoRow {
  return { repo, status, verdict: null, reason: null, odds: null, numbers: null, checked_at: null, link: reportLink(siteUrl, repo), note };
}

/** Whatever was typed, cut short, linking to the site: it isn't a repo, so it has no report. */
function invalidRow(siteUrl: string, raw: unknown): RepoRow {
  return { ...emptyRow(siteUrl, String(raw ?? "").slice(0, 100), "invalid", NOTE.invalid), link: siteUrl.replace(/\/$/, "") };
}

export function reportRow(siteUrl: string, r: Report, status: "checked" | "outdated" | "old" = "checked", note: string | null = null): RepoRow {
  return {
    repo: r.repo,
    status,
    verdict: r.headline || LABELS[r.verdict],
    reason: r.verdict_line,
    odds: r.odds?.text ?? null,
    numbers: numbersOf(r),
    checked_at: r.generated_at,
    link: reportLink(siteUrl, r.repo),
    note,
  };
}

function failureRow(siteUrl: string, repo: string, e: ApiError, status: number): RepoRow {
  if (e.code === "rate_limited") return emptyRow(siteUrl, repo, "busy", NOTE.busy);
  if (e.code === "not_found") return emptyRow(siteUrl, repo, "not_found", NOTE.notFound);
  if (e.code === "invalid_repo" || (status === 400 && e.code === "invalid_request")) return invalidRow(siteUrl, repo);
  return emptyRow(siteUrl, repo, "error", e.message || "Something went wrong on Holt's side. Try again soon.");
}

// --- one repo ------------------------------------------------------------------------

/** A report that needs a new check, and why: an older engine made it, or it is past MAX_REPORT_AGE_DAYS. */
type Stale = { report: Report; why: "outdated" | "old" };

/** A repo whose cache was read: a usable report, one that needs a new check, nothing yet, or a failure. */
type Looked =
  | { kind: "fresh"; report: Report }
  | ({ kind: "stale" } & Stale)
  | { kind: "missing" }
  | { kind: "failed"; row: RepoRow };

function isOld(r: Report, now: number): boolean {
  return now - Date.parse(r.generated_at) > MAX_REPORT_AGE_DAYS * DAY_MS;
}

/** What is happening about a stale report while its old verdict is shown. */
type StaleState = "running" | "waiting" | "busy" | "failed";

const SAME_REPORT = "The linked report may show this same older verdict.";
const STALE_NEXT: Record<StaleState, string> = {
  running: "A fresh check is running. Call again in a minute for the new verdict.",
  waiting: "Call again to start a fresh check.",
  busy: `Holt is too busy to check it again right now. ${SAME_REPORT}`,
  failed: `Holt tried to check it again and couldn't. ${SAME_REPORT}`,
};

function staleRanked(siteUrl: string, s: Stale, state: StaleState): Ranked {
  const date = shortDate(s.report.generated_at);
  const from = s.why === "outdated"
    ? `This verdict is from an older version of Holt${date ? `, on ${date}` : ""}.`
    : `This verdict is from ${date}, over ${MAX_REPORT_AGE_DAYS} days ago.`;
  return {
    row: reportRow(siteUrl, s.report, s.why, `${from} ${STALE_NEXT[state]}`),
    report: s.report,
    again: state === "running" || state === "waiting",
  };
}

async function look(d: McpDeps, repo: string): Promise<Looked> {
  const r = await d.getReport(repo);
  if (r.ok) {
    if (r.data.outdated) return { kind: "stale", report: r.data, why: "outdated" };
    return isOld(r.data, d.now()) ? { kind: "stale", report: r.data, why: "old" } : { kind: "fresh", report: r.data };
  }
  // 404 is "no report yet" as well as "no such repo": a check tells them apart.
  if (r.error.code === "not_found") return { kind: "missing" };
  return { kind: "failed", row: failureRow(d.siteUrl, repo, r.error, r.status) };
}

/** A check that was asked for: finished, still running (with its job), or refused. */
type Started = { kind: "done"; report: Report } | { kind: "running"; jobId: string } | { kind: "failed"; error: ApiError; status: number };

async function start(d: McpDeps, repo: string): Promise<Started> {
  const r = await d.startAnalysis(repo);
  if (!r.ok) return { kind: "failed", error: r.error, status: r.status };
  if (r.data.status === "done") return { kind: "done", report: r.data.report };
  return { kind: "running", jobId: r.data.job_id };
}

/** Polls a job until it ends or `deadline`; null while it is still running then. */
async function waitFor(d: McpDeps, jobId: string, deadline: number): Promise<Started | null> {
  for (;;) {
    const left = deadline - d.now();
    if (left <= 0) return null;
    await d.sleep(Math.min(POLL_MS, left));
    const r = await d.jobStatus(jobId);
    if (!r.ok) {
      // A poll that failed once isn't the check failing; give up only on a job
      // that's gone. Its 404 says nothing about the repo, so it mustn't read as
      // "no such repository" in `settled`.
      if (r.status === 404) return { kind: "failed", error: { code: "upstream", message: "Holt lost track of this check. Try again soon." }, status: 502 };
      continue;
    }
    if (r.data.status === "done" && r.data.report) return { kind: "done", report: r.data.report };
    if (r.data.status === "error") {
      return { kind: "failed", error: r.data.error ?? { code: "internal", message: "The check failed. Try again soon." }, status: 500 };
    }
  }
}

/**
 * The answer once a check ended (or not, by `deadline`). A stale report's old
 * verdict stays through anything but "no such repo": a check that says so
 * means the repo is gone or private, and that beats what it was once.
 */
function settled(d: McpDeps, repo: string, end: Started | null, stale: Stale | null): Ranked {
  if (end?.kind === "done") return { row: reportRow(d.siteUrl, end.report), report: end.report, again: false };
  if (end === null || end.kind === "running") {
    return stale ? staleRanked(d.siteUrl, stale, "running") : { row: emptyRow(d.siteUrl, repo, "checking", NOTE.checking), report: null, again: true };
  }
  if (stale && end.error.code !== "not_found") return staleRanked(d.siteUrl, stale, end.error.code === "rate_limited" ? "busy" : "failed");
  return { row: failureRow(d.siteUrl, stale?.report.repo ?? repo, end.error, end.status), report: null, again: false };
}

// --- check_repo -----------------------------------------------------------------------

export async function checkRepo(d: McpDeps, input: { repo: string }): Promise<ToolAnswer<RepoRow>> {
  const repo = repoName(input.repo);
  if (!repo) {
    return { structured: invalidRow(d.siteUrl, input.repo), text: NOTE.invalid, isError: true };
  }
  const deadline = d.now() + CHECK_WAIT_MS;
  const seen = await look(d, repo);
  let row: RepoRow;
  if (seen.kind === "fresh") row = reportRow(d.siteUrl, seen.report);
  else if (seen.kind === "failed") row = seen.row;
  else {
    const s = await start(d, repo);
    row = settled(d, repo, s.kind === "running" ? await waitFor(d, s.jobId, deadline) : s, seen.kind === "stale" ? seen : null).row;
  }
  // "No such repo" and "busy" are answers; only a failure on Holt's side is an error.
  return { structured: row, text: rowText(row), isError: row.status === "error" };
}

// --- compare_repos --------------------------------------------------------------------

const VERDICT_RANK: Record<Verdict, number> = {
  viable: 0,
  long_shot: 1,
  insufficient_evidence: 2,
  not_viable: 3,
  personal: 4,
  catalogue: 5,
};
const ODDS_RANK: Record<string, number> = { good: 0, fair: 1, long: 2 };
// Rows without a verdict come after every verdict, by status, then in the order they were asked for.
const STATUS_RANK: Record<RepoStatus, number> = { checked: 1, outdated: 1, old: 1, checking: 1, not_checked: 2, busy: 3, not_found: 4, error: 5, invalid: 6 };

// Holt's boards rank by (server/holt_server/discover.py, `welcoming_key` and
// `merged_share`): the odds, then the share of outside pull requests merged as
// if 10 more at a typical 20% had been seen (6 of 8 is less sure than 60 of
// 105), then the reply time and how many outsiders tried. The Compare page puts
// the verdict before any number (lib/compare.ts, compareTitle); so does this.
const PRIOR_PRS = 10;
const PRIOR_RATE = 0.2;

export function mergedShare(s: Pick<Report["stats"], "outsider_merged" | "outsider_attempts">): number {
  return (s.outsider_merged + PRIOR_RATE * PRIOR_PRS) / (s.outsider_attempts + PRIOR_PRS);
}

/** A row, the report it ranks by (none: it goes after every verdict), and whether another call could improve it. */
type Ranked = { row: RepoRow; report: Report | null; again: boolean };

function rankKey({ row, report }: Ranked): (number | string)[] {
  if (!report) return [STATUS_RANK[row.status]];
  const s = report.stats;
  return [
    0,
    VERDICT_RANK[report.verdict] ?? 9,
    report.odds ? ODDS_RANK[report.odds.level] ?? 3 : 3,
    -Math.round(mergedShare(s) * 1000) / 1000,
    s.median_first_response_hours ?? Number.POSITIVE_INFINITY,
    -s.outsider_attempts,
    report.repo.toLowerCase(),
  ];
}

function byRank(a: Ranked, b: Ranked): number {
  const ka = rankKey(a);
  const kb = rankKey(b);
  for (let i = 0; i < Math.min(ka.length, kb.length); i++) {
    const x = ka[i];
    const y = kb[i];
    if (x === y) continue;
    if (typeof x === "number" && typeof y === "number") return x - y;
    return String(x) < String(y) ? -1 : 1;
  }
  return 0; // Array.prototype.sort is stable: ties keep the asked order.
}

/** Runs `fn` over `items`, at most `n` at a time, in order. */
async function pool<T, U>(items: T[], n: number, fn: (t: T) => Promise<U>): Promise<U[]> {
  const out: U[] = new Array(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (next < items.length) {
      const i = next++;
      out[i] = await fn(items[i]);
    }
  }));
  return out;
}

export async function compareRepos(d: McpDeps, input: { repos: string[] }): Promise<ToolAnswer<CompareOut>> {
  const deadline = d.now() + COMPARE_WAIT_MS;
  const asked = (input.repos ?? []).slice(0, MAX_COMPARE);
  const names: string[] = [];
  const ranked: Ranked[] = [];
  for (const raw of asked) {
    const name = repoName(raw);
    if (!name) {
      ranked.push({ row: invalidRow(d.siteUrl, raw), report: null, again: false });
    } else if (!names.some((n) => n.toLowerCase() === name.toLowerCase())) {
      names.push(name);
    }
  }

  // Cached reports first, all of them: reading the cache costs nothing.
  const seen = await pool(names, 8, (n) => look(d, n));

  // New checks, a few per call; stale reports too, since a refresh is new work.
  let starts = 0;
  let busy = false;
  const running: { i: number; jobId: string; stale: Stale | null }[] = [];
  const results: (Ranked | null)[] = names.map(() => null);
  for (let i = 0; i < names.length; i++) {
    const s = seen[i];
    if (s.kind === "fresh") {
      results[i] = { row: reportRow(d.siteUrl, s.report), report: s.report, again: false };
      continue;
    }
    if (s.kind === "failed") {
      results[i] = { row: s.row, report: null, again: false };
      continue;
    }
    const stale = s.kind === "stale" ? s : null;
    if (busy || starts >= COMPARE_STARTS) {
      results[i] = stale
        ? staleRanked(d.siteUrl, stale, busy ? "busy" : "waiting")
        : { row: emptyRow(d.siteUrl, names[i], busy ? "busy" : "not_checked", busy ? NOTE.busy : NOTE.notChecked), report: null, again: !busy };
      continue;
    }
    const st = await start(d, names[i]);
    if (st.kind === "failed" && st.error.code === "rate_limited") busy = true;
    else starts++;
    if (st.kind === "running") running.push({ i, jobId: st.jobId, stale });
    else results[i] = settled(d, names[i], st, stale);
  }

  // Wait, together, for the checks this call started.
  await Promise.all(running.map(async ({ i, jobId, stale }) => {
    results[i] = settled(d, names[i], await waitFor(d, jobId, deadline), stale);
  }));

  const all = [...results.filter((r): r is Ranked => r !== null), ...ranked].sort(byRank);
  const repos = all.map((r) => r.row);
  const call_again = all.filter((r) => r.again).map((r) => r.row.repo);
  const out: CompareOut = { repos, call_again };
  return { structured: out, text: compareText(out) };
}

// --- starter_issues -----------------------------------------------------------------

export async function starterIssues(d: McpDeps, input: { repo: string; limit?: number }): Promise<ToolAnswer<IssuesOut>> {
  const repo = repoName(input.repo);
  const limit = Math.min(MAX_ISSUES, Math.max(1, Math.floor(Number(input.limit) || 5)));
  if (!repo) {
    const out: IssuesOut = { repo: String(input.repo ?? "").slice(0, 100), status: "invalid", issues: [], link: d.siteUrl.replace(/\/$/, ""), note: NOTE.invalid };
    return { structured: out, text: NOTE.invalid, isError: true };
  }
  const link = reportLink(d.siteUrl, repo);
  const r = await d.starterIssues(repo, limit);
  if (!r.ok) {
    const e = r.error;
    const [status, note]: [IssuesOut["status"], string] =
      e.code === "rate_limited" ? ["busy", "Holt is busy right now. Try again later, or open the link."]
        : e.code === "not_found" ? ["not_found", NOTE.notFound]
          : e.code === "invalid_repo" ? ["invalid", NOTE.invalid]
            : r.status === 501 ? ["unavailable", "Holt can't list starter issues yet."]
              : ["error", e.message || "Something went wrong on Holt's side. Try again soon."];
    const out: IssuesOut = { repo, status, issues: [], link, note };
    return { structured: out, text: `${repo}: ${note}`, isError: status === "error" || status === "invalid" };
  }
  const issues: IssueRow[] = r.data.issues.slice(0, limit).map((i) => ({
    number: i.number,
    title: i.title,
    url: i.url,
    labels: i.labels.slice(0, 6),
    on_it: i.on_it ?? null,
    why: i.why.slice(0, 3),
    next_step: nextStep(i),
  }));
  const out: IssuesOut = {
    repo: r.data.repo,
    status: "ok",
    issues,
    link: reportLink(d.siteUrl, r.data.repo),
    note: issues.length ? null : "No open starter issues right now.",
  };
  return { structured: out, text: issuesText(out) };
}

// --- text ------------------------------------------------------------------------------

function numbersText(n: Numbers): string {
  const plural = (k: number) => `${k} outside pull request${k === 1 ? "" : "s"}`;
  if (n.outside_prs === 0) {
    // "None" only when Holt read none: decided ones are a part of what it read.
    if (n.still_open > 0) return `${plural(n.still_open)} opened in the last 14 days, too recent to count; none older to go on`;
    if (n.older_than_a_year > 0) return `${plural(n.older_than_a_year)}, all older than a year; none recent to go on`;
    return "no outside pull requests in what Holt read";
  }
  const parts = [`${n.outside_prs_merged} of ${n.outside_prs} outside pull requests merged (${n.merged_percent}%)`];
  parts.push(n.typical_first_reply ? `first reply typically in ${n.typical_first_reply}` : "no replies to outside pull requests");
  parts.push(`${n.first_timers_merged} first-timer${n.first_timers_merged === 1 ? "" : "s"} merged`);
  if (n.still_open > 0) parts.push(`${n.still_open} more too recent to count`);
  return parts.join(", ");
}

export function rowText(row: RepoRow): string {
  const date = row.checked_at ? shortDate(row.checked_at) : "";
  const lines = [row.verdict ? `${row.repo}: ${row.verdict}.${date ? ` Checked ${date}.` : ""}` : `${row.repo}: ${row.note ?? row.status}`];
  if (row.reason) lines.push(row.reason);
  if (row.numbers) lines.push(`${numbersText(row.numbers)}.`);
  if (row.verdict && row.note) lines.push(row.note);
  lines.push(row.link);
  return lines.join("\n");
}

function compareText(out: CompareOut): string {
  const lines: string[] = [];
  let n = 0;
  for (const r of out.repos) {
    if (r.verdict) {
      n++;
      const date = r.checked_at ? shortDate(r.checked_at) : "";
      const parts = [`${n}. ${r.repo}: ${r.verdict}${date ? `, checked ${date}` : ""}.`];
      if (r.numbers) parts.push(`${numbersText(r.numbers)}.`);
      if (r.note) parts.push(r.note);
      parts.push(r.link);
      lines.push(parts.join(" "));
    } else {
      lines.push(`- ${r.repo}: ${r.note ?? r.status}`);
    }
  }
  if (out.call_again.length) lines.push(`Call compare_repos again in a minute with: ${out.call_again.join(", ")}`);
  return lines.join("\n");
}

function issuesText(out: IssuesOut): string {
  if (!out.issues.length) return `${out.repo}: ${out.note}\n${out.link}`;
  const lines = out.issues.map((i) => `#${i.number} ${i.title}${i.on_it ? ` (${i.on_it})` : ""}: ${i.url}`);
  return [`Starter issues in ${out.repo}, free ones first:`, ...lines, out.link].join("\n");
}
