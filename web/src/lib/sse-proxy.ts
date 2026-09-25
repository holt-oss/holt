import "server-only";
import { jobEvents } from "./api";
import { findCache, observeFindEvents } from "./find-cached";

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
    if (kind === "find") findCache.failJob(jobId);
    const error = upstream.status === 404
      ? { code: "not_found", message: "That analysis has expired. Start it again." }
      : { code: "upstream", message: "Lost contact with the analysis. Try again in a minute." };
    return new Response(`event: error\ndata: ${JSON.stringify({ error })}\n\n`, { headers });
  }
  // For finds, record the results on their way through so the next visitor
  // gets them from the cache instead of starting another find.
  const body = kind === "find" ? upstream.body.pipeThrough(observeFindEvents(jobId)) : upstream.body;
  return new Response(body, { headers });
}
