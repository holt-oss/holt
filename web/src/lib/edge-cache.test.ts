import assert from "node:assert/strict";
import { test } from "node:test";
import { EDGE_CACHE, EDGE_CACHE_CDN, edgeCacheKind, type CacheQuestion } from "./edge-cache.ts";
import { PICKS_COOKIE } from "./find-picks.ts";
import { NUDGE_COOKIE } from "./home.ts";
import { MOTION_COOKIE } from "./motion.ts";
import { SKIP_COOKIE } from "./profile.ts";
import { RAIL_COOKIE } from "./shell.ts";

function ask(path: string, o: { cookies?: string[]; headers?: Record<string, string>; method?: string } = {}): ReturnType<typeof edgeCacheKind> {
  const [pathname, query] = path.split("?");
  const q: CacheQuestion = {
    method: o.method ?? "GET",
    pathname,
    search: query ? `?${query}` : "",
    cookies: o.cookies ?? [],
    header: (name) => o.headers?.[name] ?? null,
  };
  return edgeCacheKind(q);
}

const PUBLIC = ["/", "/discover", "/discover?sort=stars&topic=cli", "/discover/python", "/examples", "/example-ai-report", "/pricing", "/how-it-works", "/terms", "/privacy", "/refunds", "/contact"];
const REPORTS = ["/pallets/flask", "/NixOS/nixpkgs", "/vercel/next.js"];

test("signed out, the public pages are cacheable and reports are if they exist", () => {
  for (const p of PUBLIC) assert.equal(ask(p), "page", p);
  for (const p of REPORTS) assert.equal(ask(p), "report", p);
  assert.equal(ask("/discover/"), "page");
  assert.equal(ask("/pallets/flask", { method: "HEAD" }), "report");
});

test("signed-in responses are never cacheable", () => {
  // Auth.js's session cookie, plain (http) and on https, and split in chunks when it is long.
  for (const session of ["authjs.session-token", "__Secure-authjs.session-token", "__Secure-authjs.session-token.0", "next-auth.session-token"]) {
    for (const p of [...PUBLIC, ...REPORTS]) assert.equal(ask(p, { cookies: [session] }), null, `${p} with ${session}`);
    // Beside a cookie that alone would be fine.
    assert.equal(ask("/discover", { cookies: ["__cf_bm", session] }), null);
  }
});

test("any cookie the app reads, or doesn't know, makes the page this visitor's alone", () => {
  // A sign-in half done, the connect form's choices, display settings, last Find picks, dismissed nudges.
  const app = ["authjs.csrf-token", "__Host-authjs.csrf-token", "authjs.callback-url", "holt_connect", MOTION_COOKIE, RAIL_COOKIE, PICKS_COOKIE, SKIP_COOKIE, NUDGE_COOKIE];
  for (const name of [...app, "something_new", "_ga"]) {
    assert.equal(ask("/", { cookies: [name] }), null, name);
    assert.equal(ask("/pallets/flask", { cookies: [name] }), null, name);
  }
  // Every cookie this app sets is one a cache rule can spot by name.
  for (const name of app) assert.match(name, /authjs|holt/, name);
});

test("Cloudflare's own cookies don't count", () => {
  assert.equal(ask("/discover", { cookies: ["__cf_bm", "cf_clearance", "_cfuvid", "__cflb"] }), "page");
});

test("only reads, and none with credentials", () => {
  assert.equal(ask("/discover", { method: "POST" }), null);
  assert.equal(ask("/discover", { headers: { authorization: "Bearer x" } }), null);
});

test("pages about one person, for signed-in people, or that can carry a running job, are never cacheable", () => {
  for (const p of ["/me", "/me/repos", "/settings", "/settings/profile", "/signin", "/profile", "/alerts", "/alerts/unsubscribe", "/pricing/thanks", "/find", "/find?go=1", "/find?lang=python&days=7&hacktoberfest=0", "/hacktoberfest", "/compare", "/preflight", "/lab/emails", "/api/find", "/API/find", "/badge/flask.svg", "/api/public/report/pallets/flask"]) {
    assert.equal(ask(p), null, p);
  }
});

test("a report at anything but its plain address isn't cacheable", () => {
  assert.equal(ask("/pallets/flask?mode=ai"), null);
  assert.equal(ask("/pallets/flask?days=30"), null);
  assert.equal(ask("/pallets/flask/pulls"), null);
  assert.equal(ask("/pallets"), null);
});

test("the headers keep a minute at the edge and nothing in the browser", () => {
  assert.match(EDGE_CACHE, /^public, /);
  assert.match(EDGE_CACHE, /\bmax-age=0, must-revalidate\b/);
  assert.match(EDGE_CACHE, /\bs-maxage=60\b/);
  // A browser reads Cache-Control: it must never be told it may show an old copy.
  assert.doesNotMatch(EDGE_CACHE, /stale-while-revalidate/);
  assert.match(EDGE_CACHE_CDN, /^public, s-maxage=60, stale-while-revalidate=\d+$/);
});
