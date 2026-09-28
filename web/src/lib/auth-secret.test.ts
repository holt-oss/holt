import assert from "node:assert/strict";
import { test } from "node:test";
import { authSecret } from "./auth-secret.ts";

test("a set AUTH_SECRET is used everywhere", () => {
  assert.equal(authSecret({ AUTH_SECRET: "s3cret", NODE_ENV: "production" }), "s3cret");
  assert.equal(authSecret({ AUTH_SECRET: "s3cret", NODE_ENV: "development" }), "s3cret");
});

test("development treats an empty AUTH_SECRET as missing and falls back", () => {
  assert.equal(authSecret({ AUTH_SECRET: "", NODE_ENV: "development" }), "holt-dev-only-secret");
  assert.equal(authSecret({ NODE_ENV: "development" }), "holt-dev-only-secret");
});

test("production never gets the dev fallback, so Auth.js still refuses to start", () => {
  assert.equal(authSecret({ AUTH_SECRET: "", NODE_ENV: "production" }), undefined);
  assert.equal(authSecret({ NODE_ENV: "production" }), undefined);
  assert.equal(authSecret({ AUTH_SECRET: "", NODE_ENV: "test" }), undefined);
});
