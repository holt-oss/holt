import { expect, test } from "@playwright/test";

test("sign-in: the card stands alone, centred in the page", async ({ page }) => {
  await page.goto("/signin?callbackUrl=%2Fprocessing%2Fp5.js");
  const card = page.getByRole("region", { name: "Sign in to check processing/p5.js", exact: true });
  await expect(card).toBeVisible();
  await expect(card.getByRole("link", { name: "Try an example report →", exact: true })).toBeVisible();
  await expect(page.locator("main figure")).toHaveCount(0);
  await expect(page.getByText("example merge plan")).toHaveCount(0);
  const offCentre = await card.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return Math.abs(r.left + r.width / 2 - document.documentElement.clientWidth / 2);
  });
  expect(offCentre).toBeLessThanOrEqual(1);
});
