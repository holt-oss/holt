import assert from "node:assert/strict";
import { test } from "node:test";
import { FindCache, findKey } from "./find-cache.ts";
import type { FindQuery, FindStart, Result } from "./types.ts";

const q = (over: Partial<FindQuery> = {}): FindQuery => ({ languages: ["python"], topics: [], days: 7, hacktoberfest: true, limit: 12, ...over });
const done = (repo: string): Result<FindStart> => ({ ok: true, data: { status: "done", results: [{ repo, headline: "Worth your time", verdict: "viable", stats: {}, issues: [] }] } });
const queued = (id: string): Result<FindStart> => ({ ok: true, data: { status: "queued", job_id: id } });

function counter(make: (n: number) => Result<FindStart>) {
  let calls = 0;
  const fetch = async () => {
    calls++;
    await new Promise((r) => setTimeout(r, 5));
    return make(calls);
  };
  return { fetch, calls: () => calls };
}

test("keys ignore language order and case", () => {
  assert.equal(findKey(q({ languages: ["TypeScript", "javascript"] })), findKey(q({ languages: ["javascript", "typescript"] })));
  assert.notEqual(findKey(q()), findKey(q({ hacktoberfest: false })));
  assert.notEqual(findKey(q()), findKey(q({ days: 1 })));
});

test("concurrent misses share one upstream call; hits are free", async () => {
  const cache = new FindCache();
  const c = counter(() => done("a/b"));
  const rs = await Promise.all([cache.get(q(), c.fetch), cache.get(q(), c.fetch), cache.get(q(), c.fetch)]);
  assert.equal(c.calls(), 1);
  assert.ok(rs.every((r) => r.ok && r.data.status === "done"));
  await cache.get(q(), c.fetch);
  assert.equal(c.calls(), 1);
});

test("a queued job is shared, then its results are served", async () => {
  const cache = new FindCache();
  const c = counter((n) => queued(`find_${n}`));
  const a = await cache.get(q(), c.fetch);
  const b = await cache.get(q(), c.fetch);
  assert.deepEqual(a, b);
  assert.equal(c.calls(), 1);
  cache.resolveJob("find_1", [{ repo: "x/y", headline: "Worth your time", verdict: "viable", stats: {}, issues: [] }]);
  const r = await cache.get(q(), c.fetch);
  assert.ok(r.ok && r.data.status === "done" && r.data.results[0].repo === "x/y");
  assert.equal(c.calls(), 1);
});

test("a failed job is forgotten; errors are not cached", async () => {
  const cache = new FindCache();
  const c = counter((n) => (n === 2 ? { ok: false, status: 429, error: { code: "rate_limited", message: "slow down" } } : queued(`find_${n}`)));
  await cache.get(q(), c.fetch);
  cache.failJob("find_1");
  const r2 = await cache.get(q(), c.fetch);
  assert.equal(r2.ok, false);
  await cache.get(q(), c.fetch);
  assert.equal(c.calls(), 3);
});

test("entries expire after the window", async () => {
  let t = 0;
  const cache = new FindCache(10 * 60_000, () => t);
  const c = counter(() => done("a/b"));
  await cache.get(q(), c.fetch);
  t += 9 * 60_000;
  await cache.get(q(), c.fetch);
  assert.equal(c.calls(), 1);
  t += 2 * 60_000;
  await cache.get(q(), c.fetch);
  assert.equal(c.calls(), 2);
});
