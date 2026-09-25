// Drives the real page controller against fixtures/github-repo.html with canned
// answers, so the chip can be screenshotted without GitHub or a Holt server.
// Build: npm run fixture. Open fixtures/github-repo.html (?state=missing|not_viable|insufficient_evidence).
import { createPageController, type LookupFn } from "../src/page";

const state = new URLSearchParams(location.search).get("state") ?? "viable";

const lookup = ((kind) => {
  if (kind === "starter-issues") {
    return Promise.resolve({
      state: "found",
      data: {
        repo: "pallets/flask",
        issues: [
          { number: 5612, why: ["Labelled good first issue", "Touches docs/, where 8 of 10 outsider PRs were merged"] },
          { number: 5598, why: ["Labelled good first issue"] },
        ],
      },
    });
  }
  if (state === "missing") return Promise.resolve({ state: "missing" });
  return Promise.resolve({
    state: "found",
    data: {
      repo: "pallets/flask",
      verdict: state,
      stats: { outsider_attempts: 100, outsider_merged: 15 },
    },
  });
}) as LookupFn;

void createPageController(document, lookup).sync("/pallets/flask/issues");
