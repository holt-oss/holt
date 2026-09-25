// Shared plumbing for /api/public/*: read-only proxies of cached data for the
// browser extension. They never start work and never expose the internal key.
import "server-only";
import { NextResponse } from "next/server";
import { clientIpFrom } from "./client-ip";
import { rateLimit } from "./rate-limit";
import type { Result } from "./types";

const PER_MINUTE = 60;

// API.md "Public proxy for the browser extension": the data is public, so
// CORS is open; no cookies or auth are read.
function cors(headers: Headers) {
  headers.set("Access-Control-Allow-Origin", "*");
  headers.set("Access-Control-Allow-Methods", "GET, OPTIONS");
  headers.set("Access-Control-Max-Age", "86400");
}

export function preflight() {
  const res = new NextResponse(null, { status: 204 });
  cors(res.headers);
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
    // 15 min on 200, 5 min on 404 so a new analysis shows up soon.
    res.headers.set("Cache-Control", r.ok ? "public, max-age=900" : r.status === 404 ? "public, max-age=300" : "no-store");
  }
  cors(res.headers);
  return res;
}
