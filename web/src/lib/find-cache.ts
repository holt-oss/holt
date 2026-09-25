// A short-lived cache for /v1/find, keyed by the query. Every page load of
// /find or /hacktoberfest would otherwise start a find upstream and spend the
// visitor's rate limit. Per key and window this starts at most one find:
// concurrent misses share one call, a queued job is shared by everyone who
// asks, and its results (seen by the SSE proxy) are served from memory.
// No imports, so it runs under `node --test`.
import type { FindQuery, FindResult, FindStart, Result } from "./types";

export function findKey(q: FindQuery): string {
  const norm = (xs: string[]) => [...new Set(xs.map((x) => x.trim().toLowerCase()).filter(Boolean))].sort();
  return JSON.stringify([norm(q.languages), norm(q.topics), q.days, q.hacktoberfest, q.limit]);
}

interface Entry {
  value: FindStart;
  expires: number;
}

export class FindCache {
  private entries = new Map<string, Entry>();
  private inflight = new Map<string, Promise<Result<FindStart>>>();
  private jobs = new Map<string, string>(); // job id -> key

  private ttlMs: number;
  private now: () => number;
  private max: number;

  constructor(ttlMs = 10 * 60_000, now: () => number = Date.now, max = 200) {
    this.ttlMs = ttlMs;
    this.now = now;
    this.max = max;
  }

  get(q: FindQuery, fetch: () => Promise<Result<FindStart>>): Promise<Result<FindStart>> {
    const key = findKey(q);
    const hit = this.entries.get(key);
    if (hit && hit.expires > this.now()) return Promise.resolve({ ok: true, data: hit.value });
    if (hit) this.entries.delete(key);
    const pending = this.inflight.get(key);
    if (pending) return pending;
    const p = fetch()
      .then((r) => {
        // Errors are not cached: the next visitor tries again.
        if (r.ok) {
          this.set(key, r.data);
          if (r.data.status === "queued") this.jobs.set(r.data.job_id, key);
        }
        return r;
      })
      .finally(() => this.inflight.delete(key));
    this.inflight.set(key, p);
    return p;
  }

  /** A queued find finished: serve its results from now on. */
  resolveJob(jobId: string, results: FindResult[]) {
    const key = this.jobs.get(jobId);
    if (!key) return;
    this.jobs.delete(jobId);
    this.set(key, { status: "done", results });
  }

  /** A queued find failed or expired: forget it so the next visitor starts afresh. */
  failJob(jobId: string) {
    const key = this.jobs.get(jobId);
    if (!key) return;
    this.jobs.delete(jobId);
    const e = this.entries.get(key);
    if (e?.value.status === "queued" && e.value.job_id === jobId) this.entries.delete(key);
  }

  private set(key: string, value: FindStart) {
    this.entries.delete(key);
    this.entries.set(key, { value, expires: this.now() + this.ttlMs });
    if (this.entries.size > this.max) {
      const now = this.now();
      for (const [k, v] of this.entries) if (v.expires <= now) this.entries.delete(k);
      while (this.entries.size > this.max) this.entries.delete(this.entries.keys().next().value!);
    }
  }
}
