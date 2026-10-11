// The only way web/ talks to server/ (see API.md). Server code only: the
// internal key must never reach the browser.
import "server-only";
import { cache } from "react";
import type {
  AlertCount, AlertList, AlertSettings, AlertSettingsBody, AnalysisStart, ApiError, Checkout, Contributions, DiscoverOut, DiscoverSort, Entitlements, FeedbackOut, FindIndexPart, FindQuery, FindResult, FindStart, GitHubConnection,
  History, JobStatus, Me, MergePlanStart, MergePlanState, Mode, Order, OrderConfirmed, Passes, PlaybookStart, PlaybookState, PreflightStart, PreflightState,
  ProfileOut, ProfilePrefs, RazorpaySuccess, Recommendations, RepoSearch, Report, Result, SavedList, SavedState, StarterIssue, Unsubscribed,
} from "./types";
import { BOARD_PART } from "./discover";
import type { FeedbackInput } from "./feedback";
import { isJobId } from "./ids";
import * as mock from "./mock/server";
import { isValidRepo } from "./repo";
import { ttlMemo } from "./ttl-memo";
import { retryDropped } from "./upstream-retry";

export const MOCK = process.env.MOCK_API === "1";
const BASE = (process.env.HOLT_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export interface Caller {
  userId?: string | null;
  ip?: string | null;
}

function headers(caller?: Caller): HeadersInit {
  const h: Record<string, string> = {
    "X-Holt-Internal-Key": process.env.HOLT_INTERNAL_KEY || "",
    Accept: "application/json",
  };
  if (caller?.userId) h["X-Holt-User"] = caller.userId;
  if (caller?.ip) h["X-Holt-Client-Ip"] = caller.ip;
  return h;
}

const UNREACHABLE: ApiError = {
  code: "upstream",
  message: "Holt's analysis server isn't answering right now. Try again in a minute.",
};

async function call<T>(path: string, init: RequestInit & { caller?: Caller } = {}): Promise<Result<T>> {
  const { caller, ...rest } = init;
  let res: Response;
  try {
    const signal = rest.signal ?? AbortSignal.timeout(20_000);
    res = await retryDropped(() => fetch(`${BASE}${path}`, {
      ...rest,
      cache: "no-store",
      headers: { ...headers(caller), ...(rest.body ? { "Content-Type": "application/json" } : {}) },
      signal,
    }));
  } catch {
    return { ok: false, status: 502, error: UNREACHABLE };
  }
  if (res.status === 204) return { ok: true, data: undefined as T };
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // fall through
  }
  if (!res.ok) {
    const e = (body as { error?: ApiError } | null)?.error;
    return {
      ok: false,
      status: res.status,
      error: e?.code ? e : { code: res.status === 404 ? "not_found" : "internal", message: "Something went wrong on our side. Try again soon." },
    };
  }
  return { ok: true, data: body as T };
}

const enc = encodeURIComponent;
const repoPath = (repo: string) => repo.split("/").map(enc).join("/");

// Path parameters are validated here too, so nothing unexpected is ever
// interpolated into an upstream URL, whatever the caller checked.
const BAD_JOB = { ok: false as const, status: 400, error: { code: "invalid_request" as const, message: "That isn't a valid job id." } };
const BAD_REPO = { ok: false as const, status: 400, error: { code: "invalid_repo" as const, message: "That doesn't look like a GitHub repository." } };
function repoOk(repo: string) {
  const [o, r, ...rest] = repo.split("/");
  return rest.length === 0 && Boolean(o && r) && isValidRepo(o, r);
}

/**
 * Tell the server about a sign-in: the address the provider gave, and whether
 * this sign-in created the account (the welcome email goes out once, then).
 * Never throws, and gives up after 4 seconds: a slow server never holds up a sign-in.
 */
export async function reportSignIn(userId: string, email: string | null, first: boolean): Promise<void> {
  if (MOCK) return;
  await call<void>("/v1/me/sign-in", { method: "POST", body: JSON.stringify({ email, first }), caller: { userId }, signal: AbortSignal.timeout(4_000) });
}

/** Every Holt email on made-up data, for /lab/emails. 404 from a production server. */
export function labEmails(): Promise<Result<import("./api-schema").LabEmails>> {
  if (MOCK) return Promise.resolve({ ok: false, status: 404, error: { code: "not_found", message: "The mock API has no emails." } });
  return call("/v1/lab/emails");
}

/** The model is server configuration; the web never picks one. */
export function startAnalysis(repo: string, mode: Mode, days: number, refresh: boolean, caller: Caller): Promise<Result<AnalysisStart>> {
  if (MOCK) return mock.startAnalysis(repo, mode, days, refresh, caller.userId ?? undefined);
  return call("/v1/analyses", { method: "POST", body: JSON.stringify({ repo, mode, days, refresh }), caller });
}

export async function jobStatus(jobId: string): Promise<Result<JobStatus>> {
  if (!isJobId(jobId)) return BAD_JOB;
  if (MOCK) return mock.jobStatus(jobId);
  return call(`/v1/analyses/${enc(jobId)}`);
}

export type JobKind = "analyses" | "find" | "playbook-jobs" | "preflight-jobs" | "merge-plan-jobs";

/** Raw upstream SSE response for a job (analyses, find, a playbook or a PR pre-flight check). */
export async function jobEvents(kind: JobKind, jobId: string, signal: AbortSignal): Promise<Response> {
  if (!isJobId(jobId)) {
    return new Response(`event: error\ndata: ${JSON.stringify({ error: BAD_JOB.error })}\n\n`, { status: 400, headers: { "Content-Type": "text/event-stream" } });
  }
  if (MOCK) return mock.jobEvents(kind, jobId, signal);
  try {
    return await retryDropped(() => fetch(`${BASE}/v1/${kind}/${enc(jobId)}/events`, {
      headers: { ...headers(), Accept: "text/event-stream" },
      cache: "no-store",
      signal,
    }));
  } catch {
    const body = `event: error\ndata: ${JSON.stringify({ error: UNREACHABLE })}\n\n`;
    return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
  }
}

// Once per request: a report page's metadata and body ask for the same report.
const cachedReport = cache(async (repo: string, mode: Mode, days: number): Promise<Result<Report>> => {
  if (!repoOk(repo)) return BAD_REPO;
  if (MOCK) return mock.getReport(repo, mode, days);
  return call(`/v1/reports/${repoPath(repo)}?mode=${mode}&days=${days}`);
});

export function getReport(repo: string, mode: Mode = "rules", days = 7): Promise<Result<Report>> {
  return cachedReport(repo, mode, days); // defaults filled in, so both calls share one key
}

/**
 * Latest rules report per repo, newest first, for the sitemap:
 * GET /v1/reports?limit=500 -> {"reports": [{repo, mode, generated_at, verdict}]}.
 * Never throws; any failure (404/501 before the server ships it) is [].
 */
export async function listReports(limit = 500): Promise<{ repo: string; generated_at: string }[]> {
  const n = Math.min(500, Math.max(1, Math.floor(limit)));
  const r = MOCK ? await mock.listReports(n) : await call<unknown>(`/v1/reports?limit=${n}`);
  const rows = r.ok ? (r.data as { reports?: unknown } | null)?.reports : null;
  if (!Array.isArray(rows)) return [];
  return (rows as { repo?: unknown; generated_at?: unknown }[])
    .filter((x): x is { repo: string; generated_at: string } => typeof x?.repo === "string" && repoOk(x.repo) && typeof x.generated_at === "string")
    .slice(0, n);
}

export async function starterIssues(repo: string, limit: number, caller: Caller): Promise<Result<{ repo: string; issues: StarterIssue[] }>> {
  if (!repoOk(repo)) return BAD_REPO;
  if (MOCK) return mock.starterIssues(repo, limit);
  return call(`/v1/repos/${repoPath(repo)}/starter-issues?limit=${limit}`, { caller });
}

/** Public repositories whose name matches `name`, most starred first (API.md, "Repo search"): which repo a bare "excalidraw" means. */
export async function searchRepos(name: string, caller: Caller): Promise<Result<RepoSearch>> {
  if (MOCK) return mock.searchRepos(name);
  return call(`/v1/repos/search?q=${encodeURIComponent(name)}`, { caller });
}

export async function find(q: FindQuery, caller: Caller): Promise<Result<FindStart>> {
  if (MOCK) return mock.find(q);
  const r = await call<{ status?: string; job_id?: string; results?: FindResult[]; complete?: boolean }>("/v1/find", {
    method: "POST",
    body: JSON.stringify(q),
    caller,
  });
  if (!r.ok) return r;
  // 202 {status: "queued", job_id, results}: the search runs, `results` is Holt's index meanwhile.
  if (r.data.job_id) return { ok: true, data: { status: "queued", job_id: r.data.job_id, results: r.data.results ?? [] } };
  return { ok: true, data: { status: "done", results: r.data.results ?? [], complete: r.data.complete ?? true } };
}

/** Checked repos, filtered and ranked from rules verdicts (API.md, GET /v1/discover), one part at a time: `cursor` is the last part's `next`. Reads only the database. */
export const discover = cache(async (sort: DiscoverSort, language: string | null, topic: string | null, limit = BOARD_PART, hacktoberfest = false, cursor: string | null = null): Promise<Result<DiscoverOut>> => {
  if (MOCK) return mock.discover(sort, language, topic, limit, hacktoberfest, cursor);
  const q = new URLSearchParams({ sort, limit: String(limit) });
  if (language) q.set("language", language);
  if (topic) q.set("topic", topic);
  if (hacktoberfest) q.set("hacktoberfest", "true");
  if (cursor) q.set("cursor", cursor);
  return call(`/v1/discover?${q}`);
});

/** The rest of a find's index matches, one part at a time (API.md, POST /v1/find/index). Never searches GitHub and counts against no limit. */
export async function findIndex(q: Omit<FindQuery, "limit">, cursor: string | null, limit = BOARD_PART): Promise<Result<FindIndexPart>> {
  if (MOCK) return mock.findIndex(q, cursor, limit);
  return call("/v1/find/index", { method: "POST", body: JSON.stringify({ ...q, limit, cursor }) });
}

/** "How to get merged here" (API.md, Playbook): the teaser for anyone, the whole playbook once unlocked. */
export async function playbookState(repo: string, caller: Caller): Promise<Result<PlaybookState>> {
  if (!repoOk(repo)) return BAD_REPO;
  if (MOCK) return mock.playbookState(repo, caller.userId ?? undefined);
  return call(`/v1/playbook/${repoPath(repo)}`, { caller });
}

/** Unlock a repository's playbook: the server checks and charges the user, then serves or queues it. */
export async function unlockPlaybook(repo: string, userId: string): Promise<Result<PlaybookStart>> {
  if (!repoOk(repo)) return BAD_REPO;
  if (MOCK) return mock.unlockPlaybook(repo, userId);
  return call(`/v1/me/playbook/${repoPath(repo)}`, { method: "POST", caller: { userId } });
}

/** The merge plan (API.md, Merge plan): whether one can be made here, and this user's latest for `repo`. */
export async function mergePlanState(repo: string, caller: Caller): Promise<Result<MergePlanState>> {
  if (!repoOk(repo)) return BAD_REPO;
  if (MOCK) return mock.mergePlanState(repo, caller.userId ?? undefined);
  return call(`/v1/merge-plan/${repoPath(repo)}`, { caller });
}

/**
 * Whether merge plans can be made on this server (MergePlanState's `available`,
 * the same for every repo and visitor: one anonymous, database-only read).
 * Asked on most pages, so this process keeps the answer for a minute and
 * shares one read between renders; the read gives up after 2 seconds, so a
 * slow server never holds a page. A failed read keeps the last answer (at
 * first: no) and is tried again 5 seconds later.
 */
export const mergePlansAvailable = ttlMemo<boolean>(
  async () => {
    if (MOCK) {
      const r = await mock.mergePlanState(AVAILABILITY_REPO);
      return r.ok ? r.data.available : null;
    }
    const r = await call<MergePlanState>(`/v1/merge-plan/${repoPath(AVAILABILITY_REPO)}`, { signal: AbortSignal.timeout(2_000) });
    return r.ok ? r.data.available : null;
  },
  // The mock's switch (MOCK_PRO) is read each time, so a dev server follows it.
  { ttlMs: MOCK ? 0 : 60_000, retryMs: MOCK ? 0 : 5_000, fallback: false },
);
const AVAILABILITY_REPO = "processing/p5.js";

/** Make a merge plan: the server checks and charges the user, then queues it. */
export async function startMergePlan(repo: string, userId: string): Promise<Result<MergePlanStart>> {
  if (!repoOk(repo)) return BAD_REPO;
  if (MOCK) return mock.startMergePlan(repo, userId);
  return call(`/v1/me/merge-plan/${repoPath(repo)}`, { method: "POST", caller: { userId } });
}

/** What to pre-flight: a pull request link, or a repository and a branch (API.md, PR pre-flight). */
export interface PreflightQuery {
  pr?: string | null;
  repo?: string | null;
  branch?: string | null;
  base?: string | null;
}

/** PR pre-flight (API.md): whether it's on, what it costs this user, and their latest check of `q`. */
export async function preflightState(q: PreflightQuery, caller: Caller): Promise<Result<PreflightState>> {
  if (MOCK) return mock.preflightState(q, caller.userId ?? undefined);
  const params = new URLSearchParams();
  for (const k of ["pr", "repo", "branch", "base"] as const) {
    const v = q[k]?.trim();
    if (v) params.set(k, v.slice(0, 500));
  }
  const qs = params.toString();
  return call(`/v1/preflight${qs ? `?${qs}` : ""}`, { caller });
}

/** Start a pre-flight check. The server checks and charges the user; the browser decides nothing about the price. */
export async function startPreflight(body: { pr_url?: string; repo?: string; branch?: string; base?: string; summary: boolean }, caller: Caller): Promise<Result<PreflightStart>> {
  if (MOCK) return mock.startPreflight(body, caller.userId ?? "");
  return call("/v1/me/preflight", { method: "POST", body: JSON.stringify(body), caller });
}

/** "Was this verdict right?" (API.md, Feedback). One answer per person per report version. */
export async function sendFeedback(input: FeedbackInput, caller: Caller): Promise<Result<FeedbackOut>> {
  if (!repoOk(input.repo)) return BAD_REPO;
  if (MOCK) return mock.sendFeedback(input);
  return call("/v1/feedback", { method: "POST", body: JSON.stringify(input), caller });
}

export function me(userId: string): Promise<Result<Me>> {
  if (MOCK) return mock.me(userId);
  return call("/v1/me", { caller: { userId } });
}

/** What the user's plan covers now (API.md, Account): one `Access` per paid feature. */
export function entitlements(userId: string): Promise<Result<Entitlements>> {
  if (MOCK) return mock.entitlements(userId);
  return call("/v1/me/entitlements", { caller: { userId } });
}

export function history(userId: string, limit = 50): Promise<Result<History>> {
  if (MOCK) return mock.history(userId);
  return call(`/v1/me/history?limit=${limit}`, { caller: { userId } });
}

// Connect GitHub (API.md, "Connect GitHub"). `githubId` always comes from the
// user's own GitHub sign-in record (lib/github-account.ts), never from a form.
export function githubConnection(userId: string): Promise<Result<GitHubConnection>> {
  if (MOCK) return mock.githubConnection(userId);
  return call("/v1/me/github", { caller: { userId } });
}

export function connectGitHub(userId: string, githubId: string, statsOptOut: boolean): Promise<Result<GitHubConnection>> {
  if (MOCK) return mock.connectGitHub(userId, githubId, statsOptOut);
  return call("/v1/me/github", {
    method: "POST",
    body: JSON.stringify({ github_id: Number(githubId), adult_confirmed: true, stats_opt_out: statsOptOut }),
    caller: { userId },
  });
}

/**
 * Merge the account `fromUser` into `userId` (API.md, "Merging accounts").
 * Only lib/github-account.ts calls it, with the owner of a GitHub sign-in the
 * person just proved is theirs. The mock API has one account per sign-in.
 */
export function mergeAccount(userId: string, fromUser: string, githubId: string): Promise<Result<void>> {
  if (MOCK) return Promise.resolve({ ok: true, data: undefined });
  return call("/v1/me/merge", { method: "POST", body: JSON.stringify({ from_user: fromUser, github_id: Number(githubId) }), caller: { userId } });
}

export function setStatsOptOut(userId: string, statsOptOut: boolean): Promise<Result<GitHubConnection>> {
  if (MOCK) return mock.setStatsOptOut(userId, statsOptOut);
  return call("/v1/me/github", { method: "PATCH", body: JSON.stringify({ stats_opt_out: statsOptOut }), caller: { userId } });
}

export function disconnectGitHub(userId: string): Promise<Result<GitHubConnection>> {
  if (MOCK) return mock.disconnectGitHub(userId);
  return call("/v1/me/github", { method: "DELETE", caller: { userId } });
}

// Profile (API.md, "Profile"). `adult_confirmed` is only sent when the user
// ticked the 18+ box on this save.
export function getProfile(userId: string): Promise<Result<ProfileOut>> {
  if (MOCK) return mock.getProfile(userId);
  return call("/v1/me/profile", { caller: { userId } });
}

export function saveProfile(userId: string, body: Omit<ProfilePrefs, "updated_at"> & { adult_confirmed: boolean }): Promise<Result<ProfileOut>> {
  if (MOCK) return mock.saveProfile(userId, body);
  return call("/v1/me/profile", { method: "PUT", body: JSON.stringify(body), caller: { userId } });
}

export function deleteProfile(userId: string): Promise<Result<ProfileOut>> {
  if (MOCK) return mock.deleteProfile(userId);
  return call("/v1/me/profile", { method: "DELETE", caller: { userId } });
}

// My Contributions (API.md). The first read, and a refresh past its 15-minute
// cooldown, make the server search GitHub, so they get more time.
export function contributions(userId: string): Promise<Result<Contributions>> {
  if (MOCK) return mock.contributions(userId);
  return call("/v1/me/contributions", { caller: { userId }, signal: AbortSignal.timeout(60_000) });
}

export function refreshContributions(userId: string): Promise<Result<Contributions>> {
  if (MOCK) return mock.refreshContributions(userId);
  return call("/v1/me/contributions/refresh", { method: "POST", caller: { userId }, signal: AbortSignal.timeout(60_000) });
}

/** Count a repo's pull requests in the numbers (true), leave them out (false), or go back to Holt's default (null). */
export function setContributionCounted(userId: string, repo: string, counted: boolean | null): Promise<Result<Contributions>> {
  if (MOCK) return mock.setContributionCounted(userId, repo, counted);
  const path = `/v1/me/contributions/repos/${repo.split("/").map(encodeURIComponent).join("/")}`;
  return counted === null
    ? call(path, { method: "DELETE", caller: { userId } })
    : call(path, { method: "PUT", body: JSON.stringify({ counted }), caller: { userId } });
}

// PR watch (API.md, "PR watch (alerts)"): the bell, the alert settings, muting
// one pull request, and the email's unsubscribe link.

/** The bell's list, with who gets alerts (`access`) and the unread count. Once per request: the shell and the page both ask. */
export const alertList = cache((userId: string): Promise<Result<AlertList>> => {
  if (MOCK) return mock.alertList(userId);
  return call("/v1/me/alerts?limit=20", { caller: { userId } });
});

export function alertCount(userId: string): Promise<Result<AlertCount>> {
  if (MOCK) return mock.alertCount(userId);
  return call("/v1/me/alerts/count", { caller: { userId } });
}

/** Mark some alerts read, or all of them. */
export function readAlerts(userId: string, which: { ids: number[] } | { all: true }): Promise<Result<void>> {
  if (MOCK) return mock.readAlerts(userId, which);
  return call("/v1/me/alerts/read", { method: "POST", body: JSON.stringify(which), caller: { userId } });
}

export function alertSettings(userId: string): Promise<Result<AlertSettings>> {
  if (MOCK) return mock.alertSettings(userId);
  return call("/v1/me/alerts/settings", { caller: { userId } });
}

/** Only the fields sent change. `email` is the account's own address, never one a person typed (lib/alerts.ts, settingsBody). */
export function saveAlertSettings(userId: string, body: AlertSettingsBody): Promise<Result<AlertSettings>> {
  if (MOCK) return mock.saveAlertSettings(userId, body);
  return call("/v1/me/alerts/settings", { method: "PUT", body: JSON.stringify(body), caller: { userId } });
}

/** No alerts for one pull request (true), or watch it again (false). */
export async function setAlertMute(userId: string, repo: string, number: number, muted: boolean): Promise<Result<void>> {
  if (!repoOk(repo) || !Number.isInteger(number) || number < 1 || number > 2 ** 31 - 1) return BAD_REPO;
  if (MOCK) return mock.setAlertMute(userId, repo, number, muted);
  return call(`/v1/me/contributions/${repoPath(repo)}/${number}/mute`, { method: muted ? "PUT" : "DELETE", caller: { userId } });
}

/**
 * The email's unsubscribe link (off), and its undo (on). No user: the token is
 * the key. Call it only from a POST the browser or a mail client made
 * (app/api/alerts), never while rendering a page: scanners fetch every link.
 */
export function setAlertEmailByToken(token: string, on: boolean): Promise<Result<Unsubscribed>> {
  if (MOCK) return mock.setAlertEmailByToken(token, on);
  return call(`/v1/alerts/${on ? "resubscribe" : "unsubscribe"}`, { method: "POST", body: JSON.stringify({ token }) });
}

/** Recommendations for you (API.md), a part at a time: `next` in the answer is the `offset` of the part after. Ranked by rules from cached data; free for everyone. */
export function recommendations(userId: string, limit = 10, offset = 0): Promise<Result<Recommendations>> {
  const n = Math.min(30, Math.max(1, Math.floor(limit)));
  const from = Math.max(0, Math.floor(offset));
  if (MOCK) return mock.recommendations(userId, n, from);
  return call(`/v1/me/recommendations?limit=${n}&offset=${from}`, { caller: { userId } });
}

// Saved repos (API.md, "Saved repos"). Saving and unsaving are idempotent.
export function savedRepos(userId: string): Promise<Result<SavedList>> {
  if (MOCK) return mock.savedRepos(userId);
  return call("/v1/me/saved", { caller: { userId } });
}

/**
 * Which repos a list's save buttons show as saved: one request for the whole
 * page, however many cards. Null when signed out (the buttons then offer
 * sign-in). If the list can't be read, nothing shows as saved; saving again is
 * harmless.
 */
export async function savedNames(userId: string | null | undefined): Promise<string[] | null> {
  if (!userId) return null;
  const r = await savedRepos(userId);
  return r.ok ? r.data.saved.map((i) => i.repo) : [];
}

export async function savedState(userId: string, repo: string): Promise<Result<SavedState>> {
  if (!repoOk(repo)) return BAD_REPO;
  if (MOCK) return mock.savedState(userId, repo);
  return call(`/v1/me/saved/${repoPath(repo)}`, { caller: { userId } });
}

export async function setSaved(userId: string, repo: string, saved: boolean): Promise<Result<SavedState>> {
  if (!repoOk(repo)) return BAD_REPO;
  if (MOCK) return mock.setSaved(userId, repo, saved);
  return call(`/v1/me/saved/${repoPath(repo)}`, { method: saved ? "PUT" : "DELETE", caller: { userId } });
}

/** A signed-in user opened a report page. The server keeps it only while GitHub is connected. */
export async function recordView(userId: string, repo: string): Promise<void> {
  if (!repoOk(repo) || MOCK) return;
  const r = await call("/v1/me/activity", { method: "POST", body: JSON.stringify({ repo }), caller: { userId } });
  if (!r.ok) console.error("[holt] recording a report view failed:", r.error.code);
}

export async function badge(owner: string, repo: string): Promise<Response> {
  if (!isValidRepo(owner, repo)) return new Response("Not found", { status: 404 });
  if (MOCK) return mock.badge(`${owner}/${repo}`);
  try {
    const res = await retryDropped(() => fetch(`${BASE}/badge/${enc(owner)}/${enc(repo)}.svg`, { next: { revalidate: 3600 } }));
    return new Response(res.body, {
      status: res.status,
      // The server's cache policy, so a badge that turns neutral isn't held for a day.
      headers: { "Content-Type": "image/svg+xml; charset=utf-8", "Cache-Control": res.headers.get("Cache-Control") ?? "public, max-age=3600" },
    });
  } catch {
    return mock.badge("");
  }
}

// Pro passes (API.md, "Passes"). Off unless the server says `on_sale`; the
// server takes the price from its own catalogue, never from here.
export function passes(): Promise<Result<Passes>> {
  if (MOCK) return mock.passes();
  return call("/v1/passes");
}

export function createOrder(userId: string, pass: string, currency: "INR" | "USD" = "INR"): Promise<Result<Checkout>> {
  if (MOCK) return mock.createOrder();
  return call("/v1/me/orders", { method: "POST", body: JSON.stringify({ pass, currency }), caller: { userId } });
}

/**
 * Where an order stands. For a Dodo order not settled yet, the server asks
 * Dodo first: this is how the buyer's return from Dodo's checkout gives Pro.
 */
export function checkOrder(userId: string, orderId: string): Promise<Result<OrderConfirmed>> {
  if (MOCK) return mock.createOrder();
  return call(`/v1/me/orders/${encodeURIComponent(orderId)}/check`, { method: "POST", caller: { userId } });
}

export function confirmOrder(userId: string, paid: RazorpaySuccess): Promise<Result<OrderConfirmed>> {
  if (MOCK) return mock.createOrder();
  const { razorpay_order_id, razorpay_payment_id, razorpay_signature } = paid;
  return call("/v1/me/orders/confirm", {
    method: "POST",
    body: JSON.stringify({ razorpay_order_id, razorpay_payment_id, razorpay_signature }),
    caller: { userId },
  });
}

export function orders(userId: string, limit = 50): Promise<Result<{ orders: Order[] }>> {
  if (MOCK) return Promise.resolve({ ok: true, data: { orders: [] } });
  return call(`/v1/me/orders?limit=${limit}`, { caller: { userId } });
}

/**
 * Razorpay's webhook, passed to the server byte for byte: the server checks
 * the signature over the exact body. Returns the upstream status and body.
 */
export function forwardRazorpayWebhook(body: ArrayBuffer, signature: string): Promise<{ status: number; body: unknown }> {
  return forwardWebhook("/v1/payments/razorpay/webhook", body, { "X-Razorpay-Signature": signature });
}

/** The headers a Dodo webhook is signed with (Standard Webhooks). */
export const DODO_WEBHOOK_HEADERS = ["webhook-id", "webhook-timestamp", "webhook-signature"] as const;

/** Dodo's webhook, passed on the same way: the body byte for byte, its three headers as they came. */
export function forwardDodoWebhook(body: ArrayBuffer, signed: Record<(typeof DODO_WEBHOOK_HEADERS)[number], string>): Promise<{ status: number; body: unknown }> {
  return forwardWebhook("/v1/payments/dodo/webhook", body, signed);
}

async function forwardWebhook(path: string, body: ArrayBuffer, signed: Record<string, string>): Promise<{ status: number; body: unknown }> {
  if (MOCK) return { status: 404, body: { error: { code: "payments_off", message: "Payments are off." } } };
  try {
    const res = await fetch(`${BASE}${path}`, {
      method: "POST",
      body,
      headers: { ...headers(), "Content-Type": "application/json", ...signed },
      cache: "no-store",
      // Under the 30 seconds Dodo waits; the server may ask Dodo about the payment first.
      signal: AbortSignal.timeout(25_000),
    });
    return { status: res.status, body: await res.json().catch(() => null) };
  } catch {
    return { status: 502, body: { error: UNREACHABLE } };
  }
}
