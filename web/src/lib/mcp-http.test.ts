import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { MAX_BODY_BYTES, handleMcpPost } from "./mcp-http.ts";
import { mcpServer } from "./mcp-server.ts";
import type { McpDeps } from "./mcp.ts";

/** A server whose every report is missing and whose checks only count themselves. */
function harness() {
  const seen = { built: 0, started: [] as string[] };
  const deps: McpDeps = {
    siteUrl: "https://githolt.com",
    now: () => Date.parse("2026-11-09T00:00:00Z"),
    sleep: async () => {},
    getReport: async () => ({ ok: false, status: 404, error: { code: "not_found", message: "no" } }),
    startAnalysis: async (repo) => {
      seen.started.push(repo);
      return { ok: false, status: 429, error: { code: "rate_limited", message: "no" } };
    },
    jobStatus: async () => ({ ok: false, status: 404, error: { code: "not_found", message: "no" } }),
    starterIssues: async () => ({ ok: false, status: 404, error: { code: "not_found", message: "no" } }),
  };
  return {
    seen,
    make: () => {
      seen.built++;
      return mcpServer(deps);
    },
  };
}

const call = (id: number, repo: string) => ({ jsonrpc: "2.0", id, method: "tools/call", params: { name: "check_repo", arguments: { repo } } });

function post(body: string | ReadableStream<Uint8Array>, headers: Record<string, string> = {}) {
  return new Request("https://githolt.com/mcp", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json", Accept: "application/json, text/event-stream", ...headers },
    ...(typeof body === "string" ? {} : { duplex: "half" }),
  } as RequestInit);
}

test("one JSON-RPC request runs its tool", async () => {
  const h = harness();
  const res = await handleMcpPost(post(JSON.stringify(call(1, "a/b"))), h.make);
  assert.equal(res.status, 200);
  assert.deepEqual(h.seen.started, ["a/b"]);
  const body = await res.json();
  assert.equal(body.result.structuredContent.status, "busy");
  assert.equal(res.headers.get("Cache-Control"), "no-store");
});

test("a batch is refused with a JSON-RPC error, and no tool runs, however it is written", async () => {
  const hundred = Array.from({ length: 100 }, (_, i) => call(i, `a/r${i}`));
  const forms: [string, string][] = [
    ["100 calls", JSON.stringify(hundred)],
    ["one call", JSON.stringify([call(1, "a/b")])],
    ["empty", "[]"],
    ["leading whitespace", ` \n\t ${JSON.stringify(hundred)}`],
    ["a byte order mark", `﻿${JSON.stringify(hundred)}`],
    ["escaped keys", JSON.stringify(hundred).replaceAll('"jsonrpc"', '"\\u006asonrpc"')],
    ["nested", JSON.stringify([hundred])],
  ];
  for (const [name, body] of forms) {
    const h = harness();
    const res = await handleMcpPost(post(body), h.make);
    assert.equal(res.status, 400, name);
    const out = await res.json();
    assert.equal(out.error.code, -32600, name);
    assert.deepEqual(h.seen.started, [], name);
    assert.equal(h.seen.built, 0, `${name}: nothing was even built`);
  }
});

test("anything else that isn't one request is refused before a server is built", async () => {
  for (const [body, code] of [["null", -32600], ["3", -32600], ['"x"', -32600], ["{not json", -32700], ["", -32700]] as const) {
    const h = harness();
    const res = await handleMcpPost(post(body), h.make);
    assert.equal(res.status, 400, body);
    assert.equal((await res.json()).error.code, code, body);
    assert.equal(h.seen.built, 0, body);
  }
});

test("a body over the limit is refused, whether or not it declares its length", async () => {
  const big = JSON.stringify({ ...call(1, "a/b"), pad: "x".repeat(MAX_BODY_BYTES) });
  const declared = harness();
  const a = await handleMcpPost(post(big, { "Content-Length": String(big.length) }), declared.make);
  assert.equal(a.status, 413);
  assert.deepEqual(declared.seen.started, []);

  const chunked = harness();
  const bytes = new TextEncoder().encode(big);
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      for (let i = 0; i < bytes.length; i += 4096) c.enqueue(bytes.slice(i, i + 4096));
      c.close();
    },
  });
  const b = await handleMcpPost(post(stream), chunked.make);
  assert.equal(b.status, 413);
  assert.deepEqual(chunked.seen.started, []);
});

test("no open CORS: a web page can't drive the tools from its visitors' browsers", async () => {
  const h = harness();
  const ok = await handleMcpPost(post(JSON.stringify(call(1, "a/b")), { Origin: "https://evil.example" }), h.make);
  assert.equal(ok.headers.get("Access-Control-Allow-Origin"), null);
  // The one way a page gets past a preflight is a "simple" content type: that runs nothing.
  const page = harness();
  const simple = await handleMcpPost(post(JSON.stringify(call(1, "a/b")), { "Content-Type": "text/plain", Origin: "https://evil.example" }), page.make);
  assert.equal(simple.status, 415);
  assert.deepEqual(page.seen.started, []);
  const route = readFileSync(new URL("../app/mcp/route.ts", import.meta.url), "utf-8");
  assert.doesNotMatch(route, /Access-Control|export (async )?function OPTIONS/);
});
