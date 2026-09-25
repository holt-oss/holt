import assert from "node:assert/strict";
import { test } from "node:test";
import { odds, statLines, verdictLine } from "./format.ts";

const stats = (attempts: number, merged: number, noReply: number) => ({
  outsider_attempts: attempts, outsider_merged: merged, no_reply: noReply,
  distinct_outsiders: attempts, first_time_merged_authors: merged, median_first_response_hours: 5, bot_share: 0,
});
const viable = (a: number, m: number, n: number) => verdictLine({ verdict: "viable", stats: stats(a, m, n) });

test("flask-like numbers: honest about long odds", () => {
  const line = viable(189, 5, 100);
  assert.match(line, /5 of 189/);
  assert.match(line, /most pull requests don't land/);
  assert.match(line, /about half get no reply/);
  assert.match(line, /starter issues/);
  assert.doesNotMatch(line, /real replies/);
  assert.equal(odds(stats(189, 5, 100)), "long");
});

test("strong numbers: upbeat, and claims replies", () => {
  const line = viable(100, 40, 10);
  assert.match(line, /real replies/);
  assert.match(line, /40 of 100/);
  assert.equal(odds(stats(100, 40, 10)), "good");
});

test("borderlines", () => {
  // exactly 10% merged and 40% silent is not "weak", but 40% silent may not claim replies
  assert.doesNotMatch(viable(100, 10, 40), /don't land|no reply|real replies/);
  assert.match(viable(100, 10, 40), /10 of 100 of their recent pull requests landed/);
  assert.match(viable(100, 9, 10), /most pull requests don't land/);
  assert.doesNotMatch(viable(100, 9, 10), /no reply/);
  assert.match(viable(100, 30, 41), /about 41% get no reply/);
  assert.doesNotMatch(viable(100, 30, 41), /don't land/);
  assert.match(viable(100, 30, 29), /real replies/);
  assert.doesNotMatch(viable(100, 30, 30), /real replies/);
  assert.equal(odds(stats(100, 10, 40)), "fair");
  assert.equal(odds({ outsider_attempts: 0, outsider_merged: 0, no_reply: 0 }), null);
});

test("odds agree with the stat tiles' tones", () => {
  for (const [a, m, n] of [[189, 5, 100], [100, 40, 10], [100, 10, 40], [100, 12, 25], [100, 4, 5], [100, 20, 51]]) {
    const tones = statLines(stats(a, m, n)).filter((l) => l.key === "merged" || l.key === "noreply").map((l) => l.tone);
    const expect = tones.includes("bad") ? "long" : tones.includes("warn") ? "fair" : "good";
    assert.equal(odds(stats(a, m, n)), expect, `${a}/${m}/${n}`);
  }
});
