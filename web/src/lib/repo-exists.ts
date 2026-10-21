// Is there a public repository at github.com/{owner}/{repo}? The proxy asks
// before the report page starts streaming, because once it streams the status
// is 200 whatever happens (a slow report streams in behind its loading screen). Without this check a
// typo got a 200 "Worth your time?" page, a soft 404.
//
// Only a plain 404 from GitHub counts as missing. Timeouts, rate limits and
// other errors count as "exists": the report page then runs as before and
// shows its own error, so a GitHub hiccup never hides a real repository.
//
// A renamed repository (zeit/next.js) answers with a redirect to its new
// name, which the proxy follows, so the report is the one for vercel/next.js.

import { isValidRepo } from "./repo.ts";

export type ProbeResult = "exists" | "missing" | "unknown" | { renamed: string };
export type Probe = (repo: string) => Promise<ProbeResult>;

export interface RepoFound {
  exists: boolean;
  /** GitHub's current owner/name, when it differs from what was asked. */
  renamed?: string;
}

const HOUR = 3_600_000;

export function repoExistsChecker({
  probe,
  now = Date.now,
  existsMs = 6 * HOUR,
  missingMs = 10 * 60_000,
  unknownMs = 60_000,
  maxEntries = 5000,
}: {
  probe: Probe;
  now?: () => number;
  existsMs?: number;
  missingMs?: number;
  unknownMs?: number;
  maxEntries?: number;
}): (repo: string) => Promise<RepoFound> {
  const cache = new Map<string, { found: RepoFound; until: number }>();
  const inflight = new Map<string, Promise<RepoFound>>();

  return async (repo) => {
    const key = repo.toLowerCase();
    const hit = cache.get(key);
    if (hit && hit.until > now()) return hit.found;
    const running = inflight.get(key);
    if (running) return running;

    const p = probe(repo)
      .catch((): ProbeResult => "unknown")
      .then((r) => {
        const renamed = typeof r === "object" && r.renamed.toLowerCase() !== key ? r.renamed : undefined;
        const found: RepoFound = r === "missing" ? { exists: false } : renamed ? { exists: true, renamed } : { exists: true };
        const ttl = r === "missing" ? missingMs : r === "unknown" ? unknownMs : existsMs;
        cache.delete(key);
        cache.set(key, { found, until: now() + ttl });
        // Map keeps insertion order: drop the oldest entries first.
        while (cache.size > maxEntries) cache.delete(cache.keys().next().value!);
        return found;
      })
      .finally(() => inflight.delete(key));
    inflight.set(key, p);
    return p;
  };
}

/** Where a redirect from github.com/{repo} points, as owner/name, if it's another repository page. */
export function renamedTo(location: string | null): string | null {
  if (!location) return null;
  let url: URL;
  try {
    url = new URL(location, "https://github.com");
  } catch {
    return null;
  }
  if (url.hostname !== "github.com") return null;
  const [owner = "", repo = "", ...rest] = url.pathname.replace(/^\/|\/$/g, "").split("/");
  return rest.length === 0 && isValidRepo(owner, repo) ? `${owner}/${repo}` : null;
}

/** HEAD github.com/{repo}: 404 is missing (or private), 2xx exists, a redirect to another repo is a rename. */
export async function probeGitHub(repo: string, timeoutMs = 1500): Promise<ProbeResult> {
  try {
    const res = await fetch(`https://github.com/${repo}`, {
      method: "HEAD",
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (res.status === 404) return "missing";
    if (res.status >= 300 && res.status < 400) {
      const renamed = renamedTo(res.headers.get("location"));
      if (renamed) return { renamed };
    }
    return res.status < 400 ? "exists" : "unknown";
  } catch {
    return "unknown";
  }
}
