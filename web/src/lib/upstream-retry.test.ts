import { test } from "node:test";
import assert from "node:assert/strict";
import { droppedConnection, retryDropped } from "./upstream-retry.ts";

function fetchError(code: string): TypeError {
  return new TypeError("fetch failed", { cause: Object.assign(new Error(code), { code }) });
}

test("a dropped connection is sent once more", async () => {
  let calls = 0;
  const res = await retryDropped(async () => {
    calls += 1;
    if (calls === 1) throw fetchError("UND_ERR_SOCKET");
    return new Response("ok");
  });
  assert.equal(calls, 2);
  assert.equal(await res.text(), "ok");
});

test("only once: a second drop is the caller's error", async () => {
  let calls = 0;
  await assert.rejects(retryDropped(async () => {
    calls += 1;
    throw fetchError("ECONNRESET");
  }));
  assert.equal(calls, 2);
});

test("timeouts and other failures are not retried", async () => {
  for (const err of [new DOMException("timed out", "TimeoutError"), fetchError("ENOTFOUND"), new Error("boom")]) {
    let calls = 0;
    await assert.rejects(retryDropped(async () => {
      calls += 1;
      throw err;
    }));
    assert.equal(calls, 1);
  }
});

test("an answer, even an error status, is returned as it is", async () => {
  let calls = 0;
  const res = await retryDropped(async () => {
    calls += 1;
    return new Response("", { status: 503 });
  });
  assert.equal(calls, 1);
  assert.equal(res.status, 503);
});

test("droppedConnection reads undici's cause code", () => {
  assert.equal(droppedConnection(fetchError("ECONNREFUSED")), true);
  assert.equal(droppedConnection(fetchError("ETIMEDOUT")), false);
  assert.equal(droppedConnection(null), false);
});
