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

// Google's OAuth verification crawls /privacy for a contact address, and
// Cloudflare's Email Address Obfuscation would otherwise replace it with
// "[email protected]". The address must sit inside <!--email_off--> ... <!--email_on-->.
test("/privacy shows the contact address where Cloudflare leaves it alone", async () => {
  const { html } = await page("/privacy");
  const email = process.env.NEXT_PUBLIC_CONTACT_EMAIL;
  if (!email) {
    assert.match(html, /CONTACT_EMAIL/, "without the env the placeholder is visible, not blank");
    return;
  }
  const fragment = `<!--email_off--><a href="mailto:${email}" class="text-link">${email}</a><!--email_on-->`;
  assert.ok(html.includes(fragment), `the page contains ${fragment}`);
});

test("/privacy has the Google sign-in section and how it is protected", async () => {
  const { html } = await page("/privacy");
  assert.match(html, /<h2[^>]*id="google"/);
  assert.match(html, /<h3[^>]*id="protection"/);
});

test("/signin links the terms and the privacy policy under the buttons", async () => {
  const { status, html } = await page("/signin");
  assert.equal(status, 200);
  assert.match(html, /By signing in you agree to the/);
  assert.match(html, /href="\/terms"/);
  assert.match(html, /href="\/privacy#google"/);
});
