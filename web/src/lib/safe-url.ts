/** Only allow same-site relative redirects. */
export function safeCallback(v: string | string[] | undefined, fallback = "/"): string {
  const s = Array.isArray(v) ? v[0] : v;
  return s && s.startsWith("/") && !s.startsWith("//") && !s.startsWith("/\\") ? s : fallback;
}
