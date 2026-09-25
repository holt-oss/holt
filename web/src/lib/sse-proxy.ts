import "server-only";
import { jobEvents } from "./api";

/** Pipe an upstream job's Server-Sent Events to the browser. */
export async function proxyJobEvents(kind: "analyses" | "find", jobId: string, signal: AbortSignal): Promise<Response> {
  const upstream = await jobEvents(kind, jobId, signal);
  const headers = {
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  };
  if (upstream.status === 400) return new Response(upstream.body, { status: 400, headers });
  if (!upstream.ok || !upstream.body) {
    const error = upstream.status === 404
      ? { code: "not_found", message: "That analysis has expired. Start it again." }
      : { code: "upstream", message: "Lost contact with the analysis. Try again in a minute." };
    return new Response(`event: error\ndata: ${JSON.stringify({ error })}\n\n`, { headers });
  }
  return new Response(upstream.body, { headers });
}
