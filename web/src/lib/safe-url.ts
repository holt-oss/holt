const BASE = "http://holt.invalid";

/**
 * Only allow same-site relative redirects. Browsers strip TAB/CR/LF inside
 * URLs and treat "\" like "/", so "/\t/evil.com" or "/\\evil.com" would
 * leave the site; reject those, then confirm by parsing.
 */
export function safeCallback(v: string | string[] | undefined | null, fallback = "/"): string {
  const s = Array.isArray(v) ? v[0] : v;
  if (typeof s !== "string" || !s.startsWith("/") || s.startsWith("//")) return fallback;
  if (/[\x00-\x1f\x7f\\]/.test(s)) return fallback;
  try {
    const u = new URL(s, BASE);
    if (u.origin !== BASE) return fallback;
    return `${u.pathname}${u.search}${u.hash}`;
  } catch {
    return fallback;
  }
}
