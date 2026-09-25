// Shared plumbing for /api/public/*: read-only proxies of cached data for the
// browser extension. They never start work and never expose the internal key.
import "server-only";
import { NextResponse } from "next/server";
import { clientIpFrom } from "./client-ip";
import { rateLimit } from "./rate-limit";
import type { Result } from "./types";

const PER_MINUTE = 60;

export function allowedOrigin(origin: string | null): string | null {
  if (!origin) return null;
  if (origin === "https://github.com") return origin;
  if (/^(chrome|moz)-extension:\/\/[a-z0-9-]+$/i.test(origin)) return origin;
  return null;
}

function cors(req: Request, headers: Headers) {
  const origin = allowedOrigin(req.headers.get("origin"));
  if (origin) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
    headers.set("Access-Control-Max-Age", "86400");
  }
  headers.set("Vary", "Origin");
}

export function preflight(req: Request) {
  const res = new NextResponse(null, { status: 204 });
  cors(req, res.headers);
  return res;
}

export async function publicGet<T>(req: Request, bucket: string, load: (ip: string | null) => Promise<Result<T>>) {
  const ip = clientIpFrom(req.headers);
  const limited = rateLimit(`${bucket}:${ip ?? "unknown"}`, PER_MINUTE);
  let res: NextResponse;
  if (!limited.ok) {
    res = NextResponse.json(
      { error: { code: "rate_limited", message: "Too many requests. Try again in a minute.", retry_after: limited.retryAfter } },
      { status: 429, headers: { "Retry-After": String(limited.retryAfter) } },
    );
  } else {
    const r = await load(ip);
    res = r.ok ? NextResponse.json(r.data) : NextResponse.json({ error: r.error }, { status: r.status });
    res.headers.set("Cache-Control", r.ok || r.status === 404 ? "public, max-age=3600, s-maxage=3600" : "no-store");
  }
  cors(req, res.headers);
  return res;
}
