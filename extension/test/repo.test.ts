import { isIssueListPath, parseRepo } from "../src/repo";
import { publicApiUrl, reportPageUrl } from "../src/config";

describe("parseRepo", () => {
  it.each([
    ["/pallets/flask", "pallets", "flask"],
    ["/pallets/flask/", "pallets", "flask"],
    ["/pallets/flask/issues", "pallets", "flask"],
    ["/NixOS/nixpkgs/tree/master/pkgs", "NixOS", "nixpkgs"],
    ["/o/r.git", "o", "r"],
    ["/my-org/some.repo_name", "my-org", "some.repo_name"],
  ])("%s → %s/%s", (path, owner, repo) => {
    expect(parseRepo(path)).toEqual({ owner, repo });
  });

  it.each([
    "/", "/pallets", "/settings/profile", "/orgs/pallets/repositories", "/marketplace/actions",
    "/topics/python", "/notifications/beta", "/-bad/repo", "/o/..", "/o/%E0%A4%A", "/o/re po",
  ])("%s is not a repo page", (path) => {
    expect(parseRepo(path)).toBeNull();
  });
});

describe("isIssueListPath", () => {
  it("matches issue lists and the contribute page only", () => {
    expect(isIssueListPath("/o/r/issues")).toBe(true);
    expect(isIssueListPath("/o/r/issues/")).toBe(true);
    expect(isIssueListPath("/o/r/contribute")).toBe(true);
    expect(isIssueListPath("/o/r/issues/12")).toBe(false);
    expect(isIssueListPath("/o/r/pulls")).toBe(false);
    expect(isIssueListPath("/o/r")).toBe(false);
  });
});

describe("urls", () => {
  it("points at the configured host", () => {
    expect(reportPageUrl("pallets", "flask")).toBe("https://githolt.com/pallets/flask");
    expect(publicApiUrl("report", "pallets", "flask", "example.test")).toBe(
      "https://example.test/api/public/report/pallets/flask",
    );
    expect(publicApiUrl("starter-issues", "a", "b.c", "example.test")).toBe(
      "https://example.test/api/public/starter-issues/a/b.c",
    );
  });
});
