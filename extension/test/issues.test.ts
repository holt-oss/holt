import { markStarterIssues, removeStarterMarks } from "../src/issues";

const flask = { owner: "pallets", repo: "flask" };

// A React-era issue row (data-testid) and a legacy row (id="issue_N_link"),
// each with the extra links GitHub puts in a row.
const LIST = `
  <div role="list">
    <div role="listitem">
      <a data-testid="issue-pr-title-link" href="/pallets/flask/issues/101">Fix typo in docs</a>
      <a href="/pallets/flask/issues/101#issuecomment-1">3</a>
    </div>
    <div id="issue_102" class="js-issue-row">
      <a id="issue_102_link" class="Link--primary js-navigation-open" href="https://github.com/pallets/flask/issues/102">Add type hints</a>
      <a href="/pallets/flask/issues/102">#102</a>
    </div>
    <div role="listitem">
      <a data-testid="issue-pr-title-link" href="/pallets/flask/issues/103">Rewrite the router</a>
    </div>
    <a href="/pallets/other/issues/101">Same number, other repo</a>
    <a href="/pallets/flask/pull/101">A pull request</a>
  </div>`;

beforeEach(() => {
  document.body.innerHTML = LIST;
});

describe("markStarterIssues", () => {
  it("marks only title links of listed issues in this repo", () => {
    const n = markStarterIssues(document, flask, [
      { number: 101, why: ["Labelled good first issue", "Touches docs/"] },
      { number: 102 },
    ]);
    expect(n).toBe(2);
    const badges = document.querySelectorAll(".holt-starter");
    expect(badges).toHaveLength(2);
    expect(badges[0].previousElementSibling!.textContent).toBe("Fix typo in docs");
    expect(badges[1].previousElementSibling!.textContent).toBe("Add type hints");
    expect((badges[0] as HTMLElement).title).toBe(
      "Good for a first contribution: Labelled good first issue; Touches docs/",
    );
  });

  it("matches the repo case-insensitively", () => {
    expect(markStarterIssues(document, { owner: "Pallets", repo: "Flask" }, [{ number: 103 }])).toBe(1);
  });

  it("is idempotent across re-syncs", () => {
    markStarterIssues(document, flask, [{ number: 101 }]);
    expect(markStarterIssues(document, flask, [{ number: 101 }])).toBe(0);
    expect(document.querySelectorAll(".holt-starter")).toHaveLength(1);
  });

  it("ignores an empty or malformed list", () => {
    expect(markStarterIssues(document, flask, [])).toBe(0);
    expect(markStarterIssues(document, flask, [{ number: "101" as never }])).toBe(0);
  });

  it("removeStarterMarks undoes marking so rows can be re-marked", () => {
    markStarterIssues(document, flask, [{ number: 101 }]);
    removeStarterMarks(document);
    expect(document.querySelector(".holt-starter")).toBeNull();
    expect(markStarterIssues(document, flask, [{ number: 101 }])).toBe(1);
  });
});
