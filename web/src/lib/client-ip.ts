/**
 * The visitor's IP from proxy headers (Cloudflare first), for the API
 * server's per-IP rate limits. Outside production a missing header falls
 * back to 127.0.0.1; in production we send nothing rather than put every
 * visitor in one bucket (the server then answers 400 invalid_request).
 */
export function clientIpFrom(h: Headers): string | null {
  const ip =
    h.get("cf-connecting-ip")?.trim() ||
    h.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    h.get("x-real-ip")?.trim() ||
    null;
  if (ip) return ip;
  if (process.env.NODE_ENV !== "production") return "127.0.0.1";
  console.warn("[holt] no client IP header (cf-connecting-ip / x-forwarded-for / x-real-ip) on a request");
  return null;
}
