// Replaced at build time by scripts/build.mjs (HOLT_HOST env var).
declare const __HOLT_HOST__: string;

export const HOLT_HOST: string =
  typeof __HOLT_HOST__ === "string" ? __HOLT_HOST__ : "holt.aahil-khan.xyz";

const seg = (s: string) => encodeURIComponent(s);

export function reportPageUrl(owner: string, repo: string, host = HOLT_HOST): string {
  return `https://${host}/${seg(owner)}/${seg(repo)}`;
}

export function publicApiUrl(
  kind: "report" | "starter-issues",
  owner: string,
  repo: string,
  host = HOLT_HOST,
): string {
  return `https://${host}/api/public/${kind}/${seg(owner)}/${seg(repo)}`;
}
