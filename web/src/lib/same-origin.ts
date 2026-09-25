/**
 * For cookie-authenticated POSTs: the browser's Origin must be this site.
 * (Session cookies are SameSite=Lax too; this is the second lock.)
 */
export function isSameOrigin(req: Request): boolean {
  const origin = req.headers.get("origin");
  if (!origin) return false;
  const host =
    (process.env.TRUST_PROXY_HEADERS === "1" && req.headers.get("x-forwarded-host")) || req.headers.get("host");
  try {
    return Boolean(host) && new URL(origin).host === host;
  } catch {
    return false;
  }
}
