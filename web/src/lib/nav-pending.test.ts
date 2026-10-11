import assert from "node:assert/strict";
import { beforeEach, mock, test } from "node:test";
import { GIVE_UP_AFTER_MS, SHOW_AFTER_MS, navigationSettled, navigationStarted, pendingPath, subscribe } from "./nav-pending.ts";

beforeEach(() => {
  mock.timers.reset();
  mock.timers.enable({ apis: ["setTimeout"] });
  navigationSettled();
});

test("a navigation that lands quickly never shows as pending", () => {
  navigationStarted("/psf/requests", "/find");
  mock.timers.tick(SHOW_AFTER_MS - 1);
  assert.equal(pendingPath(), null);
  navigationSettled();
  mock.timers.tick(SHOW_AFTER_MS);
  assert.equal(pendingPath(), null);
});

test("a slow one is pending from the delay until the page changes", () => {
  const seen: (string | null)[] = [];
  const stop = subscribe(() => seen.push(pendingPath()));
  navigationStarted("/psf/requests", "/find");
  mock.timers.tick(SHOW_AFTER_MS);
  assert.equal(pendingPath(), "/psf/requests");
  navigationSettled();
  assert.equal(pendingPath(), null);
  assert.deepEqual(seen, ["/psf/requests", null]);
  stop();
});

test("the same page with another query is not a pending page", () => {
  navigationStarted("/find", "/find");
  mock.timers.tick(SHOW_AFTER_MS * 2);
  assert.equal(pendingPath(), null);
});

test("a second click replaces the first, and its delay starts again", () => {
  navigationStarted("/psf/requests", "/find");
  mock.timers.tick(SHOW_AFTER_MS);
  navigationStarted("/pallets/flask", "/find");
  assert.equal(pendingPath(), null);
  mock.timers.tick(SHOW_AFTER_MS);
  assert.equal(pendingPath(), "/pallets/flask");
});

test("a navigation that never lands stops showing as pending", () => {
  navigationStarted("/psf/requests", "/find");
  mock.timers.tick(GIVE_UP_AFTER_MS);
  assert.equal(pendingPath(), null);
});
