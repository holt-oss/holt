import assert from "node:assert/strict";
import { test } from "node:test";
import { rateLimit } from "./rate-limit.ts";

test("allows up to the limit per key, then refuses", () => {
  for (let i = 0; i < 3; i++) assert.equal(rateLimit("t:1.2.3.4", 3).ok, true);
  const r = rateLimit("t:1.2.3.4", 3);
  assert.equal(r.ok, false);
  assert.ok(!r.ok && r.retryAfter > 0 && r.retryAfter <= 60);
  assert.equal(rateLimit("t:5.6.7.8", 3).ok, true);
});
