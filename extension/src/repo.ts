import type { Repo } from "./types";

// First path segments on github.com that are GitHub pages, not user or org names.
const RESERVED_OWNERS = new Set([
  "about", "account", "apps", "blog", "codespaces", "collections", "contact",
  "copilot", "customer-stories", "dashboard", "enterprise", "events", "explore",
  "features", "github-copilot", "issues", "join", "login", "logout",
  "marketplace", "new", "notifications", "organizations", "orgs", "pricing",
  "pulls", "readme", "search", "security", "sessions", "settings", "site",
  "sponsors", "stars", "team", "topics", "trending", "users", "watching",
]);

const OWNER_RE = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;
const REPO_RE = /^[A-Za-z0-9._-]{1,100}$/;

/** The repository a github.com path belongs to, or null for non-repo pages. */
export function parseRepo(pathname: string): Repo | null {
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length < 2) return null;
  const owner = safeDecode(parts[0]);
  let repo = safeDecode(parts[1]);
  if (owner === null || repo === null) return null;
  if (repo.endsWith(".git")) repo = repo.slice(0, -4);
  if (RESERVED_OWNERS.has(owner.toLowerCase())) return null;
  if (!OWNER_RE.test(owner) || !REPO_RE.test(repo)) return null;
  if (repo === "." || repo === "..") return null;
  return { owner, repo };
}

/** True on pages that list a repo's issues: /o/r/issues and /o/r/contribute. */
export function isIssueListPath(pathname: string): boolean {
  const parts = pathname.split("/").filter(Boolean);
  return parts.length === 3 && (parts[2] === "issues" || parts[2] === "contribute");
}

export function repoKey(r: Repo): string {
  return `${r.owner}/${r.repo}`.toLowerCase();
}

function safeDecode(s: string): string | null {
  try {
    return decodeURIComponent(s);
  } catch {
    return null;
  }
}
