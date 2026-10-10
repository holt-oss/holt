// The repo-exists checker, one per server process, for the proxy (the report
// page's 404). Mock mode answers from the fixtures.
import { isMockNotFound } from "./mock/fixtures";
import { probeGitHub, repoExistsChecker } from "./repo-exists";

export const repoExists = repoExistsChecker({
  probe: process.env.MOCK_API === "1" ? async (r) => (isMockNotFound(r) ? "missing" : "exists") : probeGitHub,
});
