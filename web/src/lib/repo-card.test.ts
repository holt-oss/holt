import assert from "node:assert/strict";
import { test } from "node:test";
import { fromDiscover, fromFind, fromPick, issueSummary, langColor, languageLabel, neighbours, oddsSegments, oddsText, statPills, type CardStats } from "./repo-card.ts";
import type { DiscoverRepo, Recommendation } from "./types.ts";

const stats = (over: Partial<CardStats> = {}): CardStats => ({ attempts: 71, merged: 57, noReply: 5, closedSilently: 8, closedOther: 0, stillOpen: 95, firstTimers: 3, replyHours: 46.9, ...over });

test("segments add up to the decided pull requests, then the recent ones", () => {
  const s = oddsSegments(stats())!;
  assert.deepEqual(s.map((x) => [x.key, x.n]), [["merged", 57], ["replied", 1], ["closed", 8], ["silent", 5], ["recent", 95]]);
  assert.equal(s.filter((x) => x.key !== "recent").reduce((a, x) => a + x.n, 0), 71);
});

test("segments never overflow when counts disagree, and empty ones are dropped", () => {
  const s = oddsSegments(stats({ attempts: 10, merged: 9, closedSilently: 5, noReply: 5, stillOpen: 0 }))!;
  assert.deepEqual(s.map((x) => [x.key, x.n]), [["merged", 9], ["closed", 1]]);
  assert.equal(oddsSegments(stats({ attempts: 0 })), null);
  assert.equal(oddsSegments(stats({ merged: null })), null);
});

test("find results (partial stats) still get a bar", () => {
  const s = oddsSegments(stats({ closedSilently: null, stillOpen: null }))!;
  assert.deepEqual(s.map((x) => [x.key, x.n]), [["merged", 57], ["other", 9], ["silent", 5]]);
});

test("the bar in words", () => {
  assert.equal(oddsText(stats()), "Of 71 outside pull requests, 57 merged, 1 got a reply but weren't merged, 8 closed without a word and 5 got no reply. 95 more are too recent to count.");
  assert.equal(oddsText(stats({ attempts: 1, merged: 1, stillOpen: 1 })), "Of 1 outside pull request, 1 merged. 1 more is too recent to count.");
  assert.equal(oddsText(stats({ attempts: 0 })), "No outside pull requests to count yet.");
});

test("stat pills", () => {
  assert.deepEqual(statPills(stats()), ["57 of 71 merged", "replies in 2 days", "3 first-timers merged"]);
  assert.deepEqual(statPills(stats({ replyHours: 30, firstTimers: 1 })), ["57 of 71 merged", "replies in about a day", "1 first-timer merged"]);
  assert.deepEqual(statPills(stats({ attempts: 0, replyHours: null, firstTimers: 0 })), []);
});

test("fromFind keeps what a find result has and leaves the rest empty", () => {
  const c = fromFind({ repo: "o/r", headline: "Worth your time", tone: "good", verdict: "viable", description: null, language: "Go", languages: [], stars: 5, open_issues: null, pull_requests: null, open_pull_requests: null, contributors: null, stats: { outsider_attempts: 4, outsider_merged: 3 }, issues: [] });
  assert.equal(c.stats.attempts, 4);
  assert.equal(c.stats.noReply, null);
  assert.deepEqual(c.why, []);
});

test("language colours and neighbours", () => {
  assert.equal(langColor("TypeScript"), "#3178c6");
  assert.equal(langColor("Brainfuck"), null);
  assert.equal(langColor(null), null);
  assert.deepEqual(neighbours(["a/b", "c/d", "e/f"], "C/D"), { index: 1, prev: "a/b", next: "e/f" });
  assert.deepEqual(neighbours(["a/b"], "a/b"), { index: 0, prev: null, next: null });
  assert.equal(neighbours(["a/b"], "x/y"), null);
  assert.equal(neighbours(["a/b"], null), null);
});

test("a card names a second language when the server gives one", () => {
  assert.equal(languageLabel("Go", ["Go", "TypeScript"]), "Go · TypeScript");
  assert.equal(languageLabel("Python", ["Python"]), "Python");
  assert.equal(languageLabel("Python", undefined), "Python");
  assert.equal(languageLabel(null, []), null);
});

// Engine 6, django's shape: most unmerged outside PRs closed by a bot's check.
// They are neither "closed without a word" nor "got a reply".
test("closes by a bot or the author get their own segment, not the replied one", () => {
  const segs = oddsSegments(stats({ attempts: 100, merged: 10, noReply: 20, closedSilently: 5, closedOther: 50, stillOpen: 0 }))!;
  assert.deepEqual(segs.map((x) => [x.key, x.n]), [["merged", 10], ["replied", 15], ["closed", 5], ["shut", 50], ["silent", 20]]);
  assert.match(oddsText(stats({ attempts: 10, merged: 5, noReply: 0, closedSilently: 0, closedOther: 5, stillOpen: 0 })), /5 closed by a bot or their author/);
});

test("issue summary: how many, how many nobody is on, and the kinds of work", () => {
  const issue = (over: Record<string, unknown>) => ({ number: 1, title: "t", url: "u", labels: [], comments: 0, created_at: null, people: 0, open_prs: 0, on_it: null, why: [], beginner: true, areas: [], ...over }) as never;
  assert.equal(issueSummary([]), null);
  assert.deepEqual(issueSummary([issue({ areas: ["docs"] }), issue({ people: 1, areas: ["code", "docs"] }), issue({ open_prs: 1 })]), { count: "3 starter issues", free: "1 unclaimed", allTaken: false, areas: ["code", "docs"] });
  assert.deepEqual(issueSummary([issue({})]), { count: "1 starter issue", free: "unclaimed", allTaken: false, areas: [] });
  assert.equal(issueSummary([issue({}), issue({})])!.free, "all unclaimed");
  assert.deepEqual(issueSummary([issue({ people: 2 }), issue({ open_prs: 1 })])!.free, "all taken");
  assert.equal(issueSummary([issue({ people: null, open_prs: null })])!.free, "unclaimed");
});

test("a card's last line is what the repo does best on its board, when the server says", () => {
  const stats = { outsider_attempts: 20, outsider_merged: 8, distinct_outsiders: 15, first_time_merged_authors: 6, no_reply: 2, median_first_response_hours: 3, bot_share: 0.1, still_open: 0, closed_silently: 0, closed_by_bot: 0, withdrawn: 0, too_old: 0, timing: null };
  const card = { repo: "octo/a", description: null, language: null, languages: [], stars: null, headline: "Worth your time", tone: "good", verdict: "viable", stats, topics: [], issues: [], open_issues: null, pull_requests: null, open_pull_requests: null, contributors: null, reason: "Outside contributors get real replies here, and their work gets merged." };
  const board = { ...card, pushed_at: null, checked_this_week: null, generated_at: null } as unknown as DiscoverRepo;
  assert.equal(fromDiscover({ ...board, standout: "A first reply typically comes within 3 hours." }).reason, "A first reply typically comes within 3 hours.");
  assert.equal(fromDiscover({ ...board, standout: null }).reason, card.reason);
  const pick = { ...card, why: [], numbers_line: "", odds: null, checked_at: null } as unknown as Recommendation;
  assert.equal(fromPick({ ...pick, standout: "Merges typically land within 2 days." }).reason, "Merges typically land within 2 days.");
  assert.equal(fromPick({ ...pick, standout: null }).reason, card.reason);
});
