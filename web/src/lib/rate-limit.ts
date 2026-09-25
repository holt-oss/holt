// A small in-memory, per-IP fixed-window limiter for public endpoints. Per
// process only; the API server enforces the real limits behind it.
const WINDOW_MS = 60_000;

const g = globalThis as unknown as { holtRate?: Map<string, { n: number; reset: number }> };
const hits = (g.holtRate ??= new Map());

export function rateLimit(key: string, limit: number): { ok: true } | { ok: false; retryAfter: number } {
  const now = Date.now();
  const e = hits.get(key);
  if (!e || e.reset <= now) {
    hits.set(key, { n: 1, reset: now + WINDOW_MS });
    if (hits.size > 10_000) for (const [k, v] of hits) if (v.reset <= now) hits.delete(k);
    return { ok: true };
  }
  if (e.n >= limit) return { ok: false, retryAfter: Math.ceil((e.reset - now) / 1000) };
  e.n++;
  return { ok: true };
}
