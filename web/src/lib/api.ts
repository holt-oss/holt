// The only way web/ talks to server/ (see API.md). Server code only: the
// internal key must never reach the browser.
import "server-only";
import { cache } from "react";
import type {
  AnalysisStart, ApiError, Checkout, Contributions, Credits, DiscoverOut, DiscoverSort, FeedbackOut, FindQuery, FindResult, FindStart, GitHubConnection,
  HistoryItem, JobStatus, Me, Mode, MySubscription, Order, OrderConfirmed, Packs, Plans, PlaybookStart, PlaybookState, PreflightStart, PreflightState,
  ProfileOut, ProfilePrefs, RazorpaySubscriptionSuccess, RazorpaySuccess, Recommendations, Report, Result, StarterIssue, SubscriptionCheckout, SubscriptionConfirmed,
} from "./types";
import type { FeedbackInput } from "./feedback";
import { isJobId } from "./ids";
import * as mock from "./mock/server";
import { isValidRepo } from "./repo";
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

/** The model for AI reports is server configuration; the web never picks one. */
export function startAnalysis(repo: string, mode: Mode, days: number, refresh: boolean, caller: Caller): Promise<Result<AnalysisStart>> {
  if (MOCK) return mock.startAnalysis(repo, mode, days, refresh, caller.userId ?? undefined);
  return call("/v1/analyses", { method: "POST", body: JSON.stringify({ repo, mode, days, refresh }), caller });
}

export async function jobStatus(jobId: string): Promise<Result<JobStatus>> {
  if (!isJobId(jobId)) return BAD_JOB;
  if (MOCK) return mock.jobStatus(jobId);
  return call(`/v1/analyses/${enc(jobId)}`);
}

export type JobKind = "analyses" | "find" | "playbook-jobs" | "preflight-jobs";

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

export async function find(q: FindQuery, caller: Caller): Promise<Result<FindStart>> {
  if (MOCK) return mock.find(q);
  const r = await call<{ status?: string; job_id?: string; results?: FindResult[] }>("/v1/find", {
    method: "POST",
    body: JSON.stringify(q),
    caller,
  });
  if (!r.ok) return r;
  // The server answers 202 {status: "queued", job_id}; accept a direct {results} too.
  if (r.data.job_id) return { ok: true, data: { status: "queued", job_id: r.data.job_id } };
  return { ok: true, data: { status: "done", results: r.data.results ?? [] } };
}

/** Checked repos, filtered and ranked from rules verdicts (API.md, GET /v1/discover). Reads only the database. */
export const discover = cache(async (sort: DiscoverSort, language: string | null, topic: string | null, limit = 30): Promise<Result<DiscoverOut>> => {
  if (MOCK) return mock.discover(sort, language, topic, limit);
  const q = new URLSearchParams({ sort, limit: String(limit) });
  if (language) q.set("language", language);
  if (topic) q.set("topic", topic);
  return call(`/v1/discover?${q}`);
});

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

export function claimCredit(userId: string): Promise<Result<Credits>> {
  if (MOCK) return mock.claimCredit(userId);
  return call("/v1/me/credits/claim", { method: "POST", caller: { userId } });
}

export function history(userId: string, limit = 50): Promise<Result<{ items: HistoryItem[] }>> {
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

/** Recommendations for you (API.md). Ranked by rules from cached data; the server shows 2 picks without a plan. */
export function recommendations(userId: string, limit = 10): Promise<Result<Recommendations>> {
  if (MOCK) return mock.recommendations(userId, limit);
  return call(`/v1/me/recommendations?limit=${Math.min(10, Math.max(1, Math.floor(limit)))}`, { caller: { userId } });
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

// Credit packs (API.md, "Credit packs"). Off unless the server says
// `on_sale`; the server takes the price from its own catalogue, never from here.
export function packs(): Promise<Result<Packs>> {
  if (MOCK) return mock.packs();
  return call("/v1/packs");
}

export function createOrder(userId: string, pack: string): Promise<Result<Checkout>> {
  if (MOCK) return mock.createOrder();
  return call("/v1/me/orders", { method: "POST", body: JSON.stringify({ pack }), caller: { userId } });
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

// Monthly plans (API.md, "Plans (subscriptions)"). Off unless the server says
// `on_sale`; the price and the Razorpay plan come from its catalogue.
export function plans(): Promise<Result<Plans>> {
  if (MOCK) return mock.plans();
  return call("/v1/plans");
}

export function subscribe(userId: string, plan: string): Promise<Result<SubscriptionCheckout>> {
  if (MOCK) return mock.subscribe();
  return call("/v1/me/subscription", { method: "POST", body: JSON.stringify({ plan }), caller: { userId } });
}

export function confirmSubscription(userId: string, paid: RazorpaySubscriptionSuccess): Promise<Result<SubscriptionConfirmed>> {
  if (MOCK) return mock.subscribe();
  const { razorpay_payment_id, razorpay_subscription_id, razorpay_signature } = paid;
  return call("/v1/me/subscription/confirm", {
    method: "POST",
    body: JSON.stringify({ razorpay_payment_id, razorpay_subscription_id, razorpay_signature }),
    caller: { userId },
  });
}

export function mySubscription(userId: string): Promise<Result<MySubscription>> {
  if (MOCK) return Promise.resolve({ ok: true, data: { subscription: null, charges: [] } });
  return call("/v1/me/subscription", { caller: { userId } });
}

export function cancelSubscription(userId: string): Promise<Result<SubscriptionConfirmed>> {
  if (MOCK) return mock.subscribe();
  return call("/v1/me/subscription/cancel", { method: "POST", body: "{}", caller: { userId } });
}

/**
 * Razorpay's webhook, passed to the server byte for byte: the server checks
 * the signature over the exact body. Returns the upstream status and body.
 */
export async function forwardRazorpayWebhook(body: ArrayBuffer, signature: string): Promise<{ status: number; body: unknown }> {
  if (MOCK) return { status: 404, body: { error: { code: "payments_off", message: "Payments are off." } } };
  try {
    const res = await fetch(`${BASE}/v1/payments/razorpay/webhook`, {
      method: "POST",
      body,
      headers: { ...headers(), "Content-Type": "application/json", "X-Razorpay-Signature": signature },
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
    return { status: res.status, body: await res.json().catch(() => null) };
  } catch {
    return { status: 502, body: { error: UNREACHABLE } };
  }
}
