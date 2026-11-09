// Holt's MCP server: the three tools, their schemas and the words a model
// reads to pick them (API.md, "MCP"). Built per request by app/mcp/route.ts
// (stateless) from lib/api.ts; the tests build it on a mocked server.
// No auth in v1: every tool reads public data, the same for every caller.
// OAuth can be added in front later without renaming a tool.
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import * as tools from "./mcp.ts";
import type { McpDeps, ToolAnswer } from "./mcp.ts";

export const SERVER_NAME = "holt";
export const SERVER_VERSION = "1.0.0";

const INSTRUCTIONS = `Holt tells you whether a GitHub repository is worth an outside contributor's time. It reads the repo's recent pull requests (do people outside the team get replies, and does their work get merged?) and gives one of six verdicts: Worth your time, Long shot, Not worth your time, Not enough evidence, Personal project, A list, not code.
The verdict comes from fixed rules over GitHub's own data. Report it as Holt's verdict, with its reason; don't swap in a verdict of your own. Say how old it is (the date is in the answer) and give the link to the report so the person can read the rest.
For one repo use check_repo. For a list of candidate repos ("which of these should I contribute to?") use compare_repos once with the whole list, not check_repo for each. Then starter_issues finds a first issue to pick up; pass on what on_it says, because some may already be taken.`;

const status = z.enum(["checked", "outdated", "old", "checking", "not_checked", "busy", "not_found", "invalid", "error"]);

const numbers = z.object({
  outside_prs: z.number().describe("Decided pull requests from people outside the project's team: opened more than 14 days before the report"),
  outside_prs_merged: z.number(),
  merged_percent: z.number(),
  typical_first_reply: z.string().nullable().describe('Like "14 hours"; null when no outside pull request got a reply'),
  typical_first_reply_hours: z.number().nullable(),
  no_reply: z.number().describe("Outside pull requests that never got a reply"),
  first_timers_merged: z.number().describe("People whose first pull request here was merged"),
  closed_without_a_word: z.number(),
  last_outside_merge: z.string().nullable().describe("YYYY-MM-DD"),
  still_open: z.number().describe("Outside pull requests opened in the 14 days before the report: too recent to count in the numbers above"),
  older_than_a_year: z.number().describe("Outside pull requests opened more than a year ago: read, and in no count"),
});

const row = z.object({
  repo: z.string(),
  status: status.describe(
    "checked: the verdict is from a report under 30 days old (checked_at says when). outdated / old: the verdict is from an older version of Holt, or from more than 30 days ago, and note says what is happening about it. checking / not_checked: no verdict yet, call again in a minute. busy: Holt isn't starting new checks from chats right now. not_found, invalid, error: see note.",
  ),
  verdict: z.string().nullable().describe("Holt's verdict, as the site words it"),
  reason: z.string().nullable().describe("One sentence: why that verdict"),
  odds: z.string().nullable().describe("How an outside pull request tends to fare, in words"),
  numbers: numbers.nullable(),
  checked_at: z.string().nullable().describe("When the report behind the verdict was made"),
  link: z.string().describe("The full report on Holt"),
  note: z.string().nullable(),
});

const issues = z.object({
  repo: z.string(),
  status: z.enum(["ok", "busy", "not_found", "invalid", "unavailable", "error"]),
  issues: z.array(z.object({
    number: z.number(),
    title: z.string(),
    url: z.string(),
    labels: z.array(z.string()),
    on_it: z.string().nullable().describe('Who is on it: "Nobody on it yet", "1 open pull request", … Tell the person.'),
    why: z.array(z.string()),
    next_step: z.string(),
  })),
  link: z.string(),
  note: z.string().nullable(),
});

const repoArg = z.string().min(1).max(300).describe("owner/name, like pallets/flask, or a github.com link");

// Read-only, and it reads GitHub (an open world). The same question gets the same answer.
const READ = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true } as const;

function answer<T>(a: ToolAnswer<T>) {
  return {
    content: [{ type: "text" as const, text: a.text }],
    structuredContent: a.structured as unknown as Record<string, unknown>,
    ...(a.isError ? { isError: true } : {}),
  };
}

export function mcpServer(deps: McpDeps): McpServer {
  const server = new McpServer(
    { name: SERVER_NAME, title: "Holt", version: SERVER_VERSION, websiteUrl: deps.siteUrl },
    { instructions: INSTRUCTIONS, maxToolInputElements: 100 },
  );

  server.registerTool("check_repo", {
    title: "Check a repo",
    description:
      "Is this GitHub repository worth an outside contributor's time? Returns Holt's verdict (Worth your time, Long shot, Not worth your time, Not enough evidence, Personal project, or A list, not code), the reason in one sentence, the key numbers (outside pull requests merged, typical first reply, first-timers merged) the date of the report, and a link to the full report. A repo with no report takes about 20 seconds; if the answer is still \"checking\", call again in a minute. A report over 30 days old, or from an older version of Holt, is checked again: its old verdict comes back with its date while that runs.",
    inputSchema: { repo: repoArg },
    outputSchema: row,
    annotations: { title: "Check a repo", ...READ },
  }, async ({ repo }) => answer(await tools.checkRepo(deps, { repo })));

  server.registerTool("compare_repos", {
    title: "Compare repos",
    description:
      `Rank up to ${tools.MAX_COMPARE} GitHub repositories by how likely an outside contributor's pull request is to be reviewed and merged. Use it when someone has a list of projects and asks which to contribute to. Returns one row per repo, best first: the verdict, its reason, the key numbers and a link. Repos with a report under 30 days old come back at once; it starts a few new checks per call, and the repos listed in call_again need another call (with just those) in a minute.`,
    inputSchema: { repos: z.array(repoArg).min(1).max(tools.MAX_COMPARE).describe("The repositories, as owner/name or github.com links") },
    outputSchema: z.object({
      repos: z.array(row).describe("Best first: by verdict, then by the odds and how often outside work is merged"),
      call_again: z.array(z.string()).describe("Repos without a current verdict yet: call compare_repos again with these in a minute"),
    }),
    annotations: { title: "Compare repos", ...READ },
  }, async ({ repos }) => answer(await tools.compareRepos(deps, { repos })));

  server.registerTool("starter_issues", {
    title: "Find starter issues",
    description:
      "Open issues in a GitHub repository that suit a newcomer, free ones first, with what to do next on each. Some may already be taken, when too few are free: each issue's on_it says who is on it, so pass that on rather than calling an issue free. Use it once someone has picked a repo to contribute to.",
    inputSchema: {
      repo: repoArg,
      limit: z.number().int().min(1).max(tools.MAX_ISSUES).optional().describe("How many issues, 1 to 20 (default 5)"),
    },
    outputSchema: issues,
    annotations: { title: "Find starter issues", ...READ },
  }, async ({ repo, limit }) => answer(await tools.starterIssues(deps, { repo, limit })));

  return server;
}
