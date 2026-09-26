import assert from "node:assert/strict";
import { test } from "node:test";
import { hacktoberfest } from "./site.ts";

const at = (iso: string) => hacktoberfest(new Date(iso));

test("counts down in September", () => {
  assert.deepEqual(at("2026-09-25T12:00:00Z"), { live: false, year: 2026, text: "Hacktoberfest 2026 starts in 6 days.", short: "starts in 6 days" });
  assert.equal(at("2026-09-30T23:59:59Z")?.text, "Hacktoberfest 2026 starts in 1 day.");
});

test("is on from 1 to 31 October", () => {
  assert.deepEqual(at("2026-10-01T00:00:00Z"), { live: true, year: 2026, text: "Hacktoberfest is on. 31 days left.", short: "31 days left" });
  assert.equal(at("2026-10-31T23:00:00Z")?.text, "Hacktoberfest is on. 1 day left.");
});

test("hides after October and long before it", () => {
  assert.equal(at("2026-11-01T00:00:00Z"), null);
  assert.equal(at("2026-12-15T00:00:00Z"), null);
  assert.equal(at("2026-07-01T00:00:00Z"), null);
});

test("the campaign page knows when October is over", async () => {
  const { hacktoberfestOver } = await import("./site.ts");
  assert.equal(hacktoberfestOver(2026, new Date("2026-10-31T23:59:59Z")), false);
  assert.equal(hacktoberfestOver(2026, new Date("2026-11-01T00:00:00Z")), true);
});

test("contact details fall back to visible placeholders", async () => {
  const { CONTACT_EMAIL, CONTACT_CITY, LEGAL_PAGES, LEGAL_UPDATED } = await import("./site.ts");
  assert.equal(CONTACT_EMAIL, process.env.NEXT_PUBLIC_CONTACT_EMAIL || "CONTACT_EMAIL");
  assert.equal(CONTACT_CITY, process.env.NEXT_PUBLIC_CONTACT_CITY || "CONTACT_CITY");
  assert.deepEqual(LEGAL_PAGES.map((p) => p.href), ["/terms", "/privacy", "/refunds", "/contact"]);
  assert.match(LEGAL_UPDATED, /^\d{1,2} [A-Z][a-z]+ \d{4}$/);
});
