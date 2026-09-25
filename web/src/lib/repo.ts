// Parsing repository references. No imports, so it runs in the browser,
// in proxy.ts, and under `node --test`.

export interface RepoRef {
  owner: string;
  repo: string;
}

const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;
const REPO = /^[A-Za-z0-9._-]{1,100}$/;

export function isValidRepo(owner: string, repo: string): boolean {
  return OWNER.test(owner) && REPO.test(repo) && repo !== "." && repo !== "..";
}

/**
 * Turn whatever someone pasted into owner/repo:
 * "pallets/flask", "https://github.com/pallets/flask/tree/main",
 * "github.com/pallets/flask.git", "git@github.com:pallets/flask.git".
 */
export function parseRepoInput(input: string): RepoRef | null {
  let s = input.trim();
  if (!s) return null;
  s = s.replace(/^git@github\.com:/i, "github.com/");
  s = s.replace(/^(?:git\+)?(?:https?|ssh|git):\/\/(?:[^@/]+@)?/i, "");
  s = s.replace(/[?#].*$/, "");
  s = s.replace(/^(?:www\.)?github\.com\//i, "");
  const parts = s.split("/").filter(Boolean);
  if (parts.length < 2) return null;
  const owner = parts[0];
  const repo = parts[1].replace(/\.git$/i, "");
  return isValidRepo(owner, repo) ? { owner, repo } : null;
}

// GitHub sub-pages that may follow owner/repo when someone swaps the host
// on a deep link, e.g. /pallets/flask/pulls or /pallets/flask/blob/main/README.md.
const GITHUB_SUBPAGES = new Set([
  "tree", "blob", "pulls", "pull", "issues", "commits", "commit", "actions",
  "wiki", "discussions", "releases", "tags", "branches", "projects", "security",
  "pulse", "graphs", "network", "labels", "milestones", "compare", "blame",
  "raw", "contributors", "stargazers", "watchers", "forks", "activity", "settings",
]);

/** Where the URL trick should send a request path, or null to leave it alone. */
export function redirectTargetForPath(pathname: string, search = ""): string | null {
  let path = pathname;
  try {
    path = decodeURIComponent(pathname);
  } catch {
    // keep the raw path
  }
  const hostTrick = /^\/+(?:(?:https?:)?\/*)?(?:www\.)?github\.com(?:\/|$)/i;
  if (hostTrick.test(path)) {
    const ref = parseRepoInput(path.replace(/^\/+/, "").replace(/^https?:\/*/i, ""));
    return ref ? `/${ref.owner}/${ref.repo}` : "/";
  }
  const parts = path.split("/").filter(Boolean);
  if (parts.length >= 3 && GITHUB_SUBPAGES.has(parts[2].toLowerCase()) && isValidRepo(parts[0], parts[1])) {
    return `/${parts[0]}/${parts[1]}`;
  }
  if (parts.length === 2 && /\.git$/i.test(parts[1])) {
    const repo = parts[1].replace(/\.git$/i, "");
    if (isValidRepo(parts[0], repo)) return `/${parts[0]}/${repo}${search}`;
  }
  return null;
}
