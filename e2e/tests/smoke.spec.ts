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

test("landing: pasting a GitHub URL ends on the report with a verdict", async ({ page }) => {
  await page.goto("/");
  const box = page.getByLabel("GitHub repository or URL");
  await box.fill("https://github.com/pallets/flask");
  await page.getByRole("button", { name: /check this repo/i }).click();
  await expect(page).toHaveURL(/\/pallets\/flask$/);
  // A cached report renders at once; otherwise the rules check runs first.
  await expect(page.getByText(VERDICT).first()).toBeVisible({ timeout: 180_000 });
});

test("URL trick: /github.com/owner/repo redirects to the report", async ({ page, request }) => {
  const res = await request.get("/github.com/pallets/flask", { maxRedirects: 0 });
  expect([301, 302, 307, 308]).toContain(res.status());
  expect(res.headers()["location"]).toMatch(/\/pallets\/flask$/);

  await page.goto("/https://github.com/pallets/flask/pulls");
  await expect(page).toHaveURL(/\/pallets\/flask$/);
});

test("find: Python + Hacktoberfest lists a repo with an issue link", async ({ page }) => {
  await page.goto("/find?go=1&lang=python&hacktoberfest=1&days=7");
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

test("Hacktoberfest pill: × hides it, and it stays hidden after a reload", async ({ page }, testInfo) => {
  await page.goto("/");
  const pill = page.locator(".hf-pill");
  test.skip((await pill.count()) === 0, "no Hacktoberfest pill outside the season");
  await expect(pill).toBeVisible();
  const close = page.getByRole("button", { name: "Hide the Hacktoberfest notice" });
  if (testInfo.project.name === "phone") {
    const box = await close.boundingBox();
    expect(box?.height ?? 0, "the × is a comfortable tap target").toBeGreaterThanOrEqual(44);
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
  // Plan names and prices change (and later come from /v1/plans), so check the
  // shape: a heading, at least two priced plans, and a way to act on one.
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const prices = page.locator("main").getByText(/^\s*(\$|₹|€|£)\s?\d/);
  await expect(prices.first()).toBeVisible();
  expect(await prices.count()).toBeGreaterThanOrEqual(2);
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

for (const path of ["/", "/pallets/flask", "/find", "/pricing", "/how-it-works"]) {
  test(`no console errors on ${path}`, async ({ page }) => {
    const errors = watchErrors(page);
    await page.goto(path, { waitUntil: "networkidle" });
    if (path === "/pallets/flask") await expect(page.getByText(VERDICT).first()).toBeVisible({ timeout: 180_000 });
    await page.waitForTimeout(500);
    expect(errors).toEqual([]);
  });
}
