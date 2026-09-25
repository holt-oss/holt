import assert from "node:assert/strict";
import { test } from "node:test";
import { clientIpFrom } from "./client-ip.ts";

const env = process.env as Record<string, string | undefined>;
function withEnv(vars: Record<string, string | undefined>, fn: () => void) {
  const saved = Object.fromEntries(Object.keys(vars).map((k) => [k, env[k]]));
  const warn = console.warn;
  console.warn = () => {};
  Object.assign(env, vars);
  try {
    fn();
  } finally {
    for (const [k, v] of Object.entries(saved)) if (v === undefined) delete env[k]; else env[k] = v;
    console.warn = warn;
  }
}

test("behind our proxy: Cloudflare first, then the last forwarded hop", () => {
  withEnv({ TRUST_PROXY_HEADERS: "1" }, () => {
    assert.equal(clientIpFrom(new Headers({ "cf-connecting-ip": "1.1.1.1", "x-forwarded-for": "2.2.2.2" })), "1.1.1.1");
    assert.equal(clientIpFrom(new Headers({ "x-forwarded-for": "6.6.6.6, 3.3.3.3" })), "3.3.3.3");
    assert.equal(clientIpFrom(new Headers({ "x-real-ip": "4.4.4.4" })), "4.4.4.4");
  });
});

test("ignores spoofable headers unless TRUST_PROXY_HEADERS=1", () => {
  withEnv({ TRUST_PROXY_HEADERS: undefined, NODE_ENV: "production" }, () => {
    assert.equal(clientIpFrom(new Headers({ "cf-connecting-ip": "1.1.1.1", "x-forwarded-for": "2.2.2.2" })), null);
  });
  withEnv({ TRUST_PROXY_HEADERS: undefined, NODE_ENV: "development" }, () => {
    assert.equal(clientIpFrom(new Headers({ "x-forwarded-for": "2.2.2.2" })), "127.0.0.1");
  });
});

test("no fallback address in production", () => {
  withEnv({ TRUST_PROXY_HEADERS: "1", NODE_ENV: "production" }, () => {
    assert.equal(clientIpFrom(new Headers()), null);
  });
});
