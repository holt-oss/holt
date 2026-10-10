// Smoke tests for a deployed Holt. Rules mode only: nothing here may start an
// AI report or spend quota.
import { expect, test, type Page } from "@playwright/test";

const VERDICT = /Worth your time|Not worth your time|Not enough evidence/;

// The test machine's network blipping is not a bug in the page.
const NOT_THE_APP = /net::ERR_NETWORK_CHANGED|net::ERR_INTERNET_DISCONNECTED/;

/** Collects console errors and uncaught exceptions for the page's lifetime. */
function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" && !NOT_THE_APP.test(m.text())) errors.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  return errors;
}

test("landing: pasting an example's GitHub URL ends on the report with a verdict", async ({ page }) => {
  await page.goto("/");
  const box = page.getByLabel("GitHub repository or URL");
  // pallets/flask is one of the examples (web/src/lib/examples.ts), readable signed out.
  await box.fill("https://github.com/pallets/flask");
  // The landing page has a second paste box at the bottom; click the one we filled.
  await page.locator("form").filter({ has: box }).getByRole("button", { name: /check/i }).click();
  await expect(page).toHaveURL(/\/pallets\/flask$/);
  // A cached report renders at once; otherwise the rules check runs first.
  await expect(page.getByText(VERDICT).first()).toBeVisible({ timeout: 180_000 });
});

test("landing, signed out: pasting any other repo opens its report, with sign-in for the rest", async ({ page }) => {
  await page.goto("/");
  const box = page.getByLabel("GitHub repository or URL");
  await box.fill("octocat/Hello-World");
  await page.locator("form").filter({ has: box }).getByRole("button", { name: /check this repo/i }).click();
  await expect(page).toHaveURL(/\/octocat\/Hello-World$/);
  // Under the verdict (from the index or the free check), or in its place for a test browser: sign in, and back here.
  await expect(page.locator("a[href='/signin?callbackUrl=%2Foctocat%2FHello-World']").first()).toBeVisible({ timeout: 180_000 });
});

test("URL trick: /github.com/owner/repo redirects to the report", async ({ page, request }) => {
  const res = await request.get("/github.com/pallets/flask", { maxRedirects: 0 });
  expect([301, 302, 307, 308]).toContain(res.status());
  expect(res.headers()["location"]).toMatch(/\/pallets\/flask$/);

  await page.goto("/https://github.com/pallets/flask/pulls");
  await expect(page).toHaveURL(/\/pallets\/flask$/);
});

test("find, signed out: the default search lists a repo with an issue link", async ({ page }) => {
  // Signed out, /find shows the shared default search.
  await page.goto("/find");
  const results = page.getByRole("region", { name: "Results" });
  const issue = results.locator('a[href^="https://github.com/"][href*="/issues/"]').first();
  const failure = results.getByRole("alert");
  await expect(issue.or(failure)).toBeVisible({ timeout: 180_000 });
  if (await failure.isVisible()) {
    const text = (await failure.innerText()).trim();
    test.skip(/too many|rate/i.test(text), `rate limited on staging: ${text}`);
    throw new Error(`find failed: ${text}`);
  }
  await expect(results.locator('a[href^="/"]').first()).toBeVisible();
});

test("find, signed out: picking a language on a small phone lists repos, from Holt's index alone", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  const answers: { status: string; job_id?: string }[] = [];
  page.on("response", async (r) => {
    if (r.request().method() === "POST" && new URL(r.url()).pathname === "/api/find") answers.push(await r.json());
  });
  await page.goto("/find");
  await page.getByRole("button", { name: "Python", exact: true }).click();
  await expect(page).toHaveURL(/\/find\?lang=python/);
  const results = page.getByRole("region", { name: "Results" });
  await expect(results).toHaveAttribute("aria-busy", "false");
  // Cards, or "none match" on a thin index: never a sign-in box in place of the list.
  const cards = results.locator('a[href^="/"]:not([href^="/signin"])');
  const none = results.getByText(/No repos match/);
  await expect(cards.first().or(none)).toBeVisible();
  if (await cards.count()) await expect(results.getByRole("link", { name: /sign in/ })).toHaveCount(0);
  // The index answered: a search of GitHub would come back queued, with a job.
  expect(answers.map((a) => [a.status, a.job_id])).toEqual([["done", undefined]]);
});

test("find, signed out: a page opened with filters shows its list, not sign-in", async ({ page }) => {
  await page.goto("/find?go=1&lang=python&days=7");
  await expect(page).toHaveURL(/\/find\?/);
  const results = page.getByRole("region", { name: "Results" });
  await expect(results.locator('a[href^="/"]:not([href^="/signin"])').first().or(results.getByText(/No repos match/))).toBeVisible();
});

// Browse is open: every board, order, language and topic, and the parts a list loads as it is scrolled.
for (const path of ["/discover", "/discover/python", "/discover?sort=stars", "/discover/python?sort=trending"]) {
  test(`signed out, ${path} shows its board`, async ({ page, request }) => {
    const res = await request.get(path, { maxRedirects: 0 });
    expect(res.status()).toBe(200);
    await page.goto(path);
    await expect(page).toHaveURL(new RegExp(`${path.replace(/[?]/g, "\\?")}$`));
    await expect(page.getByRole("navigation", { name: "Order" })).toBeVisible();
    // A card, or the board's own "nothing here yet": never the sign-in page.
    await expect(page.getByRole("main").locator('a[href^="/"]').first()).toBeVisible();
  });
}

test("signed out, a list's next parts come from Holt's index", async ({ request }) => {
  const board = await request.get("/api/discover?sort=stars");
  expect(board.status()).toBe(200);
  expect(Array.isArray((await board.json()).items)).toBe(true);
  const more = await request.post("/api/find/more", { data: { q: "lang=python&days=7", cursor: null } });
  expect(more.status()).toBe(200);
  expect(Array.isArray((await more.json()).items)).toBe(true);
});

// What only the full report has: the evidence list, starter issues, the README. (The locked teaser names the sections over placeholders.)
const FULL_REPORT = /id="evidence"|"id":"evidence"|data-readme|"evidence":\s*\[\s*\{/;

test("signed out, a report opened from a Browse card is the teaser, and nothing sends the rest", async ({ page, request }) => {
  await page.goto("/discover?sort=stars");
  const cards = page.getByRole("main").locator('a[href^="/"]');
  await expect(cards.first()).toBeVisible();
  // The first card that is a repo, and not one of the examples (those read in full signed out).
  const hrefs = await cards.evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""));
  const examples = (await (await request.get("/examples")).text()).toLowerCase();
  const href = hrefs.find((h) => /^\/[\w.-]+\/[\w.-]+$/.test(h) && !h.startsWith("/discover/") && !examples.includes(`href="${h.toLowerCase()}"`));
  test.skip(!href, "no card on the board that isn't an example");
  await page.locator(`a[href="${href}"]`).first().click();
  await expect(page).toHaveURL(new RegExp(`${href}$`));
  await expect(page.locator("[data-teaser]")).toBeVisible();
  await expect(page.locator("[data-teaser]").getByRole("link", { name: /sign in/ }).first()).toHaveAttribute("href", /^\/signin\?callbackUrl=/);
  await expect(page.locator("#evidence")).toHaveCount(0);

  // The page itself, as a load and as a client-side navigation.
  for (const headers of [{}, { RSC: "1" }]) {
    const res = await request.get(href!, { headers });
    expect(res.status()).toBe(200);
    expect(await res.text()).not.toMatch(FULL_REPORT);
  }
  // The AI tab asks for sign-in.
  const ai = await request.get(`${href}?mode=ai`, { maxRedirects: 0 });
  // A redirect, or one sent in the page once it has started streaming.
  const aiBody = await ai.text();
  expect(ai.status() === 307 ? ai.headers()["location"] : aiBody).toContain("/signin?callbackUrl=");
  expect(aiBody).not.toMatch(FULL_REPORT);
  // The extension's route gives the verdict and counts, never the evidence; the rest answer 401.
  const pub = await request.get(`/api/public/report${href}`);
  if (pub.ok()) expect((await pub.json()).evidence ?? []).toEqual([]);
  expect((await request.get("/api/analyses/x")).status()).toBe(401);
  expect((await request.get(`/api/preflight?repo=${href!.slice(1)}`)).status()).toBe(401);
});

// Compare and pre-flight are for signed-in people (web/src/lib/gate.ts).
for (const path of ["/compare", "/compare?repos=pallets/flask,psf/requests", "/preflight"]) {
  test(`signed out, ${path} goes to sign-in and sends no data`, async ({ page, request }) => {
    const res = await request.get(path, { maxRedirects: 0 });
    expect(res.status()).toBe(307);
    const to = new URL(res.headers()["location"], "https://holt.test");
    expect(to.pathname).toBe("/signin");
    expect(decodeURIComponent(to.searchParams.get("callbackUrl") ?? "")).toBe(path);
    expect(await res.text()).not.toContain("github.com");
    // What a client-side navigation or prefetch asks for.
    const rsc = await request.get(path, { maxRedirects: 0, headers: { RSC: "1" } });
    expect(rsc.status()).toBe(307);

    await page.goto(path);
    await expect(page).toHaveURL(/\/signin\?callbackUrl=/);
  });
}

test("signed out, the data routes behind those pages answer 401", async ({ request }) => {
  for (const path of ["/api/preflight", "/api/preflight-jobs/x/events", "/api/merge-plan-jobs/x/events", "/api/playbook-jobs/x/events"]) {
    expect((await request.get(path)).status(), path).toBe(401);
  }
});

test("signed out, Find's filters are answered at once: no search job is started", async ({ request }) => {
  const res = await request.post("/api/find", { data: { q: "lang=python&days=7&hacktoberfest=0" } });
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.status).toBe("done");
  expect(body.job_id).toBeUndefined();
});

test("Hacktoberfest pill: × hides it, and it stays hidden after a reload", async ({ page }, testInfo) => {
  await page.goto("/");
  const pill = page.locator(".hf-pill");
  test.skip((await pill.count()) === 0, "no Hacktoberfest pill outside the season");
  await expect(pill).toBeVisible();
  const close = page.getByRole("button", { name: "Hide the Hacktoberfest notice" });
  if (testInfo.project.name === "phone") {
    const box = await close.boundingBox();
    // 43.5: layout can land a hair under 44px at fractional device pixel ratios.
    expect(box?.height ?? 0, "the × is a comfortable tap target").toBeGreaterThanOrEqual(43.5);
  }
  await close.click();
  await expect(page).toHaveURL(/\/$/); // dismissing must not navigate
  await expect(pill).toBeHidden();
  await page.reload();
  await expect(pill).toBeHidden();
});

test("theme toggle persists across a reload", async ({ page }) => {
  await page.goto("/");
  const html = page.locator("html");
  const before = await html.getAttribute("data-theme");
  expect(before).toMatch(/^(light|dark)$/);
  await page.getByRole("button", { name: /switch between light and dark theme/i }).first().click();
  const after = before === "dark" ? "light" : "dark";
  await expect(html).toHaveAttribute("data-theme", after);
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", after);
  expect(await page.evaluate(() => localStorage.getItem("holt-theme"))).toBe(after);
});

test("pricing renders the plans", async ({ page }) => {
  // Plans and prices change (Pro passes come from /v1/passes and show only
  // while on sale), so check the shape: a heading, a priced plan, and a way
  // to act on one.
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const prices = page.locator("main").getByText(/^\s*(\$|₹|€|£)\s?\d/);
  await expect(prices.first()).toBeVisible();
  const cta = page.locator("main").locator("a[href], button").filter({ hasText: /\S/ })
    .filter({ hasText: /sign in|start|get|choose|buy|upgrade|subscribe|add a key|check a repo|→/i });
  await expect(cta.first()).toBeVisible();
});

test("public extension endpoints answer with CORS headers", async ({ request }) => {
  const origin = "chrome-extension://holt-smoke-test";
  for (const path of ["/api/public/report/pallets/flask", "/api/public/starter-issues/pallets/flask"]) {
    const pre = await request.fetch(path, {
      method: "OPTIONS",
      headers: { Origin: origin, "Access-Control-Request-Method": "GET" },
    });
    expect(pre.status(), `${path} preflight`).toBeLessThan(300);
    expect(pre.headers()["access-control-allow-methods"]).toContain("GET");

    const res = await request.get(path, { headers: { Origin: origin } });
    // 429 is a fair answer too (the API's per-IP limit); it must still carry CORS.
    expect([200, 404, 429], `${path} status`).toContain(res.status());
    expect(["*", origin]).toContain(res.headers()["access-control-allow-origin"]);
    expect(res.headers()["content-type"]).toContain("application/json");
    await res.json();
  }
});

test("/__build is valid JSON describing what's live", async ({ request }) => {
  const res = await request.get("/__build");
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.live?.main?.sha).toMatch(/^[0-9a-f]{40}$/);
  expect(Array.isArray(body.live?.included)).toBe(true);
  expect(body.live?.built_at).toBeTruthy();
});

for (const path of ["/", "/pallets/flask", "/find", "/discover", "/pricing", "/how-it-works"]) {
  test(`no console errors on ${path}`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto(path, { waitUntil: "networkidle" });
    if (path === "/pallets/flask") await expect(page.getByText(VERDICT).first()).toBeVisible({ timeout: 180_000 });
    await page.waitForTimeout(500);
    expect(errors).toEqual([]);
  });
}
