import assert from "node:assert/strict";
import { test } from "node:test";
import { parseRepoInput, redirectTargetForPath } from "./repo.ts";

test("parses the forms people paste", () => {
  const want = { owner: "pallets", repo: "flask" };
  for (const input of [
    "pallets/flask",
    " pallets/flask ",
    "https://github.com/pallets/flask",
    "http://github.com/pallets/flask/",
    "github.com/pallets/flask.git",
    "www.github.com/pallets/flask",
    "https://github.com/pallets/flask/tree/main/src",
    "https://github.com/pallets/flask?tab=readme-ov-file",
    "git@github.com:pallets/flask.git",
  ]) {
    assert.deepEqual(parseRepoInput(input), want, input);
  }
});

test("rejects things that are not repos", () => {
  for (const input of ["", "flask", "https://github.com/pallets", "a b/c", "-bad/repo", "o/.."]) {
    assert.equal(parseRepoInput(input), null, input);
  }
});

test("URL trick redirects", () => {
  assert.equal(redirectTargetForPath("/https://github.com/pallets/flask"), "/pallets/flask");
  assert.equal(redirectTargetForPath("/https:/github.com/pallets/flask"), "/pallets/flask");
  assert.equal(redirectTargetForPath("/github.com/pallets/flask"), "/pallets/flask");
  assert.equal(redirectTargetForPath("/github.com/pallets/flask/pulls"), "/pallets/flask");
  assert.equal(redirectTargetForPath("/pallets/flask/tree/main/src"), "/pallets/flask");
  assert.equal(redirectTargetForPath("/pallets/flask.git"), "/pallets/flask");
  assert.equal(redirectTargetForPath("/github.com/pallets"), "/");
});

test("leaves app routes alone", () => {
  for (const p of ["/", "/find", "/pallets/flask", "/me/history", "/api/analyses", "/pallets/flask/opengraph-image"]) {
    assert.equal(redirectTargetForPath(p), null, p);
  }
});
