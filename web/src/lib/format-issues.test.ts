import assert from "node:assert/strict";
import { test } from "node:test";
import { issueSkill, issueTaken, nextStep } from "./format.ts";

const starter = (people: number | null, open_prs: number | null, comments = 0) => ({
  number: 1, title: "t", url: "u", labels: [], created_at: null, comments, why: [],
  people, open_prs, on_it: null, beginner: true, areas: [],
});

test("the next step for an issue someone is already on", () => {
  assert.equal(nextStep(starter(1, 1)), "Look at the open pull request first; if it has stalled, ask to take over.");
  assert.equal(nextStep(starter(2, 0, 4)), "Ask whether it's still free before you start.");
  assert.equal(nextStep(starter(0, 0)), "Comment on the issue to ask if you can take it.");
  assert.equal(nextStep(starter(null, null)), "Comment on the issue to ask if you can take it.");
});

test("taken: anyone on it, or an open pull request", () => {
  assert.equal(issueTaken(starter(0, 0)), false);
  assert.equal(issueTaken(starter(null, null)), false);
  assert.equal(issueTaken(starter(1, 0)), true);
  assert.equal(issueTaken(starter(0, 1)), true);
});

test("the skill an issue asks for comes from its own labels, or its kind of work", () => {
  const skill = (labels: string[], areas: string[] = ["code"]) => issueSkill({ labels, areas } as never);
  assert.equal(skill(["help wanted", "python", "hacktoberfest"]), "Python");
  assert.equal(skill(["good first issue", "lang: Rust"]), "Rust");
  assert.equal(skill(["area/js"]), "JavaScript");
  assert.equal(skill(["good first issue"], ["docs"]), "Docs");
  assert.equal(skill(["good first issue"], ["code", "tests"]), null);
  // Nothing is guessed: "C" alone, or a label that only contains a language's name.
  assert.equal(skill(["priority: c", "good to go"]), null);
  assert.equal(skill([], []), null);
});
