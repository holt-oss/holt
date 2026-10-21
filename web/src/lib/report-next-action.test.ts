import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { findHref, findLabel, issuesBehindControl, nextAction, pickAlternatives } from "../components/report/next-action.ts";
import type { Verdict } from "./types.ts";

const VERDICTS: Verdict[] = ["viable", "long_shot", "not_viable", "insufficient_evidence", "personal", "catalogue"];

test("each verdict has its next action: start here, go elsewhere, or one link to Find", () => {
  assert.deepEqual(VERDICTS.map(nextAction), ["start", "alternatives", "alternatives", "find", "find", "find"]);
});

test("only a report that says start here shows its starter issues in the open", () => {
  assert.deepEqual(VERDICTS.filter(issuesBehindControl), ["long_shot", "catalogue"]);
  for (const v of VERDICTS) assert.ok(!(nextAction(v) === "start" && issuesBehindControl(v)), v);
});

test("alternatives are repos worth your time, never the one being read, at most three", () => {
  const board = [
    { repo: "Pallets/Flask", verdict: "viable" as const },
    { repo: "a/long", verdict: "long_shot" as const },
    { repo: "b/one", verdict: "viable" as const },
    { repo: "c/two", verdict: "viable" as const },
    { repo: "d/three", verdict: "viable" as const },
    { repo: "e/four", verdict: "viable" as const },
  ];
  assert.deepEqual(pickAlternatives(board, "pallets/flask").map((r) => r.repo), ["b/one", "c/two", "d/three"]);
  assert.deepEqual(pickAlternatives([], "a/b"), []);
});

test("Find is searched by the repo's language when it has one", () => {
  assert.equal(findHref("Python"), "/find?lang=python");
  assert.equal(findHref("C++"), "/find?lang=c%2B%2B");
  assert.equal(findHref(null), "/find");
  assert.equal(findHref("  "), "/find");
});

test("the link to Find says where it goes, under every verdict that shows it", () => {
  assert.equal(findLabel("insufficient_evidence", "Go"), "Find a Go project with a track record");
  assert.equal(findLabel("personal", null), "Find a project that merges outsiders");
  assert.equal(findLabel("catalogue", undefined), "Find a project to write code for");
});

test("on the report, the next action comes before the numbers, the README and the badge", () => {
  const view = readFileSync(new URL("../components/report/report-view.tsx", import.meta.url), "utf-8");
  const body = view.slice(view.indexOf("export function ReportView"));
  const at = (s: string) => {
    const i = body.indexOf(s);
    assert.ok(i >= 0, s);
    return i;
  };
  const next = at("action === \"start\"");
  assert.ok(at("<VerdictHero") < next);
  for (const later of ["<ShareMenu", "data-still-here", "<StatsGrid", "<ReadmeSection", "<UpgradeCard", "<BadgeSnippet"]) assert.ok(next < at(later), later);
});
