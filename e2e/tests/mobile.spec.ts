// Phone layout checks. Rules mode only: nothing here starts an AI report.
import { expect, test, type Page } from "@playwright/test";

const PAGES = [
  "/",
  "/pallets/flask",
  "/pallets/flask?mode=ai",
  "/find?go=1&lang=python",
  "/hacktoberfest",
  "/compare?repos=pallets/flask,psf/requests",
  "/pricing",
  "/how-it-works",
  "/settings",
  "/signin",
  "/me/history",
];

const WIDTH = 360;

/**
 * Measured against the device width, not innerWidth: on a phone, content that
 * is too wide makes the browser widen the layout viewport (innerWidth grows
 * and the page zooms out), so innerWidth alone would hide the problem.
 */
async function overflow(page: Page) {
  return page.evaluate((vw) => {
    const clipped = (el: Element) => {
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        if (getComputedStyle(a).overflowX !== "visible") return true;
      }
      return false;
    };
    const wide: string[] = [];
    for (const el of document.body.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();
      if (r.width && r.right > vw + 1 && !clipped(el) && getComputedStyle(el).position !== "fixed") {
        wide.push(`${el.tagName.toLowerCase()}.${String(el.className).split(" ").slice(0, 3).join(".")} → ${Math.round(r.right)}px`);
      }
    }
    return { scrollWidth: document.scrollingElement!.scrollWidth, innerWidth: window.innerWidth, vw, wide: wide.slice(0, 8) };
  }, WIDTH);
}

test.describe("phone layout at 360px", () => {
  test.use({ viewport: { width: WIDTH, height: 780 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });

  for (const path of PAGES) {
    test(`no sideways scroll: ${path}`, async ({ page }, testInfo) => {
      test.skip(testInfo.project.name !== "phone", "phone project only");
      // Not "networkidle": report and compare pages keep an event stream open.
      await page.goto(path, { waitUntil: "load" });
      await page.waitForTimeout(1500);
      const o = await overflow(page);
      const why = `layout ${o.innerWidth}px / content ${o.scrollWidth}px on a ${o.vw}px phone: ${o.wide.join(" | ")}`;
      expect(o.innerWidth, why).toBeLessThanOrEqual(o.vw);
      expect(o.scrollWidth, why).toBeLessThanOrEqual(o.vw);
    });
  }

  test("the viewport meta lets phones render at device width", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "phone", "phone project only");
    await page.goto("/");
    await expect(page.locator('meta[name="viewport"]')).toHaveAttribute("content", /width=device-width/);
  });
});

test("the OPEN / SOURCE band slides as you scroll (desktop)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "desktop project only");
  await page.goto("/");
  const band = page.locator("[data-marquee]");
  await band.scrollIntoViewIfNeeded();
  // Let the motion engine attach (GSAP loads after idle where CSS scroll timelines are missing).
  await expect(band).toHaveAttribute("data-engine", /css|gsap|raf/, { timeout: 10_000 });
  const x = () => band.evaluate((el) => new DOMMatrixReadOnly(getComputedStyle(el).transform).m41);
  await page.evaluate(() => window.scrollBy(0, -250));
  await page.waitForTimeout(400);
  const a = await x();
  await page.evaluate(() => window.scrollBy(0, 250));
  await page.waitForTimeout(400);
  const b = await x();
  expect(Math.abs(b - a), `band moved from ${a}px to ${b}px`).toBeGreaterThan(2);
});
