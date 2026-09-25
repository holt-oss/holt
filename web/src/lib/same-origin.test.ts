import assert from "node:assert/strict";
import { test } from "node:test";
import { isSameOrigin } from "./same-origin.ts";

const req = (h: Record<string, string>) => new Request("http://internal:3000/api/x", { method: "POST", headers: h });

test("accepts only this site's origin", () => {
  assert.equal(isSameOrigin(req({ origin: "https://holt.test", host: "holt.test" })), true);
  assert.equal(isSameOrigin(req({ origin: "https://evil.test", host: "holt.test" })), false);
  assert.equal(isSameOrigin(req({ host: "holt.test" })), false);
  assert.equal(isSameOrigin(req({ origin: "null", host: "holt.test" })), false);
});
