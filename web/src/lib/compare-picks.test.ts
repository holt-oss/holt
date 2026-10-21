import assert from "node:assert/strict";
import { test } from "node:test";
import { MAX } from "./compare.ts";
import { addPick, comparePicksHref, createPickStore, PICKS_KEY, readPicks, removePick, SENT_KEY, shortName, tickState, togglePick } from "./compare-picks.ts";
import { safeCallback } from "./safe-url.ts";

const FOUR = ["pallets/flask", "django/django", "psf/requests", "rust-lang/rust"];

function fakeStorage(init: Record<string, string> = {}) {
  const data = new Map(Object.entries(init));
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

test("a pick is added once, whatever its case", () => {
  assert.deepEqual(addPick([], "pallets/flask"), ["pallets/flask"]);
  assert.deepEqual(addPick(["pallets/flask"], "Pallets/Flask"), ["pallets/flask"]);
  assert.deepEqual(togglePick(["pallets/flask"], "PALLETS/flask"), []);
  assert.deepEqual(removePick(FOUR, "Django/Django"), ["pallets/flask", "psf/requests", "rust-lang/rust"]);
});

test("four at most: a fifth is not added, and its tick says so", () => {
  assert.equal(FOUR.length, MAX);
  assert.deepEqual(addPick(FOUR, "golang/go"), FOUR);
  assert.deepEqual(togglePick(FOUR, "golang/go"), FOUR);
  assert.equal(tickState(FOUR, "golang/go"), "full");
  assert.equal(tickState(FOUR, "psf/requests"), "on");
  assert.equal(tickState(FOUR.slice(0, 3), "golang/go"), "off");
  // A ticked one can still come off a full list.
  assert.equal(togglePick(FOUR, "psf/requests").length, 3);
});

test("the bar's names leave the owner out unless two picks share a name", () => {
  assert.equal(shortName("pallets/flask", FOUR), "flask");
  assert.equal(shortName("vuejs/core", ["vuejs/core", "home-assistant/core"]), "vuejs/core");
  assert.equal(shortName("vuejs/core"), "core");
});

test("what storage holds is read back as real repos only, without duplicates, four at most", () => {
  assert.deepEqual(readPicks(JSON.stringify(["pallets/flask", "Pallets/Flask", 7, "nope", "psf/requests"])), ["pallets/flask", "psf/requests"]);
  assert.deepEqual(readPicks(JSON.stringify([...FOUR, "golang/go"])), FOUR);
  for (const bad of [null, "", "{", '"a/b"', "{}"]) assert.deepEqual(readPicks(bad), []);
});

test("picks persist: a new store over the same storage starts from them", () => {
  const storage = fakeStorage();
  const a = createPickStore(() => storage);
  a.toggle("pallets/flask");
  a.toggle("django/django");
  a.toggle("pallets/flask");
  a.toggle("psf/requests");
  assert.deepEqual(createPickStore(() => storage).get(), ["django/django", "psf/requests"]);
  a.clear();
  assert.equal(storage.data.has(PICKS_KEY), false);
  assert.deepEqual(createPickStore(() => storage).get(), []);
});

test("the store tells its listeners only when the list changed, and keeps one array between changes", () => {
  const store = createPickStore(() => fakeStorage({ [PICKS_KEY]: JSON.stringify(FOUR) }));
  let calls = 0;
  const off = store.subscribe(() => calls++);
  const before = store.get();
  store.toggle("golang/go"); // full: nothing happens
  assert.equal(calls, 0);
  assert.equal(store.get(), before);
  store.remove("django/django");
  assert.equal(calls, 1);
  off();
  store.clear();
  assert.equal(calls, 1);
});

test("storage that throws leaves the picks in memory", () => {
  const store = createPickStore(() => {
    throw new Error("blocked");
  });
  store.toggle("pallets/flask");
  assert.deepEqual(store.get(), ["pallets/flask"]);
});

test("signed in, Compare opens with the picks; signed out, sign-in comes back to the same list", () => {
  const two = ["pallets/flask", "django/django"];
  assert.equal(comparePicksHref(two, true), "/compare?repos=pallets/flask,django/django");
  const href = comparePicksHref(two, false);
  assert.ok(href.startsWith("/signin?callbackUrl="));
  const callback = new URL(href, "http://holt.invalid").searchParams.get("callbackUrl");
  assert.equal(callback, "/compare?repos=pallets/flask,django/django");
  // The sign-in page accepts it as it is.
  assert.equal(safeCallback(callback), callback);
});

test("opening Compare clears the picks: at once signed in, after sign-in when signed out", () => {
  const storage = fakeStorage();
  const store = createPickStore(() => storage);
  store.toggle("pallets/flask");
  store.toggle("django/django");
  store.opened(false);
  assert.equal(store.get().length, 2);
  // Backed out of sign-in: still there.
  store.arrived(false);
  assert.equal(store.get().length, 2);
  assert.equal(storage.data.has(SENT_KEY), false);

  store.opened(false);
  // Signed in and back on a list in the same tab.
  const later = createPickStore(() => storage);
  later.arrived(true);
  assert.deepEqual(later.get(), []);
  assert.equal(storage.data.has(SENT_KEY), false);

  later.toggle("psf/requests");
  later.toggle("golang/go");
  later.opened(true);
  assert.deepEqual(later.get(), []);
});
