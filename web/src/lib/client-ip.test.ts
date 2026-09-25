import assert from "node:assert/strict";
import { test } from "node:test";
import { clientIpFrom } from "./client-ip.ts";

test("prefers Cloudflare, then the first forwarded address", () => {
  assert.equal(clientIpFrom(new Headers({ "cf-connecting-ip": "1.1.1.1", "x-forwarded-for": "2.2.2.2" })), "1.1.1.1");
  assert.equal(clientIpFrom(new Headers({ "x-forwarded-for": "3.3.3.3, 10.0.0.1" })), "3.3.3.3");
  assert.equal(clientIpFrom(new Headers({ "x-real-ip": "4.4.4.4" })), "4.4.4.4");
});

test("falls back only outside production", () => {
  const env = process.env.NODE_ENV;
  const warn = console.warn;
  console.warn = () => {};
  try {
    (process.env as Record<string, string>).NODE_ENV = "development";
    assert.equal(clientIpFrom(new Headers()), "127.0.0.1");
    (process.env as Record<string, string>).NODE_ENV = "production";
    assert.equal(clientIpFrom(new Headers()), null);
  } finally {
    (process.env as Record<string, string | undefined>).NODE_ENV = env;
    console.warn = warn;
  }
});
