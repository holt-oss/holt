// The HTTP half of POST /mcp (app/mcp/route.ts), with no server-only imports so
// it runs under `node --test`: one JSON-RPC request per POST, in a new stateless
// server and transport.
//
// Batches are refused here, before a server exists. The transport would run up
// to 100 messages from one POST, each free to spend the MCP budget, and a chat
// has no use for them (MCP dropped batching in its 2025-06-18 revision). The
// value checked is the value the transport gets (`parsedBody`): it never reads
// the body again, so nothing can parse differently on the way through.
//
// No CORS headers: Claude's and ChatGPT's connectors call from their own
// servers. A web page can't send application/json here without a preflight,
// which fails, and the transport answers any other content type with 415.
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";

/** Far more than 30 repo names need. `parsedBody` skips the transport's own limit, so this is the limit. */
export const MAX_BODY_BYTES = 64 * 1024;

function rpcError(status: number, code: number, message: string): Response {
  return Response.json({ jsonrpc: "2.0", error: { code, message }, id: null }, { status });
}

/** The body as text, or null past `max` bytes, whatever Content-Length claimed. */
async function readBody(req: Request, max: number): Promise<string | null> {
  if (Number(req.headers.get("content-length")) > max) return null;
  if (!req.body) return "";
  const reader = req.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > max) {
      void reader.cancel().catch(() => {});
      return null;
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks).toString("utf-8").replace(/^﻿/, "");
}

async function answer(req: Request, makeServer: () => McpServer): Promise<Response> {
  const text = await readBody(req, MAX_BODY_BYTES);
  if (text === null) return rpcError(413, -32000, "That request is too large.");
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return rpcError(400, -32700, "That request isn't valid JSON.");
  }
  if (Array.isArray(body)) return rpcError(400, -32600, "Send one request per POST. Batches aren't accepted.");
  if (typeof body !== "object" || body === null) return rpcError(400, -32600, "That isn't a JSON-RPC request.");

  const server = makeServer();
  // Stateless: a new server and transport per request, no session id.
  const transport = new WebStandardStreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
  try {
    await server.connect(transport);
    return await transport.handleRequest(req, { parsedBody: body });
  } finally {
    void server.close().catch(() => {});
  }
}

export async function handleMcpPost(req: Request, makeServer: () => McpServer): Promise<Response> {
  let res: Response;
  try {
    res = await answer(req, makeServer);
  } catch (e) {
    console.error("[holt] mcp request failed:", e instanceof Error ? e.message : e);
    res = rpcError(500, -32603, "Holt couldn't answer that. Try again soon.");
  }
  const out = new Response(res.body, { status: res.status, headers: res.headers });
  out.headers.set("Cache-Control", "no-store");
  return out;
}

/** GET and DELETE: stateless with JSON responses, there is no stream to open and no session to end. */
export function mcpMethodNotAllowed(): Response {
  const res = rpcError(405, -32000, "Method not allowed. Send MCP requests with POST.");
  res.headers.set("Allow", "POST");
  return res;
}
