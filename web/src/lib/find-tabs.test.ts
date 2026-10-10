import assert from "node:assert/strict";
import { test } from "node:test";
import { findTabs } from "./find-tabs.ts";

test("find a project has a tab per page, Hacktoberfest only in season or on its page", () => {
  const ids = (season: boolean, current: "find" | "hacktoberfest" = "find") => findTabs({ signedIn: true, season, current }).map((t) => t.id);
  assert.deepEqual(ids(false), ["find", "browse"]);
  assert.deepEqual(ids(true), ["find", "browse", "hacktoberfest"]);
  assert.deepEqual(ids(false, "hacktoberfest"), ["find", "browse", "hacktoberfest"]);
  assert.deepEqual(findTabs({ signedIn: true, season: true, current: "find" }).map((t) => t.href), ["/find", "/discover", "/hacktoberfest"]);
});

test("discovery destinations keep the same names before and after sign-in", () => {
  for (const signedIn of [true, false]) {
    const tabs = findTabs({ signedIn, season: false, current: "find" });
    assert.deepEqual(tabs.map(({ label }) => label), ["Find a project", "Browse projects"]);
  }
});

test("a tab's phone label is the start of its full name", () => {
  const tabs = findTabs({ signedIn: false, season: true, current: "find" });
  assert.deepEqual(tabs.map((t) => t.short ?? t.label), ["Find", "Browse", "Hacktoberfest"]);
  for (const t of tabs) assert.ok(t.label.startsWith(t.short ?? t.label));
});
