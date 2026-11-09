// POST /mcp: Holt as a remote MCP server (Streamable HTTP, stateless, JSON
// responses), for Claude's custom connectors and ChatGPT's (API.md, "MCP";
// docs/MCP.md). No auth in v1: the tools read public data, the same for
// everyone. Cached reports are free; new checks draw on one server-side
// bucket for all MCP traffic (`X-Holt-Client: mcp`), apart from the site's
// per-visitor buckets, with a ceiling per address inside it.
import { getReport, jobStatus, startAnalysis, starterIssues, type Caller } from "@/lib/api";
import { clientIpFrom } from "@/lib/client-ip";
import { handleMcpPost, mcpMethodNotAllowed } from "@/lib/mcp-http";
import { mcpServer } from "@/lib/mcp-server";
import { SITE_URL } from "@/lib/site";

export async function POST(req: Request) {
  const caller: Caller = { ip: clientIpFrom(req.headers), client: "mcp" };
  return handleMcpPost(req, () => mcpServer({
    getReport: (repo) => getReport(repo, "rules", 7),
    startAnalysis: (repo) => startAnalysis(repo, "rules", 7, false, caller),
    jobStatus,
    starterIssues: (repo, limit) => starterIssues(repo, limit, caller),
    siteUrl: SITE_URL,
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now: Date.now,
  }));
}

export const GET = mcpMethodNotAllowed;
export const DELETE = mcpMethodNotAllowed;
