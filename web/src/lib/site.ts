export const SITE_HOST = process.env.NEXT_PUBLIC_SITE_HOST || "localhost:3000";
export const SITE_URL = `${/^(localhost|127\.|\[::1\])/.test(SITE_HOST) ? "http" : "https"}://${SITE_HOST}`;
export const FREE_AI_QUOTA = Number(process.env.NEXT_PUBLIC_FREE_AI_QUOTA || 3);
export const GITHUB_REPO_URL = "https://github.com/holt-oss/holt";

/** Hacktoberfest runs through October. Returns banner copy for `now`. */
export function hacktoberfest(now = new Date()): { live: boolean; text: string } | null {
  const y = now.getUTCFullYear();
  const start = Date.UTC(y, 9, 1);
  const end = Date.UTC(y, 10, 1);
  const t = now.getTime();
  const day = 86_400_000;
  if (t >= start && t < end) {
    const left = Math.ceil((end - t) / day);
    return { live: true, text: `Hacktoberfest ${y} is on. ${left} day${left === 1 ? "" : "s"} left.` };
  }
  if (t < start && start - t <= 45 * day) {
    const n = Math.ceil((start - t) / day);
    return { live: false, text: `Hacktoberfest ${y} starts in ${n} day${n === 1 ? "" : "s"}.` };
  }
  return null;
}
