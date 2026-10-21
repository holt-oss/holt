// Who sees what without signing in. Signed out, a visitor can read the
// curated example reports (examples.ts) in full and a teaser of any other
// report: the verdict, the odds and one number, with the rest behind sign-in.
// Find, Browse and the Hacktoberfest page are open: their lists come from
// what Holt has already checked, and every card leads to a report (so, signed
// out, to its teaser). Find's filters work signed out too, answered from that
// index alone (findReads): only an account's search goes on to GitHub. Opening a report with no result yet runs the free
// check (anon-check.ts: the report page only, rate-limited per IP, never for
// bots); anything else that starts a check or a search needs an account, and
// so do Compare, pre-flight, the dashboard and settings (ACCOUNT_PAGES):
// arriving signed out goes to sign-in and back.
// The browser extension's public API (/api/public/*) reads the cache and
// stays open. No runtime imports, so it runs under `node --test` and in the browser.
import { isExample } from "./examples.ts";
import type { ApiError } from "./types.ts";

export type Access = "full" | "teaser";

export function reportAccess(repo: string, signedIn: boolean): Access {
  return signedIn || isExample(repo) ? "full" : "teaser";
}

/**
 * What the report page shows. `report`: a report is cached; `missing`: none
 * yet. `anonymousCheck`: signed out, and the report page may run the free
 * check for this visitor (a person, with a ticket: anon-check.ts).
 *   full: the report · teaser: part of it, the rest after sign-in ·
 *   check: run the check here (signed out, it ends on the teaser) ·
 *   sign-in: no report, and the check waits for sign-in.
 */
export function reportShows(o: { repo: string; signedIn: boolean; found: "report" | "missing" | "error"; anonymousCheck: boolean }): "full" | "teaser" | "check" | "sign-in" | "error" {
  if (o.found === "report") return reportAccess(o.repo, o.signedIn);
  if (o.found === "error") return "error";
  return o.signedIn || o.anonymousCheck ? "check" : "sign-in";
}

/** A signed-out check the server turned down (over the per-IP limit, say): offer sign-in instead. */
export function checkNeedsSignIn(code: string): boolean {
  return code === "rate_limited" || code === "unauthorized" || code === "invalid_request";
}

/** Sign-in, then back to `path` (a path on this site, with its query). */
export function signInHref(path: string): string {
  return `/signin?callbackUrl=${encodeURIComponent(path)}`;
}

// Pages that need an account. One-segment pages match exactly (/compare/x is
// a repo whose owner is "compare"); sections match with everything under them
// (they are in lib/app-routes.ts, so never a repo).
const ACCOUNT_PAGES = new Set(["/compare", "/preflight"]);
const ACCOUNT_SECTIONS = new Set(["me", "settings"]);

/** Whether a page is only for signed-in people. */
export function needsAccount(pathname: string): boolean {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  return ACCOUNT_PAGES.has(path) || ACCOUNT_SECTIONS.has(path.split("/")[1] ?? "");
}

// Auth.js's session cookie: plain on http, __Secure- on https, in numbered chunks when long.
const SESSION_COOKIE = /^(__Secure-)?authjs\.session-token(\.\d+)?$/;

/**
 * The proxy's half of the gate: an account page asked for with no session
 * cookie is answered with a redirect to sign-in (and back), before anything
 * renders. `search` comes with its "?", or "". A cookie only lets the request
 * through to the page, which asks the server who it is (requireUser,
 * lib/session.ts): the cookie itself is never trusted.
 */
export function arrivalGate(pathname: string, search: string, cookies: string[]): string | null {
  if (!needsAccount(pathname) || cookies.some((name) => SESSION_COOKIE.test(name))) return null;
  return signInHref(`${pathname}${search}`);
}

/**
 * Where every repo box sends a repo: its report, signed in or not, the same
 * page the URL opens. Signed out that is the teaser, or the free check when
 * there is no result yet (reportShows); a typo gets the not-found page.
 */
export function pasteHref(repo: string): string {
  return `/${repo}`;
}

/** What a paste box says when the input can't be a repo. */
export const NOT_A_REPO = "That doesn't look like a repo. Try owner/name or a github.com link.";

type Refusal = { status: 401; error: ApiError };

const refuse = (message: string): Refusal => ({ status: 401, error: { code: "unauthorized", message } });

/** POST /api/analyses: null when this caller may start a check. `anonymous`: the report page allowed a signed-out one. */
export function startGate(userId: string | null | undefined, anonymous = false): Refusal | null {
  return userId || anonymous ? null : refuse("Sign in to check this repo.");
}

/** A route that reads for an account page (pre-flight, a paid job's progress): null when signed in. */
export function signedInGate(userId: string | null | undefined): Refusal | null {
  return userId ? null : refuse("Sign in first.");
}

/**
 * POST /api/find, what answers this caller's filters. `search`: Holt's index,
 * then a GitHub search. `index`: the index alone, which calls GitHub for nothing.
 */
export function findReads(userId: string | null | undefined): "search" | "index" {
  return userId ? "search" : "index";
}
