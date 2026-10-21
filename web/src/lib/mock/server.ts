// An in-memory stand-in for server/ (MOCK_API=1). It follows API.md: cached
// reports return at once, anything else becomes a job with stages over SSE.
import "server-only";
import type {
  AlertSettings, AlertSettingsBody, AnalysisStart, ApiError, DiscoverOut, DiscoverRepo, DiscoverSort, Entitlements, FeedbackOut, FindIndexPart, FindJobStatus, FindQuery, FindResult, FindStart, Contributions, GitHubConnection, History, HistoryItem,
  ContributionType, JobStatus, Me, Mode, Passes, ProfileOut, ProfilePrefs, Recommendation, Recommendations, RepoSearch, Report, Result, SavedList, SavedState, Stats, StarterIssue,
} from "../types";
import type { FeedbackInput } from "../feedback";
import type { Timing } from "../api-schema";
import * as watch from "./alerts";
import { verdictView, withDerived } from "./derived";
import { canonicalName, isMockNotFound, mockAbout, mockFindPool, mockIssues, mockReport, PRECACHED } from "./fixtures";
import { access as mergePlanAccess, mergePlanEvents } from "./merge-plan";
import { playbookEvents } from "./playbook";
import { preflightEvents } from "./preflight";

export { alertCount, alertList, alertSettings, readAlerts, setAlertEmailByToken, setAlertMute } from "./alerts";
export { mergePlanState, startMergePlan } from "./merge-plan";
export { playbookState, unlockPlaybook } from "./playbook";
export { preflightState, startPreflight } from "./preflight";

const JOB_MS = Number(process.env.MOCK_JOB_MS || 6500);
/** Holds every report read back this long: a slow API, for the report page's loading screen. */
const REPORT_MS = Number(process.env.MOCK_REPORT_MS || 0);
const WELCOME_CREDITS = Number(process.env.NEXT_PUBLIC_FREE_AI_QUOTA || 3);
const CLAIM_EVERY_DAYS = 7;
const DAY_MS = 86_400_000;

const STAGES: [at: number, stage: string][] = [
  [0, "Fetching pull requests"],
  [0.3, "Reading threads"],
  [0.6, "Checking evidence"],
  [0.82, "Writing the report"],
];

interface Job {
  id: string;
  repo: string;
  mode: Mode;
  days: number;
  userId?: string;
  started: number;
}

interface FindJob {
  id: string;
  q: FindQuery;
  started: number;
}

interface State {
  cache: Map<string, Report>;
  jobs: Map<string, Job>;
  findJobs: Map<string, FindJob>;
  users: Map<string, { me: Me; history: HistoryItem[] }>;
}

/** Always outdated, and its fresh check always fails (the report page's fallback). */
const OUTDATED = "mock/outdated";

// globalThis so route handlers and pages share one state in dev.
const g = globalThis as unknown as { holtMock?: State };
function state(): State {
  if (!g.holtMock) {
    const cache = new Map<string, Report>();
    for (const repo of PRECACHED) cache.set(key(repo, "rules", 7), mockReport(repo, "rules", 7));
    // A report from older rules whose fresh check fails: the page falls back to it.
    cache.set(key(OUTDATED, "rules", 7), { ...mockReport(OUTDATED, "rules", 7), outdated: true });
    g.holtMock = { cache, jobs: new Map(), findJobs: new Map(), users: new Map() };
  }
  return g.holtMock;
}

function key(repo: string, mode: Mode, days: number) {
  return `${repo.toLowerCase()}|${mode}|${days}`;
}

function err(status: number, code: ApiError["code"], message: string, extra: Partial<ApiError> = {}) {
  return { ok: false as const, status, error: { code, message, ...extra } };
}

function user(id: string) {
  const s = state();
  let u = s.users.get(id);
  if (!u) {
    u = {
      me: {
        plan: "free",
        plan_expires_at: null,
        credits: {
          balance: WELCOME_CREDITS,
          free: WELCOME_CREDITS,
          purchased: 0,
          can_claim: false,
          next_claim_at: new Date(Date.now() + CLAIM_EVERY_DAYS * DAY_MS).toISOString(),
          claim_every_days: CLAIM_EVERY_DAYS,
          ai_available: true,
        },
      },
      history: [
        { job_id: "job_seed_requests", status: "done", repo: "psf/requests", mode: "rules", days: 7, ...verdictView("viable"), verdict: "viable", created_at: new Date(Date.now() - 26 * 3_600_000).toISOString() },
        { job_id: "job_seed_pytorch", status: "done", repo: "pytorch/pytorch", mode: "rules", days: 7, ...verdictView("not_viable"), verdict: "not_viable", created_at: new Date(Date.now() - 50 * 3_600_000).toISOString() },
      ],
    };
    s.users.set(id, u);
  }
  return u;
}

function remember(userId: string | undefined, r: Report) {
  if (!userId) return;
  const h = user(userId).history;
  h.unshift({ job_id: `job_${crypto.randomUUID().slice(0, 12)}`, status: "done", repo: r.repo, mode: r.mode, days: r.days, verdict: r.verdict, headline: r.headline, tone: r.tone, created_at: new Date().toISOString() });
  h.splice(30);
}

function validate(repo: string): Result<string> {
  if (!/^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/.test(repo)) return err(400, "invalid_repo", "That doesn't look like a GitHub repository. Try something like pallets/flask.");
  if (isMockNotFound(repo)) return err(404, "not_found", `We couldn't find ${repo} on GitHub. It may be private, renamed, or misspelled.`);
  return { ok: true, data: canonicalName(repo) };
}

export async function startAnalysis(
  repoIn: string, mode: Mode, days: number, refresh: boolean, userId?: string,
): Promise<Result<AnalysisStart>> {
  const v = validate(repoIn);
  if (!v.ok) return v;
  const repo = v.data;
  if (mode === "ai") {
    if (!userId) return err(401, "unauthorized", "Sign in to get an AI report.");
    const c = user(userId).me.credits;
    if (!c.ai_available) return err(503, "ai_unavailable", "AI reports aren't switched on yet. The free quick report has the full verdict and evidence.");
    if (c.balance <= 0) return err(402, "quota_exceeded", "You've used your free AI reports. You can claim another one in your settings once a week. The quick report is always free.");
  }
  const s = state();
  const cached = s.cache.get(key(repo, mode, days));
  if (repo === OUTDATED) return err(502, "upstream", "GitHub didn't answer in time. Try again in a minute.");
  if (cached && !refresh && !cached.outdated) {
    remember(userId, cached);
    return { ok: true, data: { status: "done", report: cached } };
  }
  const id = `job_${crypto.randomUUID().slice(0, 12)}`;
  s.jobs.set(id, { id, repo, mode, days, userId, started: Date.now() });
  if (mode === "ai" && userId) {
    const c = user(userId).me.credits;
    c.balance--;
    c.free--;
  }
  return { ok: true, data: { status: "queued", job_id: id } };
}

function progressOf(job: Job) {
  const p = Math.min(1, (Date.now() - job.started) / JOB_MS);
  let stage = STAGES[0][1];
  for (const [at, name] of STAGES) if (p >= at) stage = name;
  return { p, stage };
}

function finish(job: Job): Report {
  const s = state();
  const k = key(job.repo, job.mode, job.days);
  let r = s.cache.get(k);
  if (!r) {
    r = { ...mockReport(job.repo, job.mode, job.days), generated_at: new Date().toISOString() };
    s.cache.set(k, r);
    remember(job.userId, r);
  }
  return r;
}

export async function jobStatus(id: string): Promise<Result<JobStatus>> {
  const job = state().jobs.get(id);
  if (!job) return err(404, "not_found", "That analysis has expired. Start it again.");
  const { p, stage } = progressOf(job);
  if (p >= 1) return { ok: true, data: { status: "done", stage: "Done", progress: 1, report: finish(job), error: null } };
  return { ok: true, data: { status: p < 0.05 ? "queued" : "running", stage, progress: p, report: null, error: null } };
}

function sse(event: string, data: unknown) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

export function jobEvents(kind: "analyses" | "find" | "playbook-jobs" | "preflight-jobs" | "merge-plan-jobs", id: string, signal: AbortSignal): Response {
  if (kind === "find") return findEvents(id, signal);
  if (kind === "merge-plan-jobs") return mergePlanEvents(id, signal);
  if (kind === "playbook-jobs") return playbookEvents(id, signal);
  if (kind === "preflight-jobs") return preflightEvents(id, signal);
  const job = state().jobs.get(id);
  const enc = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      if (!job) {
        controller.enqueue(enc.encode(sse("error", { error: { code: "not_found", message: "That analysis has expired. Start it again." } })));
        controller.close();
        return;
      }
      let last = "";
      const tick = () => {
        if (signal.aborted) return;
        const { p, stage } = progressOf(job);
        if (p >= 1) {
          controller.enqueue(enc.encode(sse("stage", { stage: "Writing the report", progress: 1 })));
          controller.enqueue(enc.encode(sse("done", { report: finish(job) })));
          controller.close();
          return;
        }
        if (stage !== last || Math.random() < 0.5) {
          controller.enqueue(enc.encode(sse("stage", { stage, progress: Math.round(p * 100) / 100 })));
          last = stage;
        }
        setTimeout(tick, 350);
      };
      tick();
    },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
}

export async function listReports(limit: number): Promise<Result<{ reports: { repo: string; mode: Mode; generated_at: string; verdict: string }[] }>> {
  const rows = [...state().cache.values()]
    .filter((r) => r.mode === "rules" && r.days === 7)
    .map((r) => ({ repo: r.repo, mode: r.mode, generated_at: r.generated_at, verdict: r.verdict }))
    .sort((a, b) => b.generated_at.localeCompare(a.generated_at));
  return { ok: true, data: { reports: rows.slice(0, limit) } };
}

const counts = (a: ReturnType<typeof mockAbout>) => ({
  open_issues: a?.open_issues ?? null, pull_requests: a?.pull_requests ?? null,
  open_pull_requests: a?.open_pull_requests ?? null, contributors: a?.contributors ?? null,
});

/** Discover over the cached reports. The mock has no GitHub details, so language and stars are empty; the counts are the made-up "About". */
export async function discover(sort: DiscoverSort, language: string | null, topic: string | null, limit: number, hacktoberfest = false, cursor: string | null = null): Promise<Result<DiscoverOut>> {
  const tagged = new Set(mockFindPool().filter(({ seed }) => seed.hacktoberfest).map(({ seed }) => seed.repo));
  const cards: DiscoverRepo[] = [...state().cache.values()]
    .filter((r) => r.mode === "rules" && r.days === 7)
    .filter((r) => !hacktoberfest || tagged.has(r.repo))
    .map((r) => ({
      ...counts(mockAbout(r.repo)),
      repo: r.repo, verdict: r.verdict, headline: r.headline, tone: r.tone, reason: r.verdict_line, standout: null, stats: r.stats,
      description: null, language: null, languages: [], stars: null, topics: [], pushed_at: null, checked_this_week: null, generated_at: r.generated_at,
      issues: mockIssues(r.repo).slice(0, 5),
    }));
  const chosen = language || topic || sort === "trending" ? [] : sort === "welcoming" ? cards.filter((c) => c.verdict === "viable") : cards;
  // The mock's cursor is the offset; the server's also names the last repo sent (API.md).
  const start = Number(cursor) || 0;
  const end = start + limit;
  return { ok: true, data: { sort, language, topic, hacktoberfest, repos: chosen.slice(start, end), languages: [], trending_min: 5, total: chosen.length, next: end < chosen.length ? String(end) : null } };
}

export async function getReport(repoIn: string, mode: Mode, days: number): Promise<Result<Report>> {
  const v = validate(repoIn);
  if (!v.ok) return v;
  if (REPORT_MS) await new Promise((r) => setTimeout(r, REPORT_MS));
  const r = state().cache.get(key(v.data, mode, days)) ?? (mode === "rules" ? anotherBudget(v.data, days) : undefined);
  // Like the real server, `about` is read fresh when a report is served, never stored with it: a report cached earlier shows the current fields.
  return r ? { ok: true, data: { ...r, about: mockAbout(r.repo) } } : err(404, "not_found", "No report yet for this repository.");
}

/** Like the server: a rules report's verdict is the same for every budget, so
 * another budget is served from the one already made (the mock's fixtures
 * reply fast, so there's no slow-reply note to redo). */
function anotherBudget(repo: string, days: number): Report | undefined {
  for (const d of [7, 14, 30]) {
    const r = state().cache.get(key(repo, "rules", d));
    if (r?.budget_independent) return { ...r, days };
  }
  return undefined;
}

export async function starterIssues(repoIn: string, limit: number): Promise<Result<{ repo: string; issues: StarterIssue[] }>> {
  const v = validate(repoIn);
  if (!v.ok) return v;
  return { ok: true, data: { repo: v.data, issues: mockIssues(v.data).slice(0, limit) } };
}

/** API.md, "Repo search": the repos the mock knows whose name has `name` in it, exact matches first. */
export async function searchRepos(name: string): Promise<Result<RepoSearch>> {
  const q = name.trim().toLowerCase();
  if (!/^[a-z0-9._-]+(?: [a-z0-9._-]+)*$/.test(q)) return err(400, "invalid_request", "That doesn't look like a repository name.");
  const known = [...new Set([...PRECACHED, "excalidraw/excalidraw"])];
  const hits = known.filter((r) => r.split("/")[1].toLowerCase().includes(q));
  hits.sort((a, b) => Number(b.split("/")[1].toLowerCase() === q) - Number(a.split("/")[1].toLowerCase() === q));
  return { ok: true, data: { query: q, results: hits.slice(0, 5).map((repo) => ({ repo, description: null, stars: 0 })) } };
}

const FIND_MS = Math.round(JOB_MS / 2);

/** API.md: a new search answers 202 with the index part (here, the first two results); the job's `done` carries them all. */
export async function find(q: FindQuery): Promise<Result<FindStart>> {
  const id = `find_${crypto.randomUUID().slice(0, 12)}`;
  state().findJobs.set(id, { id, q, started: Date.now() });
  return { ok: true, data: { status: "queued", job_id: id, results: findResults(q).slice(0, 2) } };
}

/** API.md, POST /v1/find/index: the mock's whole pool stands in for the index. */
export async function findIndex(q: Omit<FindQuery, "limit">, cursor: string | null, limit: number): Promise<Result<FindIndexPart>> {
  const all = findResults({ ...q, limit: Number.MAX_SAFE_INTEGER });
  const start = Number(cursor) || 0;
  const end = start + limit;
  return { ok: true, data: { results: all.slice(start, end), total: all.length, next: end < all.length ? String(end) : null } };
}

export async function findStatus(id: string): Promise<Result<FindJobStatus>> {
  const job = state().findJobs.get(id);
  if (!job) return err(404, "not_found", "That search has expired. Start it again.");
  const p = Math.min(1, (Date.now() - job.started) / FIND_MS);
  return p >= 1
    ? { ok: true, data: { status: "done", stage: "Done", progress: 1, results: findResults(job.q), error: null } }
    : { ok: true, data: { status: "running", stage: p < 0.5 ? "Fetching pull requests" : "Checking evidence", progress: p, results: null, error: null } };
}

function findEvents(id: string, signal: AbortSignal): Response {
  const enc = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const tick = async () => {
        if (signal.aborted) return;
        const r = await findStatus(id);
        if (!r.ok) {
          controller.enqueue(enc.encode(sse("error", { error: r.error })));
          controller.close();
          return;
        }
        if (r.data.status === "done") {
          controller.enqueue(enc.encode(sse("done", { results: r.data.results })));
          controller.close();
          return;
        }
        controller.enqueue(enc.encode(sse("stage", { stage: r.data.stage, progress: Math.round(r.data.progress * 100) / 100 })));
        setTimeout(tick, 350);
      };
      tick();
    },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
}

function findResults(q: FindQuery): FindResult[] {
  const langs = q.languages.map((l) => l.toLowerCase());
  return mockFindPool()
    .filter(({ seed }) => !langs.length || langs.includes(seed.language.toLowerCase()))
    .filter(({ seed }) => !q.hacktoberfest || seed.hacktoberfest)
    .filter(({ issues }) => issues.length > 0)
    .sort((a, b) => b.seed.stats.first_time_merged_authors - a.seed.stats.first_time_merged_authors)
    .slice(0, q.limit)
    .map(({ seed, issues }) => ({
      repo: seed.repo,
      ...verdictView(seed.verdict),
      verdict: seed.verdict,
      description: seed.description,
      language: seed.language,
      languages: [seed.language],
      stars: seed.stars,
      ...counts(mockAbout(seed.repo)),
      stats: {
        outsider_attempts: seed.stats.outsider_attempts,
        outsider_merged: seed.stats.outsider_merged,
        first_time_merged_authors: seed.stats.first_time_merged_authors,
        median_first_response_hours: seed.stats.median_first_response_hours,
      },
      issues: q.days <= 1 ? issues.filter((i) => i.labels.some((l) => /doc|typo|good first/i.test(l))).slice(0, 2) : issues,
    }))
    .filter((r) => r.issues.length > 0);
}

/** Accepts an answer for any cached report version, like the server. */
export async function sendFeedback(input: FeedbackInput): Promise<Result<FeedbackOut>> {
  const r = state().cache.get(key(input.repo, input.mode, input.days));
  if (!r || r.generated_at !== input.generated_at) return err(404, "not_found", "We couldn't find that report any more. Reload the page and try again.");
  return { ok: true, data: { repo: r.repo, generated_at: r.generated_at, verdict: r.verdict, vote: input.vote, reason: input.reason } };
}

export async function me(userId: string): Promise<Result<Me>> {
  return { ok: true, data: user(userId).me };
}

export async function entitlements(userId: string): Promise<Result<Entitlements>> {
  const { plan, plan_expires_at } = user(userId).me;
  return { ok: true, data: { plan, plan_expires_at, features: [mergePlanAccess(userId)] } };
}

// Payments stay off in the mock: no passes, no orders.
export async function passes(): Promise<Result<Passes>> {
  return { ok: true, data: { on_sale: false, passes: [], features: [] } };
}

export async function createOrder(): Promise<Result<never>> {
  return err(403, "payments_off", "Passes aren't on sale yet. Everything free in Holt keeps working.");
}

export async function history(userId: string): Promise<Result<History>> {
  const items = user(userId).history;
  const cards = await cachedCards();
  const checked = new Set(items.map((i) => i.repo.toLowerCase()));
  return { ok: true, data: { items, cards: [...cards.values()].filter((c) => checked.has(c.repo.toLowerCase())) } };
}

// Mirrors server/holt_server/badge.py: a positive, factual line for a passing
// repo, neutral grey for anything else, never a red verdict.
function shortHours(h: number): string {
  if (h < 1) return `~${Math.max(1, Math.round(h * 60))}m`;
  if (h < 24) return `~${Math.round(h)}h`;
  return `~${Math.round(h / 24)}d`;
}

export function badgeMessage(report: Pick<Report, "verdict" | "stats"> | undefined): [string, string] {
  if (!report) return ["not checked yet", "#57606a"];
  if (report.verdict !== "viable") return ["see report", "#57606a"];
  const parts: string[] = [];
  if (report.stats.outsider_merged > 0) parts.push("merges outsiders");
  const h = report.stats.median_first_response_hours;
  if (h != null && h >= 0 && h <= 72) parts.push(`replies in ${shortHours(h)}`);
  return [parts.join(" · ") || "worth your time", "#1a7f37"];
}

export function badge(repoIn: string): Response {
  const v = validate(repoIn);
  const report = v.ok ? state().cache.get(key(v.data, "rules", 7)) : undefined;
  const [text, color] = badgeMessage(report);
  return new Response(badgeSvg("holt", text, color), {
    headers: { "Content-Type": "image/svg+xml; charset=utf-8", "Cache-Control": "public, max-age=3600" },
  });
}

/** Shields-style badge. Opaque fills so it reads on light and dark READMEs. */
export function badgeSvg(label: string, message: string, color: string): string {
  const w = (s: string) => Math.round(s.length * 6.6 + 12);
  const lw = 36 + Math.round(label.length * 6.6) + 6;
  const mw = w(message);
  const total = lw + mw;
  const esc = (s: string) => s.replace(/[<>&"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" })[c]!);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${total}" height="20" role="img" aria-label="${esc(label)}: ${esc(message)}">
<title>${esc(label)}: ${esc(message)}</title>
<clipPath id="r"><rect width="${total}" height="20" rx="3"/></clipPath>
<g clip-path="url(#r)"><rect width="${lw}" height="20" fill="#1b1d1c"/><rect x="${lw}" width="${mw}" height="20" fill="${color}"/></g>
<g fill="#83a9ff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11"><text x="5" y="13.5" font-size="8.5">=^.^=</text></g>
<g fill="#fff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11"><text x="36" y="14">${esc(label)}</text><text x="${lw + 6}" y="14">${esc(message)}</text></g>
</svg>`;
}

// Connect GitHub. The mock names the account after its id; the real server asks GitHub.
const g2 = globalThis as unknown as { holtMockGitHub?: Map<string, GitHubConnection> };
const connections = () => (g2.holtMockGitHub ??= new Map());
const NOT_CONNECTED: GitHubConnection = { connected: false, account: null };

export async function githubConnection(userId: string): Promise<Result<GitHubConnection>> {
  return { ok: true, data: connections().get(userId) ?? NOT_CONNECTED };
}

export async function connectGitHub(userId: string, githubId: string, statsOptOut: boolean): Promise<Result<GitHubConnection>> {
  const at = new Date().toISOString();
  const prev = connections().get(userId)?.account;
  const data: GitHubConnection = {
    connected: true,
    account: { id: Number(githubId), login: `github-user-${githubId}`, connected_at: prev?.connected_at ?? at, adult_confirmed_at: at, stats_opt_out: statsOptOut },
  };
  connections().set(userId, data);
  return { ok: true, data };
}

export async function setStatsOptOut(userId: string, statsOptOut: boolean): Promise<Result<GitHubConnection>> {
  const c = connections().get(userId);
  if (!c?.account) return err(404, "not_found", "Your GitHub account isn't connected.");
  const data = { connected: true, account: { ...c.account, stats_opt_out: statsOptOut } };
  connections().set(userId, data);
  return { ok: true, data };
}

export async function disconnectGitHub(userId: string): Promise<Result<GitHubConnection>> {
  connections().delete(userId);
  refreshed().delete(userId);
  return { ok: true, data: NOT_CONNECTED };
}

// My Contributions: a fixed handful of pull requests for any connected user.
const g3 = globalThis as unknown as { holtMockRefreshed?: Map<string, number> };
const refreshed = () => (g3.holtMockRefreshed ??= new Map());

function mockContributions(userId: string, login: string): Contributions {
  const day = 86_400_000;
  const at = (daysAgo: number) => new Date(Date.now() - daysAgo * day).toISOString();
  const fetched = refreshed().get(userId) ?? Date.now() - 20 * 60_000;
  const next = fetched + 15 * 60_000;
  const verdict = (v: "viable" | "not_viable" | "insufficient_evidence") => ({
    verdict: v,
    headline: { viable: "Worth your time", not_viable: "Not worth your time", insufficient_evidence: "Not enough evidence" }[v],
    tone: ({ viable: "good", not_viable: "bad", insufficient_evidence: "neutral" } as const)[v],
    checked_at: at(1),
    first_reply_hours: { viable: 15, not_viable: 60, insufficient_evidence: null }[v],
    timing: v === "viable" ? { first_reply_half_hours: 10, first_reply_slow_hours: 30, merge_half_days: 6, merge_slow_days: 30, stale_bot: false } as Timing : null,
  });
  const pr = (repo: string, number: number, title: string, state: "open" | "merged" | "closed", daysAgo: number,
    v: ReturnType<typeof verdict> | null, found = false) => ({
    repo, number, title, url: `https://github.com/${repo}/pull/${number}`, state, draft: false,
    created_at: at(daysAgo), closed_at: state === "open" ? null : at(daysAgo - 2), merged_at: state === "merged" ? at(daysAgo - 2) : null,
    verdict: v, found_via_holt: found, counted: true, not_counted_because: null as "you" | "own_project" | null,
    turn: (state === "open" ? "theirs" : "unknown") as "yours" | "theirs" | "unknown", turn_at: null as string | null,
    first_reply_at: null as string | null, last_activity_at: state === "open" ? at(daysAgo) : null,
    review_decision: null as "approved" | "changes_requested" | "review_required" | null,
    reply_by: null as string | null, reply_kind: null as "changes" | "approved" | "reply" | null,
    watch: null as "on" | "muted" | null, unread_alert: false,
  });
  const prs = [
    pr("home-assistant/core", 153340, "Add a battery sensor to the Roborock integration", "open", 2, verdict("viable"), true),
    { ...pr("pallets/click", 2811, "Fix shell completion for nested groups", "open", 6, verdict("viable")),
      turn: "yours" as const, turn_at: at(1), first_reply_at: at(4), last_activity_at: at(1), review_decision: "changes_requested" as const,
      reply_by: "davidism", reply_kind: "changes" as const },
    pr("NixOS/nixpkgs", 339210, "python3Packages.rich: 13.7.1 -> 13.9.4", "merged", 12, verdict("viable"), true),
    pr("octo/one", 88, "Fix a typo in the contributing guide", "merged", 40, null),
    pr("octo/two", 14, "Add a --quiet flag", "closed", 95, verdict("not_viable")),
  ];
  // The person's choices win; nothing is a personal or team project in the mock.
  const chosen = choices().get(userId) ?? new Map<string, boolean>();
  for (const p of prs) {
    const c = chosen.get(p.repo.toLowerCase());
    if (c === false) Object.assign(p, { counted: false, not_counted_because: "you" });
  }
  // PR watch (mock/alerts.ts): the open ones that count are watched once alerts are on.
  for (const p of prs) Object.assign(p, watch.watchFields(userId, p));
  const counted = prs.filter((p) => p.counted);
  const n = (s: string) => counted.filter((p) => p.state === s).length;
  const decided = n("merged") + n("closed");
  return {
    login, fetched_at: new Date(fetched).toISOString(), next_refresh_at: next > Date.now() ? new Date(next).toISOString() : null,
    window_days: 365, truncated: false,
    summary: {
      opened: counted.length, merged: n("merged"), waiting: n("open"), closed: n("closed"),
      landed_share: decided ? Math.round((n("merged") / decided) * 10_000) / 10_000 : null,
      found_via_holt: counted.filter((p) => p.found_via_holt).length, not_counted: prs.length - counted.length,
    },
    pull_requests: prs,
  };
}

const g6 = globalThis as unknown as { holtMockChoices?: Map<string, Map<string, boolean>> };
const choices = () => (g6.holtMockChoices ??= new Map());

export async function setContributionCounted(userId: string, repo: string, counted: boolean | null): Promise<Result<Contributions>> {
  const r = await contributions(userId);
  if (!r.ok) return r;
  const key = repo.toLowerCase();
  if (!r.data.pull_requests.some((p) => p.repo.toLowerCase() === key)) return err(404, "not_found", "None of your pull requests are to that repository.");
  const mine = choices().get(userId) ?? new Map<string, boolean>();
  if (counted === null) mine.delete(key);
  else mine.set(key, counted);
  choices().set(userId, mine);
  return contributions(userId);
}

/** Turning alerts on needs GitHub connected, as on the real server. */
export async function saveAlertSettings(userId: string, body: AlertSettingsBody): Promise<Result<AlertSettings>> {
  return watch.saveAlertSettings(userId, body, Boolean(connections().get(userId)?.account));
}

export async function contributions(userId: string): Promise<Result<Contributions>> {
  const acct = connections().get(userId)?.account;
  if (!acct) return err(404, "not_found", "Connect your GitHub account to see your contributions.");
  return { ok: true, data: mockContributions(userId, acct.login) };
}

export async function refreshContributions(userId: string): Promise<Result<Contributions>> {
  const acct = connections().get(userId)?.account;
  if (!acct) return err(404, "not_found", "Connect your GitHub account to see your contributions.");
  const last = refreshed().get(userId);
  if (!last || last + 15 * 60_000 <= Date.now()) refreshed().set(userId, Date.now());
  return { ok: true, data: mockContributions(userId, acct.login) };
}

// Recommendations: a fixed ranked list. With no profile and no connection
// (a new account) the reasons that speak of the user are left out, as the
// server's popular-language picks do. The real ranking is server rules
// (server/holt_server/recommendations.py).
function mockPicks(): Recommendation[] {
  const at = (hoursAgo: number) => new Date(Date.now() - hoursAgo * 3_600_000).toISOString();
  const stats = (attempts: number, merged: number, noReply: number, reply: number, firstTimers: number): Stats => ({
    outsider_attempts: attempts, outsider_merged: merged, distinct_outsiders: Math.round(attempts * 0.8),
    first_time_merged_authors: firstTimers, no_reply: noReply, median_first_response_hours: reply, bot_share: 0.05, still_open: 3, closed_silently: 1, closed_by_bot: 0, withdrawn: 0, too_old: 0, timing: null,
  });
  const issue = (repo: string, number: number, title: string, labels: string[], areas: ContributionType[], daysAgo: number): StarterIssue => ({
    number, title, url: `https://github.com/${repo}/issues/${number}`, labels, created_at: at(daysAgo * 24), comments: 1,
    why: ["Labelled good first issue"], beginner: labels.some((l) => /good first/i.test(l)), areas,
    people: 0, open_prs: 0, on_it: "Nobody on it yet",
  });
  const pick = (repo: string, language: string, description: string, stars: number, topics: string[], s: Stats, why: string[], issues: StarterIssue[]): Recommendation => {
    const r = withDerived({ ...mockReport(repo, "rules", 7), stats: s });
    return { repo, ...counts(mockAbout(repo)), ...verdictView("viable"), verdict: "viable", odds: r.odds, reason: r.verdict_line, standout: null, numbers_line: r.numbers_line, why, stats: s, description, language, languages: [language], stars, topics, issues, checked_at: at(5) };
  };
  // Enough further picks for /me/picks to load in parts.
  const MORE: [repo: string, language: string, description: string, stars: number][] = [
    ["encode/httpx", "Python", "A next generation HTTP client for Python.", 13_800],
    ["pytest-dev/pytest", "Python", "The pytest framework makes it easy to write small tests, yet scales to support complex functional testing.", 12_600],
    ["python-poetry/poetry", "Python", "Python packaging and dependency management made easy.", 32_500],
    ["pydantic/pydantic", "Python", "Data validation using Python type hints.", 22_400],
    ["psf/black", "Python", "The uncompromising Python code formatter.", 39_800],
    ["tiangolo/sqlmodel", "Python", "SQL databases in Python, designed for simplicity, compatibility, and robustness.", 15_200],
    ["Textualize/textual", "Python", "The lean application framework for Python.", 27_100],
    ["pallets/flask", "Python", "The Python micro framework for building web applications.", 68_900],
    ["pallets/jinja", "Python", "A very fast and expressive template engine.", 10_600],
    ["python-attrs/attrs", "Python", "Python classes without boilerplate.", 5_400],
    ["mkdocs/mkdocs", "Python", "Project documentation with Markdown.", 19_800],
    ["nedbat/coveragepy", "Python", "The code coverage tool for Python.", 3_100],
    ["BurntSushi/ripgrep", "Rust", "ripgrep recursively searches directories for a regex pattern while respecting your gitignore.", 49_300],
    ["sharkdp/bat", "Rust", "A cat(1) clone with wings.", 50_700],
    ["sharkdp/fd", "Rust", "A simple, fast and user-friendly alternative to find.", 34_900],
    ["clap-rs/clap", "Rust", "A full featured, fast Command Line Argument Parser for Rust.", 14_500],
    ["tokio-rs/axum", "Rust", "Ergonomic and modular web framework built with Tokio, Tower, and Hyper.", 19_600],
    ["starship/starship", "Rust", "The minimal, blazing-fast, and infinitely customizable prompt for any shell.", 45_800],
    ["nushell/nushell", "Rust", "A new type of shell.", 33_100],
    ["helix-editor/helix", "Rust", "A post-modern modal text editor.", 34_400],
    ["casey/just", "Rust", "Just a command runner.", 22_300],
    ["ajeetdsouza/zoxide", "Rust", "A smarter cd command. Supports all major shells.", 23_700],
    ["python-pillow/Pillow", "Python", "Python Imaging Library (Fork).", 12_400],
    ["urllib3/urllib3", "Python", "urllib3 is a user-friendly HTTP client library for Python.", 3_800],
    ["jazzband/pip-tools", "Python", "A set of tools to keep your pinned Python dependencies fresh.", 7_800],
    ["marshmallow-code/marshmallow", "Python", "A lightweight library for converting complex objects to and from simple Python datatypes.", 7_100],
  ];
  const more = MORE.map(([repo, language, description, stars], i) =>
    pick(repo, language, description, stars, [], stats(30 + i, 12 + (i % 7), 4, 8 + 3 * i, 3 + (i % 5)), [
      language === "Rust" ? "Written in Rust, where you've had pull requests merged before." : "Written in Python, one of your languages.",
      `Maintainers usually reply within ${8 + 3 * i < 24 ? `${8 + 3 * i} hours` : `${Math.round((8 + 3 * i) / 24)} days`}.`,
    ], []));
  return [
    pick("pallets/click", "Python", "Python composable command line interface toolkit", 16_200, ["cli", "python"], stats(42, 19, 3, 6, 9), [
      "Written in Python, one of your languages, and you've had pull requests merged in it.",
      "About cli, a topic you picked.",
      "Maintainers usually reply within 6 hours.",
      "9 people had their first pull request merged here recently.",
      "Has an open docs issue, the kind of work you want to do.",
    ], [
      issue("pallets/click", 2811, "Document how to test a command that reads from stdin", ["good first issue", "docs"], ["docs"], 4),
      issue("pallets/click", 2794, "Help text wraps badly for long option names", ["good first issue"], ["code"], 9),
    ]),
    pick("Textualize/rich", "Python", "Rich is a Python library for rich text and beautiful formatting in the terminal.", 51_000, ["terminal", "python"], stats(60, 21, 9, 14, 11), [
      "Written in Python, one of your languages.",
      "Maintainers usually reply within 14 hours.",
      "11 people had their first pull request merged here recently.",
      "Has 3 open issues labelled for first-timers.",
    ], [
      issue("Textualize/rich", 3512, "Add an example for Table.grid to the docs", ["good first issue", "documentation"], ["docs"], 2),
      issue("Textualize/rich", 3490, "Progress bar ignores `refresh_per_second` when paused", ["good first issue", "bug"], ["code"], 12),
      issue("Textualize/rich", 3471, "Test coverage for Markdown tables with alignment", ["good first issue", "tests"], ["tests"], 20),
    ]),
    pick("fastapi/typer", "Python", "Typer, build great CLIs. Easy to code. Based on Python type hints.", 17_000, ["cli"], stats(35, 10, 6, 30, 5), [
      "Written in Python, one of your languages.", "About cli, a topic you picked.", "Maintainers usually reply within 30 hours.",
    ], []),
    pick("astral-sh/ruff", "Rust", "An extremely fast Python linter and code formatter, written in Rust.", 38_000, ["linter"], stats(120, 70, 8, 3, 22), [
      "Written in Rust, where you've had pull requests merged before.", "Maintainers usually reply within 3 hours.",
    ], []),
    pick("httpie/cli", "Python", "Modern, user-friendly command-line HTTP client for the API era.", 34_000, ["cli", "http"], stats(28, 7, 5, 40, 4), [
      "Written in Python, one of your languages.", "About cli and http, topics you picked.", "Maintainers usually reply within 2 days.",
    ], []),
    ...more,
  ];
}

export async function recommendations(userId: string, limit: number, offset = 0): Promise<Result<Recommendations>> {
  const prefs = profiles().get(userId) ?? null;
  const connected = connections().has(userId);
  const picks = prefs || connected ? mockPicks() : mockPicks().map((p) => ({ ...p, why: p.why.filter((w) => !/\byou/i.test(w)) }));
  return {
    ok: true,
    data: {
      picks: picks.slice(offset, offset + limit),
      total: picks.length,
      next: offset + limit < picks.length ? offset + limit : null,
      basis: {
        languages: prefs?.languages ?? [], topics: prefs?.topics ?? [], level: prefs?.level ?? "newcomer", contributions: prefs?.contributions ?? [],
        history_languages: connected ? ["Python", "Rust"] : [], already_contributing: connected ? 4 : 0, has_profile: prefs !== null, connected,
      },
      computed_at: new Date().toISOString(),
    },
  };
}

// Profile: kept in memory per user, like the connections above.
const g4 = globalThis as unknown as { holtMockProfiles?: Map<string, ProfilePrefs> };
const profiles = () => (g4.holtMockProfiles ??= new Map());

export async function getProfile(userId: string): Promise<Result<ProfileOut>> {
  return { ok: true, data: { profile: profiles().get(userId) ?? null, adult_confirmed: profiles().has(userId) || connections().has(userId) } };
}

export async function saveProfile(userId: string, body: Omit<ProfilePrefs, "updated_at"> & { adult_confirmed: boolean }): Promise<Result<ProfileOut>> {
  const { adult_confirmed, ...prefs } = body;
  const known = profiles().has(userId) || connections().has(userId);
  if (!adult_confirmed && !known) return { ok: false, status: 400, error: { code: "invalid_request", message: "Please confirm you're 18 or older to save a profile." } };
  profiles().set(userId, { ...prefs, updated_at: new Date().toISOString() });
  return getProfile(userId);
}

export async function deleteProfile(userId: string): Promise<Result<ProfileOut>> {
  profiles().delete(userId);
  return getProfile(userId);
}

// Saved repos: in memory per user, newest first; cards from the cached reports.
const g5 = globalThis as unknown as { holtMockSaved?: Map<string, Map<string, { repo: string; saved_at: string }>> };
const savedOf = (userId: string) => {
  const all = (g5.holtMockSaved ??= new Map());
  if (!all.has(userId)) all.set(userId, new Map());
  return all.get(userId)!;
};

const cachedCards = async () =>
  new Map(((await discover("stars", null, null, 1000)) as { ok: true; data: DiscoverOut }).data.repos.map((c) => [c.repo.toLowerCase(), c]));

export async function savedRepos(userId: string): Promise<Result<SavedList>> {
  const cards = await cachedCards();
  const rows = [...savedOf(userId).values()].sort((a, b) => b.saved_at.localeCompare(a.saved_at));
  return { ok: true, data: { saved: rows.map((r) => ({ ...r, card: cards.get(r.repo.toLowerCase()) ?? null })), max_saved: 500 } };
}

export async function savedState(userId: string, repo: string): Promise<Result<SavedState>> {
  const row = savedOf(userId).get(repo.toLowerCase());
  return { ok: true, data: row ? { ...row, saved: true } : { repo, saved: false, saved_at: null } };
}

export async function setSaved(userId: string, repo: string, saved: boolean): Promise<Result<SavedState>> {
  const mine = savedOf(userId);
  const key = repo.toLowerCase();
  if (!saved) mine.delete(key);
  else if (!mine.has(key)) mine.set(key, { repo: canonicalName(repo), saved_at: new Date().toISOString() });
  return savedState(userId, repo);
}
