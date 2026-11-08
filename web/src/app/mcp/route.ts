// POST /mcp: Holt as a remote MCP server (Streamable HTTP, stateless, JSON
// responses), for Claude's custom connectors and ChatGPT's (API.md, "MCP";
// docs/MCP.md). No auth in v1: the tools read public data, the same for
// everyone. Cached reports are free; new checks draw on one server-side
// bucket for all MCP traffic (`X-Holt-Client: mcp`), apart from the site's
// per-visitor buckets, since every chat arrives from a few provider addresses.
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { getReport, jobStatus, startAnalysis, starterIssues, type Caller } from "@/lib/api";
import { clientIpFrom } from "@/lib/client-ip";
import { mcpServer } from "@/lib/mcp-server";
import { SITE_URL } from "@/lib/site";

// The data is public and nothing reads cookies, so any origin may call it
// (a browser-based MCP inspector, say), as with /api/public/*.
function cors(h: Headers) {
  h.set("Access-Control-Allow-Origin", "*");
  h.set("Access-Control-Allow-Methods", "POST, OPTIONS");
  h.set("Access-Control-Allow-Headers", "Content-Type, Accept, Authorization, Mcp-Protocol-Version, Mcp-Session-Id, Last-Event-ID");
  h.set("Access-Control-Expose-Headers", "Mcp-Session-Id");
  h.set("Access-Control-Max-Age", "86400");
}

export function OPTIONS() {
  const res = new Response(null, { status: 204 });
  cors(res.headers);
  return res;
}

export async function POST(req: Request) {
  const caller: Caller = { ip: clientIpFrom(req.headers), client: "mcp" };
  const server = mcpServer({
    getReport: (repo) => getReport(repo, "rules", 7),
    startAnalysis: (repo) => startAnalysis(repo, "rules", 7, false, caller),
    jobStatus,
    starterIssues: (repo, limit) => starterIssues(repo, limit, caller),
    siteUrl: SITE_URL,
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now: Date.now,
  });
  // Stateless: a new server and transport per request, no session id.
  const transport = new WebStandardStreamableHTTPServerTransport({
    sessionIdGenerator: undefined,
    enableJsonResponse: true,
    maxRequestBodySize: 64 * 1024,
  });
  let res: Response;
  try {
    await server.connect(transport);
    res = await transport.handleRequest(req);
  } catch (e) {
    console.error("[holt] mcp request failed:", e instanceof Error ? e.message : e);
    res = Response.json(
      { jsonrpc: "2.0", error: { code: -32603, message: "Holt couldn't answer that. Try again soon." }, id: null },
      { status: 500 },
    );
  } finally {
    void server.close().catch(() => {});
  }
  const out = new Response(res.body, { status: res.status, headers: res.headers });
  cors(out.headers);
  out.headers.set("Cache-Control", "no-store");
  return out;
}

// Stateless with JSON responses: there is no stream to open with GET and no session to end with DELETE.
function notAllowed() {
  const res = Response.json(
    { jsonrpc: "2.0", error: { code: -32000, message: "Method not allowed. Send MCP requests with POST." }, id: null },
    { status: 405, headers: { Allow: "POST, OPTIONS" } },
  );
  cors(res.headers);
  return res;
}

export const GET = notAllowed;
export const DELETE = notAllowed;
