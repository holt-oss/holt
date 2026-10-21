import assert from "node:assert/strict";
import { test } from "node:test";
import { ABOUT_ROWS, aboutCells, anyLead, bareNames, cells, compareHref, compareTitle, contenders, leaders, MAX, parseList, pickRepo, ROWS, savedToAdd, SUGGESTIONS } from "./compare.ts";
import { humanHours } from "./format.ts";
import type { Stats, Verdict } from "./types.ts";

const st = (over: Partial<Stats> = {}): Stats => ({ outsider_attempts: 10, outsider_merged: 5, distinct_outsiders: 8, first_time_merged_authors: 2, no_reply: 1, median_first_response_hours: 10, bot_share: 0, still_open: 0, closed_silently: 0, closed_by_bot: 0, withdrawn: 0, too_old: 0, timing: null, ...over });

test("parseList takes names and URLs, split by commas or spaces, without duplicates", () => {
  assert.deepEqual(parseList("pallets/flask https://github.com/psf/requests, Pallets/Flask"), ["pallets/flask", "psf/requests"]);
  assert.deepEqual(parseList(["a/b,c/d", "e/f g/h i/j"]), ["a/b", "c/d", "e/f", "g/h"]);
  assert.deepEqual(parseList(undefined), []);
  assert.deepEqual(parseList("not a repo"), []);
});

test("past the limit, the first four are compared and the rest can be named as left out", () => {
  const asked = parseList("a/b,c/d,e/f,g/h,i/j,A/B,k/l", 12);
  assert.deepEqual(asked.slice(0, MAX), parseList("a/b,c/d,e/f,g/h,i/j,A/B,k/l"));
  assert.deepEqual(asked.slice(MAX), ["i/j", "k/l"]);
});

test("the best mark's key shows only when a number is marked", () => {
  // One contender: nothing to be best among.
  assert.equal(anyLead(leaders([st(), null])), false);
  assert.equal(anyLead(leaders([st(), st()])), false);
  assert.equal(anyLead(leaders([st(), st({ outsider_merged: 8 })])), true);
});

test("compareHref", () => {
  assert.equal(compareHref([]), "/compare");
  assert.equal(compareHref(["a/b", "c/d"]), "/compare?repos=a/b,c/d");
});

test("removing the last repo ends on the empty page, and each suggestion there loads a full comparison", () => {
  const list = ["a/b"];
  assert.equal(compareHref(list.filter((r) => r !== "a/b")), "/compare");
  for (const s of SUGGESTIONS) {
    assert.ok(s.repos.length >= 2 && s.repos.length <= MAX, s.label);
    // The link reads back as the same list: nothing dropped or renamed on the way in.
    assert.deepEqual(parseList(compareHref(s.repos).split("repos=")[1]), s.repos);
  }
});

test("leaders mark the best column on each number, ties included", () => {
  const l = leaders([st({ outsider_merged: 8 }), st({ median_first_response_hours: 2, first_time_merged_authors: 9 }), null, st({ no_reply: 0, outsider_merged: 8 })]);
  assert.deepEqual(l, { merged: [0, 3], reply: [1], firstTimers: [1], silent: [3], closed: [] });
});

test("no leader with one column, equal numbers or missing ones", () => {
  assert.deepEqual(leaders([st()]), { merged: [], reply: [], firstTimers: [], silent: [], closed: [] });
  assert.deepEqual(leaders([st(), st()]).merged, []);
  assert.deepEqual(leaders([st({ median_first_response_hours: null }), st()]).reply, []);
  assert.deepEqual(leaders([st({ outsider_attempts: 0 }), st()]).merged, []);
});

const col = (repo: string, verdict: Verdict, over: Partial<Stats> = {}) => ({ repo, verdict, stats: st(over) });
const ASK = "Which one will review your pull request?";

test("compareTitle goes by verdict first; the merge rate only breaks a tie", () => {
  // A higher merge rate doesn't beat a better verdict.
  assert.equal(compareTitle([col("a/b", "long_shot", { outsider_merged: 9 }), col("c/d", "viable", { outsider_merged: 3 })]), "c/d is the one worth your time.");
  assert.equal(compareTitle([col("a/b", "viable", { outsider_merged: 8 }), col("c/d", "viable")]), "Both are worth your time; a/b merges outsiders most often.");
  assert.equal(compareTitle([col("a/b", "viable"), col("c/d", "viable"), col("e/f", "viable")]), "All 3 are worth your time.");
  assert.equal(compareTitle([col("a/b", "viable"), col("c/d", "viable", { outsider_merged: 7 }), col("e/f", "not_viable", { outsider_merged: 9 })]), "2 of these are worth your time; c/d merges outsiders most often.");
  // django vs flask: the long shot is the best of them, and the title says it's still a long shot.
  assert.equal(compareTitle([col("pallets/flask", "not_viable", { outsider_merged: 1 }), col("django/django", "long_shot")]), "django/django is your best shot here, but still a long shot.");
  assert.equal(compareTitle([col("a/b", "long_shot", { outsider_merged: 1 }), col("c/d", "long_shot")]), "No sure bets here; c/d is the best of the long shots.");
  assert.equal(compareTitle([col("a/b", "long_shot"), col("c/d", "long_shot")]), "No sure bets here, only long shots.");
  assert.equal(compareTitle([col("a/b", "not_viable"), col("c/d", "insufficient_evidence")]), "None of these looks like a good bet right now.");
});

test("compareTitle keeps the question for an empty page, a single repo, or one not checked yet", () => {
  const two = [col("a/b", "viable"), col("c/d", "long_shot")];
  assert.equal(compareTitle([]), ASK);
  assert.equal(compareTitle([col("a/b", "viable")]), ASK);
  assert.equal(compareTitle([...two, null]), ASK);
});

test("only repos worth trying or long shots can lead a row", () => {
  const cols = [col("a/b", "not_viable", { median_first_response_hours: 1 }), col("c/d", "long_shot", { median_first_response_hours: 48 }), col("e/f", "viable", { median_first_response_hours: 20 }), null];
  const s = contenders(cols);
  assert.deepEqual(s.map((x) => x != null), [false, true, true, false]);
  // The not-worth repo's one-hour reply gets no mark; the viable repo's 20 hours does.
  assert.deepEqual(leaders(s).reply, [2]);
  // A lone contender has nobody to beat, so nothing is marked.
  assert.deepEqual(leaders(contenders([col("a/b", "personal", { outsider_merged: 9 }), col("c/d", "viable")])).merged, []);
});

test("savedToAdd offers saved repos not in the list, and none once it's full", () => {
  assert.deepEqual(savedToAdd(["a/b", "C/D", "e/f"], ["c/d"]), ["a/b", "e/f"]);
  assert.deepEqual(savedToAdd(["a/1", "a/2", "a/3"], [], 2), ["a/1", "a/2"]);
  assert.deepEqual(savedToAdd(["z/z"], ["a/1", "a/2", "a/3", "a/4"]), []);
});

test("fewest closed without a word leads", () => {
  assert.deepEqual(leaders([st({ closed_silently: 1 }), st({ closed_silently: 4 })]).closed, [0]);
});

test("cells: a share to scan with what it's out of, and plain words where there's no number", () => {
  const c = cells({ stats: st({ outsider_merged: 8, outsider_attempts: 20, median_first_response_hours: 30 }), landing: [{ path: "docs" } as never] });
  assert.deepEqual(c.merged, { main: "40%", sub: "8 of 20" });
  assert.equal(c.reply.main, humanHours(30));
  assert.equal(c.way.main, "docs/");
  assert.equal(cells({ stats: st(), landing: [{ path: "(root)" } as never] }).way.main, "(root)");
  const quiet = cells({ stats: st({ median_first_response_hours: null, first_time_merged_authors: 0 }), landing: [] });
  assert.deepEqual(quiet.reply, { main: "no replies", tone: "bad" });
  assert.equal(quiet.firstTimers.tone, "bad");
  assert.deepEqual(quiet.way, { main: "none yet", tone: "none" });
  const empty = cells({ stats: st({ outsider_attempts: 0, outsider_merged: 0, median_first_response_hours: null }), landing: [] });
  assert.equal(empty.merged.tone, "none");
  assert.equal(empty.silent.main, "–");
  assert.equal(empty.reply.tone, "none");
});

test("every row has a cell", () => {
  const c = cells({ stats: st(), landing: [] });
  for (const r of ROWS) assert.ok(c[r.id], r.id);
});

test("aboutCells: stars lead, counts are compact, and archived shows where the last push goes", () => {
  const now = Date.parse("2026-09-30T00:00:00Z");
  const about = {
    stars: 68400, forks: 16300, open_issues: 12, pushed_at: "2026-09-28T00:00:00Z", archived: false,
    languages: [{ name: "Python", share: 0.62 }, { name: "HTML", share: 0.2 }],
  } as never;
  const c = aboutCells(about, now);
  assert.equal(c.stars.main, "68k");
  assert.equal(c.forks.main, "16k");
  assert.equal(c.issues.main, "12");
  assert.equal(c.pushed.main, "2 days ago");
  assert.deepEqual(c.language, { main: "Python", sub: "62%", lang: "Python" });
  const old = aboutCells({ ...(about as object), archived: true, forks: null, languages: [] } as never, now);
  assert.deepEqual(old.pushed, { main: "archived", tone: "bad" });
  assert.equal(old.forks.tone, "none");
  assert.equal(old.language.main, "–");
  for (const r of ABOUT_ROWS) assert.equal(aboutCells(null, now)[r.id].main, "–", r.id);
});

test("bareNames: a word with no owner is a name to look up; repos and links are not", () => {
  assert.deepEqual(bareNames("excalidraw"), ["excalidraw"]);
  assert.deepEqual(bareNames("  Excalidraw, vscode  tailwindcss "), ["excalidraw", "vscode", "tailwindcss"]);
  assert.deepEqual(bareNames("pallets/flask https://github.com/psf/requests"), []);
  assert.deepEqual(bareNames("psf/requests excalidraw"), ["excalidraw"]);
  assert.deepEqual(bareNames("excalidraw EXCALIDRAW excalidraw"), ["excalidraw"]);
  assert.deepEqual(bareNames(["a", "b,c"]), ["a", "b", "c"]);
  assert.deepEqual(bareNames(undefined), []);
});

test("bareNames: odd text is not a name", () => {
  assert.deepEqual(bareNames("!!! ??? <script> a;b x:y"), []);
  assert.deepEqual(bareNames(".hidden -dash"), []);
  assert.deepEqual(bareNames("a".repeat(61)), []);
  assert.deepEqual(bareNames("github.com/psf"), []);
});

test("pickRepo: the exact name wins over a more starred near match, else the top result", () => {
  const hits = [{ repo: "someone/excalidraw-tools" }, { repo: "excalidraw/excalidraw" }, { repo: "fork/Excalidraw" }];
  assert.equal(pickRepo("excalidraw", hits), "excalidraw/excalidraw");
  assert.equal(pickRepo("excali", hits), "someone/excalidraw-tools");
  assert.equal(pickRepo("excalidraw", []), null);
});
