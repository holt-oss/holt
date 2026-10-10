import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { EXAMPLES, isExample } from "./examples.ts";
import { arrivalGate, findReads, needsAccount, pasteHref, pasteTarget, reportAccess, signedInGate, signInHref, startGate } from "./gate.ts";
import { afterSignIn } from "./home.ts";

const back = (href: string) => new URL(href, "https://holt.test").searchParams.get("callbackUrl");

test("the curated examples cover each verdict and are real repo names", () => {
  assert.ok(EXAMPLES.length >= 6 && EXAMPLES.length <= 8);
  for (const v of ["viable", "long_shot", "not_viable", "insufficient_evidence"]) {
    assert.ok(EXAMPLES.filter((e) => e.verdict === v).length >= 2, v);
  }
  assert.equal(new Set(EXAMPLES.map((e) => e.repo.toLowerCase())).size, EXAMPLES.length);
  for (const e of EXAMPLES) {
    assert.match(e.repo, /^[\w.-]+\/[\w.-]+$/);
    assert.ok(e.language && e.stars > 0, e.repo);
    // One short line.
    assert.ok(e.why.length <= 60, e.why);
  }
});

test("an example is recognised whatever the casing", () => {
  const { repo } = EXAMPLES[0];
  assert.ok(isExample(repo));
  assert.ok(isExample(repo.toUpperCase()));
  assert.ok(!isExample("someone/else"));
});

test("signed out: an example report is shown in full, any other repo as a teaser", () => {
  assert.equal(reportAccess(EXAMPLES[0].repo, false), "full");
  assert.equal(reportAccess("octo/project", false), "teaser");
});

// A card on Find or Browse links to the report page, so this is all a signed-out visitor gets from one.
test("signed out: the teaser is rendered on the server from the verdict, its reason and the counts, and the page gives the report to nothing else", () => {
  const dir = join(import.meta.dirname, "../components/report");
  for (const [file, fields] of [["partial-report.tsx", ["generated_at", "headline", "repo", "stats", "tone", "verdict_line"]], ["report-teaser.tsx", ["generated_at", "headline", "tone", "verdict_line"]]] as const) {
    const src = readFileSync(join(dir, file), "utf-8");
    // A client component's props are sent to the browser whole.
    assert.doesNotMatch(src, /^["']use client["']/m, file);
    assert.deepEqual([...new Set(src.match(/\breport\.[a-z_]+/g))].map((f) => f.slice(7)).sort(), fields, file);
  }
  const page = readFileSync(join(import.meta.dirname, "../app/[owner]/[repo]/page.tsx"), "utf-8");
  const teaser = page.indexOf(") : teaser ? (");
  assert.ok(teaser >= 0 && teaser < page.indexOf("<AnalysisRunner") && teaser < page.indexOf("<ReportView"), "the teaser is decided before the full report or a check");
});

test("signed in: every report is shown in full, as before", () => {
  assert.equal(reportAccess("octo/project", true), "full");
  assert.equal(reportAccess(EXAMPLES[0].repo, true), "full");
});

test("sign-in links come back to the page they left", () => {
  const href = signInHref("/octo/project?days=14");
  assert.ok(href.startsWith("/signin?callbackUrl="));
  assert.equal(back(href), "/octo/project?days=14");
});

test("signed out: pasting a repo goes to sign-in, then straight to its report", () => {
  assert.equal(back(pasteHref("octo/project", false)), "/octo/project");
});

test("after sign-in, /signin sends people on to the report or search they asked for", () => {
  assert.equal(afterSignIn(back(pasteHref("octo/project", false))), "/octo/project");
  assert.equal(afterSignIn(back(signInHref("/find?lang=rust&days=7"))), "/find?lang=rust&days=7");
});

test("signed out: pasting an example opens it directly", () => {
  assert.equal(pasteHref(EXAMPLES[0].repo, false), `/${EXAMPLES[0].repo}`);
});

test("signed in: pasting a repo opens its report, as before", () => {
  assert.equal(pasteHref("octo/project", true), "/octo/project");
});

test("signed out: starting a check is refused with a sign-in error, and Find reads the index alone", () => {
  const refused = startGate(null);
  assert.ok(refused);
  assert.equal(refused.status, 401);
  assert.equal(refused.error.code, "unauthorized");
  assert.match(refused.error.message, /sign in/i);
  for (const nobody of [null, undefined, ""]) assert.equal(findReads(nobody), "index");
});

test("signed in: starting a check or a search goes through", () => {
  assert.equal(startGate("user-1"), null);
  assert.equal(findReads("user-1"), "search");
});

test("the extension's public API stays open: it never reads the session or the gate", () => {
  for (const kind of ["report", "starter-issues"]) {
    const src = readFileSync(join(import.meta.dirname, `../app/api/public/${kind}/[owner]/[repo]/route.ts`), "utf-8");
    assert.doesNotMatch(src, /@\/lib\/(session|gate)|@\/auth\b/);
  }
});

test("a paste box asks whether the repo exists before a sign-in wall, and only then", async () => {
  const asked: string[] = [];
  const says = (answer: boolean) => async (r: string) => (asked.push(r), answer);
  // Signed out, a real repo: sign in first.
  assert.equal(await pasteTarget("octo/real", false, says(true)), "/signin?callbackUrl=%2Focto%2Freal");
  // Signed out, a typo: the report URL, which answers 404 (the not-found page).
  assert.equal(await pasteTarget("octo/typo", false, says(false)), "/octo/typo");
  // The check failing never blocks the way in.
  assert.equal(await pasteTarget("octo/real", false, async () => { throw new Error("offline"); }), "/signin?callbackUrl=%2Focto%2Freal");
  // Signed in, or an example: straight to the report (its 404 is the proxy's), no question asked.
  asked.length = 0;
  assert.equal(await pasteTarget("octo/typo", true, says(false)), "/octo/typo");
  assert.equal(await pasteTarget(EXAMPLES[0].repo, false, says(false)), `/${EXAMPLES[0].repo}`);
  assert.deepEqual(asked, []);
});

// Account pages (Compare, pre-flight, the dashboard, settings).
const SIGNED_OUT_COOKIES = [[], ["__cf_bm"], ["authjs.csrf-token", "authjs.callback-url", "holt-rail"]];
const SESSIONS = ["authjs.session-token", "__Secure-authjs.session-token", "__Secure-authjs.session-token.0"];
const ACCOUNT_URLS = [
  "/compare", "/compare/", "/compare?repos=pallets/flask,psf/requests", "/preflight", "/preflight?pr=https://github.com/o/r/pull/1",
  "/me", "/me/repos?show=saved", "/settings", "/settings/profile",
];
const OPEN_URLS = [
  "/", "/hacktoberfest", "/hacktoberfest?lang=go", "/examples", "/example-merge-plan", "/pricing", "/how-it-works", "/badge", "/badge?repo=o/r",
  "/terms", "/privacy", "/refunds", "/contact", "/signin?callbackUrl=%2Fcompare", "/alerts/unsubscribe?t=x", "/pricing/thanks",
  // Find and Browse: lists of what Holt has checked, every sort, language and topic.
  "/find", "/find?go=1&lang=python&days=7", "/discover", "/discover/", "/discover?sort=stars&topic=cli", "/discover/python", "/discover/c%2B%2B?sort=trending",
  "/pallets/flask", "/pallets/flask?mode=ai",
  // GitHub owners that only start like an account page.
  "/find/repo", "/compare/repo", "/preflight/repo", "/discovery/repo", "/finder", "/mes/repo",
];

const arrive = (url: string, cookies: string[]) => {
  const [pathname, query] = url.split("?");
  return arrivalGate(pathname, query ? `?${query}` : "", cookies);
};

test("signed out, arriving on an account page goes to sign-in, then back to that exact page", () => {
  for (const cookies of SIGNED_OUT_COOKIES) {
    for (const url of ACCOUNT_URLS) {
      const to = arrive(url, cookies);
      assert.ok(to, `${url} with [${cookies}]`);
      assert.ok(to.startsWith("/signin?callbackUrl="), to);
      assert.equal(back(to), url);
      // /signin accepts it as a place to come back to.
      assert.equal(afterSignIn(back(to)), url);
    }
  }
});

test("a session cookie is let through to the page, which asks who it is", () => {
  for (const session of SESSIONS) {
    for (const url of ACCOUNT_URLS) assert.equal(arrive(url, [session]), null, `${url} with ${session}`);
  }
  // A cookie that only looks like one is not a session.
  for (const fake of ["session-token", "authjs.session-token-x", "xauthjs.session-token", "holt-signed-in"]) {
    assert.ok(arrive("/compare", [fake]), fake);
  }
});

test("the public pages, reports and repos named like an account page stay open", () => {
  for (const url of OPEN_URLS) assert.equal(arrive(url, []), null, url);
});

test("every account page asks the server who is signed in before it loads anything", () => {
  const app = join(import.meta.dirname, "../app");
  for (const page of ["compare", "preflight"]) {
    const src = readFileSync(join(app, page, "page.tsx"), "utf-8");
    // The page, and its metadata when that is worked out per request.
    const entries = src.split(/^export (?:default )?async function /m).slice(1);
    assert.ok(entries.length >= 1, page);
    for (const body of entries) {
      const gate = body.indexOf("await requireUser(");
      assert.ok(gate >= 0, `${page}: ${body.slice(0, 20)} never asks`);
      // Before it, only the request's own address is read.
      assert.deepEqual(body.slice(0, gate).match(/await [^;]+/g)?.filter((a) => a !== "await searchParams") ?? [], [], page);
    }
    assert.doesNotMatch(src, /currentUser\(/, `${page}: no path for a visitor without an account`);
  }
});

test("Find and Browse are open: no page or part of a list asks for an account", () => {
  const src = join(import.meta.dirname, "..");
  for (const file of ["app/find/page.tsx", "app/discover/page.tsx", "app/discover/[language]/page.tsx", "components/discover/discover-view.tsx", "app/api/discover/route.ts", "app/api/find/more/route.ts"]) {
    assert.doesNotMatch(readFileSync(join(src, file), "utf-8"), /requireUser|signedInGate/, file);
  }
  // The parts a list loads as it is scrolled read what Holt has checked, and never search GitHub or start a check.
  assert.match(readFileSync(join(src, "app/api/find/more/route.ts"), "utf-8"), /await findIndex\(/);
  for (const route of ["discover", "find/more"]) {
    assert.doesNotMatch(readFileSync(join(src, "app/api", route, "route.ts"), "utf-8"), /cachedFind|\bfind\(|startAnalysis|@\/lib\/session/, route);
  }
  // Signed out, Find shows the search every visitor shares, and other filters are answered from the index alone: no search starts.
  assert.match(readFileSync(join(src, "app/find/page.tsx"), "utf-8"), /user \|\| shared \? await cachedFind\(.*\) : await indexFind\(picks\)/);
  assert.match(readFileSync(join(src, "app/api/find/route.ts"), "utf-8"), /findReads\(who\.userId\) === "search" \? await cachedFind\(.*\) : await indexFind\(picks\)/);
  const index = readFileSync(join(src, "lib/find-index.ts"), "utf-8");
  assert.match(index, /await findIndex\(/);
  assert.doesNotMatch(index, /cachedFind|\bfind\(|startAnalysis/);
  // The filters never swap the list for a sign-in box.
  assert.doesNotMatch(readFileSync(join(src, "components/find/find-view.tsx"), "utf-8"), /locked|data-signin-card/);
});

test("signed out: the data routes behind account pages answer 401 before reading anything", () => {
  const refused = signedInGate(null);
  assert.ok(refused);
  assert.equal(refused.status, 401);
  assert.equal(refused.error.code, "unauthorized");
  assert.equal(signedInGate("user-1"), null);
  const api = join(import.meta.dirname, "../app/api");
  for (const route of ["preflight", "preflight-jobs/[job]/events", "merge-plan-jobs/[job]/events", "playbook-jobs/[job]/events", "picks"]) {
    const src = readFileSync(join(api, route, "route.ts"), "utf-8");
    const get = src.slice(src.indexOf("export async function GET"));
    const gate = get.indexOf("signedInGate(");
    const data = get.search(/preflightState\(|proxyJobEvents\(|recommendations\(/);
    assert.ok(gate >= 0 && data > gate, `${route}: the gate comes before the data`);
  }
});

test("the sign-in wall never appears as a page a crawler is sent to", () => {
  const app = join(import.meta.dirname, "../app");
  const sitemap = readFileSync(join(app, "sitemap.ts"), "utf-8");
  for (const path of ["/compare", "/preflight"]) {
    assert.ok(needsAccount(path), path);
    assert.doesNotMatch(sitemap, new RegExp(`["\`]${path}["/\`]`), `sitemap lists ${path}`);
  }
  const robots = readFileSync(join(app, "robots.ts"), "utf-8");
  for (const path of ["/compare", "/preflight", "/me/", "/settings"]) assert.match(robots, new RegExp(`"${path}[$"]`), `robots.txt allows ${path}`);
});

test("crawlers are sent to Find and the boards, and kept off the boards' facets", () => {
  const app = join(import.meta.dirname, "../app");
  const sitemap = readFileSync(join(app, "sitemap.ts"), "utf-8");
  for (const path of ["/find", "/discover"]) {
    assert.ok(!needsAccount(path), path);
    assert.match(sitemap, new RegExp(`path: "${path}"`), `sitemap lists ${path}`);
  }
  assert.match(sitemap, /\/discover\/\$\{languageSlug\(/);
  const disallow: string[] = readFileSync(join(app, "robots.ts"), "utf-8").match(/"\/[^"]*"/g) ?? [];
  assert.ok(disallow.includes('"/discover?"') && disallow.includes('"/discover/*?"') && disallow.includes('"/find?"'));
  // Nothing that would cover /find, /discover or /discover/python themselves.
  for (const rule of disallow) assert.doesNotMatch(rule, /^"\/(find[$\/"]|discover\$|discover\/?")/, rule);
});

// A signed-out page that asks a gated route logs a 401 in the visitor's console.
test("the open pages never ask a gated route: only signed-in parts of the app do", () => {
  const src = join(import.meta.dirname, "..");
  const GATED = /\/api\/(preflight|preflight-jobs|merge-plan-jobs|playbook-jobs|picks)\b/;
  const askers = (readdirSync(src, { recursive: true }) as string[])
    .map((f) => f.replaceAll("\\", "/"))
    .filter((f) => /\.tsx?$/.test(f) && !f.endsWith(".test.ts") && !f.startsWith("app/api/") && GATED.test(readFileSync(join(src, f), "utf-8")))
    .sort();
  // The picks' next parts and the pre-flight page (both gated), the link to it, and two streams that open only after a signed-in POST starts a job.
  assert.deepEqual(askers, ["app/me/picks/picks-list.tsx", "components/preflight/preflight-link.tsx", "components/preflight/preflight-view.tsx", "components/report/merge-plan-panel.tsx", "components/report/playbook-section.tsx"]);
  // The link asks as soon as it is on the page, so it is only ever there for someone signed in.
  const uses = (readdirSync(src, { recursive: true }) as string[])
    .filter((f) => /\.tsx$/.test(f) && !f.endsWith("preflight-link.tsx"))
    .flatMap((f) => readFileSync(join(src, f), "utf-8").split("\n").filter((line) => line.includes("<PreflightLink")));
  assert.ok(uses.length >= 1);
  for (const line of uses) assert.match(line, /signedIn && <PreflightLink/, line.trim());
});
