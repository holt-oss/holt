// Smoke check against a running site: the policy pages the payment processors
// look for exist, render, and are reachable from every page's footer.
//
//   E2E_BASE_URL=http://localhost:3000 npm run e2e
//
// Needs `npm run dev` or `npm start` on that URL (MOCK_API=1 is fine; no
// database needed). Not part of `npm test`, which must stay network-free.
import assert from "node:assert/strict";
import { before, test } from "node:test";

const BASE = (process.env.E2E_BASE_URL || "http://localhost:3000").replace(/\/$/, "");
const PAGES = ["/terms", "/privacy", "/refunds", "/contact"];

async function page(path: string): Promise<{ status: number; html: string }> {
  const res = await fetch(BASE + path, { redirect: "manual" });
  return { status: res.status, html: await res.text() };
}

function footerOf(html: string): string {
  const m = html.match(/<footer[\s\S]*?<\/footer>/i);
  assert.ok(m, "the page has a <footer>");
  return m[0];
}

before(async () => {
  try {
    await fetch(BASE, { redirect: "manual" });
  } catch (e) {
    throw new Error(`nothing is listening at ${BASE}: start the app first (npm run dev -- -p PORT) or set E2E_BASE_URL. ${(e as Error).message}`);
  }
});

for (const path of PAGES) {
  test(`${path} renders with a last-updated date`, async () => {
    const { status, html } = await page(path);
    assert.equal(status, 200);
    assert.match(html, /Last updated:/);
    assert.match(html, /<h1[^>]*>/);
    // A static page ships no route skeleton: the footer is in the first response.
    footerOf(html);
  });
}

test("the footer links every policy page", async () => {
  const { html } = await page("/");
  const footer = footerOf(html);
  for (const path of PAGES) assert.match(footer, new RegExp(`href="${path}"`), `footer links ${path}`);
});

test("/pricing links the refund policy", async () => {
  const { status, html } = await page("/pricing");
  assert.equal(status, 200);
  assert.match(html, /href="\/refunds"/);
});
