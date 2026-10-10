import assert from "node:assert/strict";
import { test } from "node:test";
import { days, describe, fromForm, langName, personalise, topics } from "./profile.ts";
import type { FindResult, StarterIssue } from "./types.ts";

const issue = (number: number, beginner: boolean, areas: StarterIssue["areas"], people = 0): StarterIssue => ({
  number, title: `#${number}`, url: `https://github.com/o/r/issues/${number}`, labels: [], created_at: null, comments: 0, why: [], beginner, areas,
  people, open_prs: 0, on_it: null,
});
const repo = (name: string, issues: StarterIssue[]): FindResult => ({
  repo: name, headline: "Worth your time", tone: "good", verdict: "viable", description: null, language: null, languages: [], stars: null, open_issues: null, pull_requests: null, open_pull_requests: null, contributors: null, stats: {}, issues,
});

const results = [
  repo("a/code", [issue(1, false, ["code"]), issue(2, true, ["code"])]),
  repo("b/help", [issue(3, false, ["docs"])]),
  repo("c/docs", [issue(4, true, ["code"]), issue(5, true, ["docs"])]),
];

test("no profile leaves results alone", () => {
  assert.equal(personalise(results, null), results);
});

test("a newcomer sees only first-timer issues; repos left empty drop out", () => {
  const got = personalise(results, { level: "newcomer", contributions: [] });
  assert.deepEqual(got.map((r) => [r.repo, r.issues.map((i) => i.number)]), [["a/code", [2]], ["c/docs", [4, 5]]]);
});

test("experienced keeps every issue", () => {
  const got = personalise(results, { level: "experienced", contributions: [] });
  assert.deepEqual(got.map((r) => r.issues.length), [2, 1, 2]);
});

test("matching contribution types come first, issues and then repos", () => {
  const got = personalise(results, { level: "experienced", contributions: ["docs"] });
  assert.deepEqual(got.map((r) => [r.repo, r.issues.map((i) => i.number)]), [
    ["b/help", [3]], ["c/docs", [5, 4]], ["a/code", [1, 2]],
  ]);
});

test("an issue somebody is on stays behind free ones, even when it fits", () => {
  const got = personalise([repo("d/busy", [issue(6, true, ["docs"], 2), issue(7, true, ["code"])])], { level: "experienced", contributions: ["docs"] });
  assert.deepEqual(got[0].issues.map((i) => i.number), [7, 6]);
});

test("issues cached before the flags existed still show", () => {
  const old = [repo("x/y", [{ ...issue(9, true, ["code"]), beginner: undefined as unknown as boolean, areas: undefined as unknown as StarterIssue["areas"] }])];
  assert.equal(personalise(old, { level: "newcomer", contributions: ["docs"] })[0].issues.length, 1);
});

test("reading the form", () => {
  const f = new FormData();
  for (const l of ["python", "Rust", "python"]) f.append("lang", l);
  f.set("topics", "Web framework, cli, c++");
  f.set("days", "3");
  for (const t of ["docs", "marketing", "tests"]) f.append("type", t);
  f.set("level", "experienced");
  assert.deepEqual(fromForm(f), {
    languages: ["python", "rust"], topics: ["web-framework", "cli"], days: 3,
    contributions: ["docs", "tests"], level: "experienced", adult_confirmed: false,
  });
  const empty = fromForm(new FormData());
  assert.equal(empty.level, "newcomer");
  assert.equal(empty.days, 7);
});

test("days and topics fall back safely", () => {
  assert.equal(days("5"), 7);
  assert.equal(days("30"), 30);
  assert.deepEqual(topics(" , !!, machine learning"), ["machine-learning"]);
});

test("describe reads as plain English", () => {
  assert.equal(describe({ languages: ["python", "c++"], days: 3, level: "newcomer", contributions: ["docs"] }),
    "Python, C++ · replies within a weekend · first-timer issues only, docs first");
  assert.equal(describe({ languages: [], days: 7, level: "experienced", contributions: [] }), "any language · replies within a week · all starter issues");
});

test("a typed-in language shows with GitHub's spelling, else a leading capital", () => {
  assert.equal(langName("c#"), "C#");
  assert.equal(langName("objective-c"), "Objective-C");
  assert.equal(langName("python"), "Python");
  assert.equal(langName("mojo"), "Mojo");
});
