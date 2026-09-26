export const SITE_HOST = process.env.NEXT_PUBLIC_SITE_HOST || "localhost:3000";
export const SITE_URL = `${/^(localhost|127\.|\[::1\])/.test(SITE_HOST) ? "http" : "https"}://${SITE_HOST}`;
export const FREE_AI_QUOTA = Number(process.env.NEXT_PUBLIC_FREE_AI_QUOTA || 3);
export const GITHUB_REPO_URL = "https://github.com/holt-oss/holt";

// Who runs Holt, for the legal pages (/terms, /privacy, /refunds, /contact).
// The values are placeholders until the deployment sets the env; the pages
// render them as-is so a missing value is visible, not silently blank.
export const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL || "CONTACT_EMAIL";
export const CONTACT_CITY = process.env.NEXT_PUBLIC_CONTACT_CITY || "CONTACT_CITY";
/** The name on card statements and processor receipts (Razorpay, Dodo Payments). */
export const PAYMENT_BRAND = "Githolt";
/** Shown as "Last updated" on every legal page. Bump it when any of them changes. */
export const LEGAL_UPDATED = "27 September 2026";
export const LEGAL_PAGES = [
  { href: "/terms", label: "terms" },
  { href: "/privacy", label: "privacy" },
  { href: "/refunds", label: "refunds" },
  { href: "/contact", label: "contact" },
] as const;

/**
 * Banner copy for `now` (UTC): a countdown in the 45 days before 1 October,
 * "is on" from 1 to 31 October, and nothing after that.
 */
export function hacktoberfest(now = new Date()): { live: boolean; text: string; short: string; year: number } | null {
  const y = now.getUTCFullYear();
  const start = Date.UTC(y, 9, 1);
  const end = Date.UTC(y, 10, 1);
  const t = now.getTime();
  const day = 86_400_000;
  if (t >= start && t < end) {
    const left = Math.ceil((end - t) / day);
    return { live: true, year: y, text: `Hacktoberfest is on. ${left} day${left === 1 ? "" : "s"} left.`, short: `${left} day${left === 1 ? "" : "s"} left` };
  }
  if (t < start && start - t <= 45 * day) {
    const n = Math.ceil((start - t) / day);
    return { live: false, year: y, text: `Hacktoberfest ${y} starts in ${n} day${n === 1 ? "" : "s"}.`, short: `starts in ${n} day${n === 1 ? "" : "s"}` };
  }
  return null;
}

/** True from 1 November (UTC) of `year`. */
export function hacktoberfestOver(year: number, now = new Date()): boolean {
  return now.getTime() >= Date.UTC(year, 10, 1);
}
