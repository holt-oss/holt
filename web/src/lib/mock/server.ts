// An in-memory stand-in for server/ (MOCK_API=1). It follows API.md: cached
// reports return at once, anything else becomes a job with stages over SSE.
import "server-only";
import type {
  AnalysisStart, ApiError, Credits, DiscoverOut, DiscoverRepo, DiscoverSort, FeedbackOut, FindJobStatus, FindQuery, FindResult, FindStart, Contributions, GitHubConnection, HistoryItem,
  ContributionType, JobStatus, Me, Mode, Packs, Plans, ProfileOut, ProfilePrefs, Recommendation, Recommendations, Report, Result, Stats, StarterIssue,
} from "../types";
import type { FeedbackInput } from "../feedback";
import { verdictView, withDerived } from "./derived";
import { canonicalName, isMockNotFound, mockFindPool, mockIssues, mockReport, PRECACHED } from "./fixtures";
import { playbookEvents } from "./playbook";
import { preflightEvents } from "./preflight";

export { playbookState, unlockPlaybook } from "./playbook";
export { preflightState, startPreflight } from "./preflight";

const JOB_MS = Number(process.env.MOCK_JOB_MS || 6500);
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

export function jobEvents(kind: "analyses" | "find" | "playbook-jobs" | "preflight-jobs", id: string, signal: AbortSignal): Response {
  if (kind === "find") return findEvents(id, signal);
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

/** Discover over the cached reports. The mock has no GitHub details, so language and stars are empty. */
export async function discover(sort: DiscoverSort, language: string | null, topic: string | null, limit: number): Promise<Result<DiscoverOut>> {
  const cards: DiscoverRepo[] = [...state().cache.values()]
    .filter((r) => r.mode === "rules" && r.days === 7)
    .map((r) => ({
      repo: r.repo, verdict: r.verdict, headline: r.headline, tone: r.tone, reason: r.verdict_line, stats: r.stats,
      description: null, language: null, stars: null, topics: [], pushed_at: null, checked_this_week: null, generated_at: r.generated_at,
    }));
  const chosen = language || topic || sort === "trending" ? [] : sort === "welcoming" ? cards.filter((c) => c.verdict === "viable") : cards;
  return { ok: true, data: { sort, language, topic, repos: chosen.slice(0, limit), languages: [], trending_min: 5 } };
}

export async function getReport(repoIn: string, mode: Mode, days: number): Promise<Result<Report>> {
  const v = validate(repoIn);
  if (!v.ok) return v;
  const r = state().cache.get(key(v.data, mode, days)) ?? (mode === "rules" ? anotherBudget(v.data, days) : undefined);
  return r ? { ok: true, data: r } : err(404, "not_found", "No report yet for this repository.");
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

const FIND_MS = Math.round(JOB_MS / 2);

/** API.md: find always answers 202; the job's `done` carries {results}. */
export async function find(q: FindQuery): Promise<Result<FindStart>> {
  const id = `find_${crypto.randomUUID().slice(0, 12)}`;
  state().findJobs.set(id, { id, q, started: Date.now() });
  return { ok: true, data: { status: "queued", job_id: id } };
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
      stars: seed.stars,
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

export async function claimCredit(userId: string): Promise<Result<Credits>> {
  const c = user(userId).me.credits;
  if (!c.can_claim) {
    const when = c.next_claim_at ? new Date(c.next_claim_at).toLocaleDateString("en-GB", { day: "numeric", month: "long", timeZone: "UTC" }) : "later";
    return err(409, "claim_not_ready", `Your next free AI report can be claimed on ${when}.`);
  }
  c.balance++;
  c.free++;
  c.can_claim = false;
  c.next_claim_at = new Date(Date.now() + CLAIM_EVERY_DAYS * DAY_MS).toISOString();
  return { ok: true, data: c };
}

// Payments stay off in the mock: no packs, no orders.
export async function packs(): Promise<Result<Packs>> {
  return { ok: true, data: { on_sale: false, packs: [] } };
}

// Plans stay off in the mock too: nothing on sale, no subscription.
export async function plans(): Promise<Result<Plans>> {
  return { ok: true, data: { on_sale: false, plans: [] } };
}

export async function subscribe(): Promise<Result<never>> {
  return err(403, "payments_off", "Paid plans aren't on sale yet. Everything free in Holt keeps working.");
}

export async function createOrder(): Promise<Result<never>> {
  return err(403, "payments_off", "Credit packs aren't on sale yet. Everything free in Holt keeps working.");
}

export async function history(userId: string): Promise<Result<{ items: HistoryItem[] }>> {
  return { ok: true, data: { items: user(userId).history } };
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
    tone: ({ viable: "good", not_viable: "bad", insufficient_evidence: "warn" } as const)[v],
    checked_at: at(1),
  });
  const pr = (repo: string, number: number, title: string, state: "open" | "merged" | "closed", daysAgo: number,
    v: ReturnType<typeof verdict> | null, found = false) => ({
    repo, number, title, url: `https://github.com/${repo}/pull/${number}`, state, draft: false,
    created_at: at(daysAgo), closed_at: state === "open" ? null : at(daysAgo - 2), merged_at: state === "merged" ? at(daysAgo - 2) : null,
    verdict: v, found_via_holt: found,
  });
  const prs = [
    pr("home-assistant/core", 153340, "Add a battery sensor to the Roborock integration", "open", 2, verdict("viable"), true),
    pr("NixOS/nixpkgs", 339210, "python3Packages.rich: 13.7.1 -> 13.9.4", "merged", 12, verdict("viable"), true),
    pr("octo/one", 88, "Fix a typo in the contributing guide", "merged", 40, null),
    pr("octo/two", 14, "Add a --quiet flag", "closed", 95, verdict("not_viable")),
  ];
  return {
    login, fetched_at: new Date(fetched).toISOString(), next_refresh_at: next > Date.now() ? new Date(next).toISOString() : null,
    window_days: 365, truncated: false,
    summary: { opened: 4, merged: 2, waiting: 1, closed: 1, landed_share: 0.6667, found_via_holt: 2 },
    pull_requests: prs,
  };
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

// Recommendations: a fixed ranked list once there is a profile or a connection.
// The real ranking is server rules (server/holt_server/recommendations.py).
// MOCK_PLAN=pro shows every pick; otherwise the free taste of two.
function mockPicks(): Recommendation[] {
  const at = (hoursAgo: number) => new Date(Date.now() - hoursAgo * 3_600_000).toISOString();
  const stats = (attempts: number, merged: number, noReply: number, reply: number, firstTimers: number): Stats => ({
    outsider_attempts: attempts, outsider_merged: merged, distinct_outsiders: Math.round(attempts * 0.8),
    first_time_merged_authors: firstTimers, no_reply: noReply, median_first_response_hours: reply, bot_share: 0.05, still_open: 3, closed_silently: 1,
  });
  const issue = (repo: string, number: number, title: string, labels: string[], areas: ContributionType[], daysAgo: number): StarterIssue => ({
    number, title, url: `https://github.com/${repo}/issues/${number}`, labels, created_at: at(daysAgo * 24), comments: 1,
    why: ["Labelled good first issue", "Nobody has claimed it"], beginner: labels.some((l) => /good first/i.test(l)), areas,
  });
  const pick = (repo: string, language: string, description: string, stars: number, topics: string[], s: Stats, why: string[], issues: StarterIssue[]): Recommendation => {
    const r = withDerived({ ...mockReport(repo, "rules", 7), stats: s });
    return { repo, ...verdictView("viable"), verdict: "viable", odds: r.odds, reason: r.verdict_line, numbers_line: r.numbers_line, why, stats: s, description, language, stars, topics, issues, checked_at: at(5) };
  };
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
  ];
}

export async function recommendations(userId: string, limit: number): Promise<Result<Recommendations>> {
  const prefs = profiles().get(userId) ?? null;
  const connected = connections().has(userId);
  const full = process.env.MOCK_PLAN === "pro" || user(userId).me.plan !== "free";
  const picks = prefs || connected ? mockPicks() : [];
  const shown = picks.slice(0, full ? limit : Math.min(limit, 2));
  return {
    ok: true,
    data: {
      picks: shown, locked: full ? 0 : Math.max(picks.length - 2, 0), full,
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
