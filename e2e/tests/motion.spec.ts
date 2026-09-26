// Motion and loading (docs/design/MOTION.md): no layout shift, skeletons only
// when a page is actually slow, menus that open and close, and nothing moving
// for visitors who asked for reduced motion. Rules mode only.
import { expect, test, type Page } from "@playwright/test";

const VERDICT = /Worth your time|Not worth your time|Not enough evidence/;

/** Starts summing layout shifts (not caused by input) from the first paint. */
async function watchShifts(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __cls: number; __shifts: string[] };
    w.__cls = 0;
    w.__shifts = [];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as unknown as { value: number; hadRecentInput: boolean; sources?: { node?: Node }[] }[]) {
        if (e.hadRecentInput) continue;
        w.__cls += e.value;
        const el = e.sources?.[0]?.node as Element | undefined;
        w.__shifts.push(`${e.value.toFixed(4)} ${el?.tagName?.toLowerCase() ?? "?"}.${String(el?.className ?? "").split(" ").slice(0, 3).join(".")}`);
      }
    }).observe({ type: "layout-shift", buffered: true });
  });
}
const shifts = (page: Page) => page.evaluate(() => {
  const w = window as unknown as { __cls: number; __shifts: string[] };
  return { cls: w.__cls, list: w.__shifts };
});

test.describe("no layout shift", () => {
  for (const path of ["/", "/pallets/flask", "/find?go=1&lang=python&days=7", "/pricing"]) {
    test(`cold load: ${path}`, async ({ page }) => {
      await watchShifts(page);
      await page.goto(path, { waitUntil: "load" });
      await page.waitForTimeout(2500);
      const s = await shifts(page);
      expect(s.cls, s.list.join(" | ")).toBeLessThan(0.01);
    });
  }

  test("client navigation to a report (skeleton, then content)", async ({ page }) => {
    await watchShifts(page);
    await page.goto("/");
    await openReportFromLanding(page, 0);
    await page.waitForTimeout(1500);
    const s = await shifts(page);
    expect(s.cls, s.list.join(" | ")).toBeLessThan(0.01);
  });
});

interface Timeline {
  committed: number | null; // skeleton in the DOM
  visible: number | null; // skeleton at least half visible
  maxOpacity: number;
  content: number | null; // skeleton gone, report in place
  response: number | null;
}

/**
 * Clicks the landing page's link to /pallets/flask after it has been
 * prefetched (so the loading skeleton can show at once) and records, frame by
 * frame, when the skeleton appears and when the report replaces it.
 * `delay` holds the navigation's server response back by that many ms.
 */
async function openReportFromLanding(page: Page, delay: number): Promise<Timeline> {
  let response: number | null = null;
  await page.route((u) => u.pathname === "/pallets/flask" && u.searchParams.has("_rsc"), async (route) => {
    const h = route.request().headers();
    if (h["next-router-prefetch"]) return route.continue();
    const sent = Date.now();
    if (delay) await new Promise((r) => setTimeout(r, delay));
    const res = await route.fetch();
    response = Date.now() - sent - delay;
    await route.fulfill({ response: res });
  });
  const link = page.locator('main a[href="/pallets/flask"]').first();
  const prefetched = page.waitForRequest((r) => r.url().includes("/pallets/flask?_rsc=") && Boolean(r.headers()["next-router-prefetch"]), { timeout: 15_000 }).catch(() => null);
  await link.scrollIntoViewIfNeeded();
  test.skip(!(await prefetched), "the report link was never prefetched");
  await page.waitForTimeout(500);
  await page.evaluate(() => {
    const w = window as unknown as { __tl: Timeline; __t0: number };
    w.__tl = { committed: null, visible: null, maxOpacity: 0, content: null, response: null };
    w.__t0 = performance.now();
    const tick = () => {
      const t = Math.round(performance.now() - w.__t0);
      const sk = document.querySelector("main [data-skeleton]");
      if (sk) {
        w.__tl.committed ??= t;
        const o = Number(getComputedStyle(sk).opacity);
        w.__tl.maxOpacity = Math.max(w.__tl.maxOpacity, o);
        if (o >= 0.5) w.__tl.visible ??= t;
      } else if (w.__tl.committed != null && document.querySelector("main h1")?.textContent?.match(/worth|evidence/i)) {
        w.__tl.content = t;
        return;
      }
      if (t < 10_000) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });
  // A script click: the link is below the fold on phones, and scrolling would move it.
  await link.evaluate((a: HTMLAnchorElement) => a.click());
  await expect(page).toHaveURL(/\/pallets\/flask$/);
  await expect(page.locator("main h1").filter({ hasText: VERDICT })).toBeVisible();
  await page.waitForTimeout(300);
  const tl = await page.evaluate(() => (window as unknown as { __tl: Timeline }).__tl);
  return { ...tl, response };
}

test.describe("skeletons", () => {
  test("show for a slow page, and stay until the content replaces them", async ({ page }) => {
    await page.goto("/");
    const tl = await openReportFromLanding(page, 600);
    const why = JSON.stringify(tl);
    expect(tl.committed, why).not.toBeNull();
    expect(tl.visible, `the skeleton never became visible: ${why}`).not.toBeNull();
    expect(tl.content, why).not.toBeNull();
    // React holds a shown fallback for at least 300ms, so it never blinks.
    expect(tl.content! - tl.committed!, why).toBeGreaterThanOrEqual(300);
  });

  test("don't flash for a fast page", async ({ page }) => {
    await page.goto("/");
    const tl = await openReportFromLanding(page, 0);
    test.skip(tl.response == null || tl.response > 100, `the server took ${tl.response}ms; this needs an answer under 100ms`);
    expect(tl.maxOpacity, JSON.stringify(tl)).toBeLessThan(0.1);
  });
});

test.describe("menus", () => {
  test("the phone menu opens, closes on Escape and on a click outside", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "phone", "phone project only");
    await page.goto("/pricing");
    const menu = page.locator("#mobile-nav");
    const button = page.getByRole("button", { name: "Menu" });
    const open = () => menu.evaluate((el) => el.matches(":popover-open"));

    await button.click();
    await expect.poll(open).toBe(true);
    await expect(menu.getByRole("link", { name: "compare" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect.poll(open).toBe(false);

    await button.click();
    await expect.poll(open).toBe(true);
    await page.mouse.click(200, 780);
    await expect.poll(open).toBe(false);
    await expect(page).toHaveURL(/\/pricing$/);

    // Picking a link closes it too (the header stays mounted across pages).
    await button.click();
    await menu.getByRole("link", { name: "compare" }).click();
    await expect(page).toHaveURL(/\/compare$/);
    await expect.poll(open).toBe(false);
  });
});

test("reduced motion: nothing moves", async ({ browser, baseURL }, testInfo) => {
  const ctx = await browser.newContext({ ...testInfo.project.use, baseURL, reducedMotion: "reduce" });
  const page = await ctx.newPage();
  await page.addInitScript(() => {
    const w = window as unknown as { __moving: string[] };
    w.__moving = [];
    const root = getComputedStyle(document.documentElement);
    const resolve = (v: string) => v.replace(/var\((--[\w-]+)\)/g, (_, n) => root.getPropertyValue(n).trim() || "0px");
    const nums = (v: string) => (resolve(v).match(/-?[\d.]+/g) ?? []).map(Number);
    const moves: Record<string, (v: string) => boolean> = {
      transform: (v) => {
        const r = resolve(v);
        if (r === "none") return false;
        try {
          return !new DOMMatrixReadOnly(r).isIdentity;
        } catch {
          return true;
        }
      },
      translate: (v) => nums(v).some((n) => n !== 0),
      scale: (v) => resolve(v) !== "none" && nums(v).some((n) => n !== 1),
      rotate: (v) => resolve(v) !== "none" && nums(v).some((n) => n !== 0),
    };
    const check = () => {
      for (const a of document.getAnimations()) {
        if (a.playState !== "running") continue;
        const effect = a.effect as KeyframeEffect | null;
        if (!effect || Number(effect.getComputedTiming().duration) === 0) continue;
        for (const kf of effect.getKeyframes()) {
          for (const [prop, test] of Object.entries(moves)) {
            const v = (kf as Record<string, unknown>)[prop];
            if (typeof v === "string" && test(v)) {
              const name = (a as CSSAnimation).animationName || (a as CSSTransition).transitionProperty || "animation";
              const label = `${name} ${prop}: ${v} on ${effect.pseudoElement ?? (effect.target as Element | null)?.className ?? "?"}`;
              if (!w.__moving.includes(label)) w.__moving.push(label);
            }
          }
        }
      }
      requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
  });

  await page.goto("/");
  await page.waitForTimeout(800);
  await page.goto("/pallets/flask");
  await expect(page.getByText(VERDICT).first()).toBeVisible();
  await page.waitForTimeout(800);
  // A client navigation (view transition) and a menu.
  if (testInfo.project.name === "phone") {
    await page.getByRole("button", { name: "Menu" }).click();
    await page.waitForTimeout(400);
    await page.locator("#mobile-nav").getByRole("link", { name: "pricing" }).click();
  } else {
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "pricing" }).click();
  }
  await expect(page).toHaveURL(/\/pricing$/);
  await page.waitForTimeout(800);
  const moving = await page.evaluate(() => (window as unknown as { __moving: string[] }).__moving);
  expect(moving).toEqual([]);
  await ctx.close();
});
