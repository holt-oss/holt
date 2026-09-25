import assert from "node:assert/strict";
import { test } from "node:test";
import { safeCallback } from "./safe-url.ts";

const stays = (s: string) => {
  const out = safeCallback(s);
  assert.ok(out.startsWith("/") && !out.startsWith("//") && !/[\x00-\x1f\\]/.test(out), `${JSON.stringify(s)} -> ${out}`);
  assert.equal(new URL(out, "https://holt.test").origin, "https://holt.test", JSON.stringify(s));
  return out;
};

test("keeps same-site paths", () => {
  assert.equal(safeCallback("/pallets/flask?mode=ai"), "/pallets/flask?mode=ai");
  assert.equal(safeCallback("/settings#byok"), "/settings#byok");
});

test("rejects off-site and smuggled redirects", () => {
  for (const s of [
    "//evil.com", "/\t/evil.com", "/\n/evil.com", "/\r\n/evil.com", "/\\evil.com", "/\\/evil.com",
    decodeURIComponent("/%09/evil.com"), decodeURIComponent("/%0a/evil.com"),
    "https://evil.com", "evil.com", "javascript:alert(1)", "",
  ]) {
    assert.equal(safeCallback(s), "/", JSON.stringify(s));
  }
  assert.equal(safeCallback(undefined), "/");
  assert.equal(safeCallback(["//evil.com"]), "/");
});

test("encoded slashes stay a same-site path", () => {
  stays("/%2F%2Fevil.com");
  stays("/%09/evil.com");
  stays("/%5Cevil.com");
});
