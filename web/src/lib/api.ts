// The only way web/ talks to server/ (see API.md). Server code only: the
// internal key must never reach the browser.
import "server-only";
import type {
  AnalysisStart, ApiError, ByokProvider, FindQuery, FindResult, FindStart, HistoryItem, JobStatus, Me, Mode,
  Report, Result, StarterIssue,
} from "./types";
import { isJobId } from "./ids";
import * as mock from "./mock/server";
import { isValidRepo } from "./repo";

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
    res = await fetch(`${BASE}${path}`, {
      ...rest,
      cache: "no-store",
      headers: { ...headers(caller), ...(rest.body ? { "Content-Type": "application/json" } : {}) },
      signal: rest.signal ?? AbortSignal.timeout(20_000),
    });
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

export function startAnalysis(repo: string, mode: Mode, days: number, refresh: boolean, caller: Caller): Promise<Result<AnalysisStart>> {
  if (MOCK) return mock.startAnalysis(repo, mode, days, refresh, caller.userId ?? undefined);
  return call("/v1/analyses", { method: "POST", body: JSON.stringify({ repo, mode, days, refresh }), caller });
}

export async function jobStatus(jobId: string): Promise<Result<JobStatus>> {
  if (!isJobId(jobId)) return BAD_JOB;
  if (MOCK) return mock.jobStatus(jobId);
  return call(`/v1/analyses/${enc(jobId)}`);
}

/** Raw upstream SSE response for a job (analyses or find). */
export async function jobEvents(kind: "analyses" | "find", jobId: string, signal: AbortSignal): Promise<Response> {
  if (!isJobId(jobId)) {
    return new Response(`event: error\ndata: ${JSON.stringify({ error: BAD_JOB.error })}\n\n`, { status: 400, headers: { "Content-Type": "text/event-stream" } });
  }
  if (MOCK) return mock.jobEvents(kind, jobId, signal);
  try {
    return await fetch(`${BASE}/v1/${kind}/${enc(jobId)}/events`, {
      headers: { ...headers(), Accept: "text/event-stream" },
      cache: "no-store",
      signal,
    });
  } catch {
    const body = `event: error\ndata: ${JSON.stringify({ error: UNREACHABLE })}\n\n`;
    return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
  }
}

export async function getReport(repo: string, mode: Mode = "rules", days = 7): Promise<Result<Report>> {
  if (!repoOk(repo)) return BAD_REPO;
  if (MOCK) return mock.getReport(repo, mode, days);
  return call(`/v1/reports/${repoPath(repo)}?mode=${mode}&days=${days}`);
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

export function me(userId: string): Promise<Result<Me>> {
  if (MOCK) return mock.me(userId);
  return call("/v1/me", { caller: { userId } });
}

export function putByok(userId: string, provider: ByokProvider, apiKey: string, model: string): Promise<Result<Me>> {
  if (MOCK) return mock.putByok(userId, provider, apiKey, model);
  return call("/v1/me/byok", { method: "PUT", body: JSON.stringify({ provider, api_key: apiKey, model }), caller: { userId } });
}

export function deleteByok(userId: string): Promise<Result<Me>> {
  if (MOCK) return mock.deleteByok(userId);
  return call("/v1/me/byok", { method: "DELETE", caller: { userId } });
}

export function history(userId: string, limit = 50): Promise<Result<{ items: HistoryItem[] }>> {
  if (MOCK) return mock.history(userId);
  return call(`/v1/me/history?limit=${limit}`, { caller: { userId } });
}

export async function badge(owner: string, repo: string): Promise<Response> {
  if (!isValidRepo(owner, repo)) return new Response("Not found", { status: 404 });
  if (MOCK) return mock.badge(`${owner}/${repo}`);
  try {
    const res = await fetch(`${BASE}/badge/${enc(owner)}/${enc(repo)}.svg`, { next: { revalidate: 3600 } });
    return new Response(res.body, {
      status: res.status,
      headers: { "Content-Type": "image/svg+xml; charset=utf-8", "Cache-Control": "public, max-age=86400" },
    });
  } catch {
    return mock.badge("");
  }
}
