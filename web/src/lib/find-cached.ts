import "server-only";
import { find, type Caller } from "./api";
import { FindCache } from "./find-cache";
import type { FindQuery, FindResult, FindStart, Result } from "./types";

// One cache per server process (globalThis so dev reloads share it).
const g = globalThis as unknown as { holtFindCache?: FindCache };
export const findCache = (g.holtFindCache ??= new FindCache(10 * 60_000));

/** /v1/find through the 10-minute cache: at most one upstream find per query per window. */
export function cachedFind(q: FindQuery, caller: Caller): Promise<Result<FindStart>> {
  return findCache.get(q, () => find(q, caller));
}

/** Watches a find job's SSE stream as it passes through and records the outcome. */
export function observeFindEvents(jobId: string): TransformStream<Uint8Array, Uint8Array> {
  const dec = new TextDecoder();
  let buf = "";
  let settled = false;
  const scan = () => {
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const event = block.match(/^event:\s*(.+)$/m)?.[1]?.trim();
      const data = block
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim())
        .join("\n");
      if (event === "done") {
        try {
          const d = JSON.parse(data) as { results?: FindResult[] };
          if (Array.isArray(d.results)) findCache.resolveJob(jobId, d.results);
          settled = true;
        } catch {}
      } else if (event === "error") {
        findCache.failJob(jobId);
        settled = true;
      }
    }
  };
  return new TransformStream({
    transform(chunk, controller) {
      controller.enqueue(chunk);
      if (!settled && buf.length < 2_000_000) {
        buf += dec.decode(chunk, { stream: true });
        scan();
      }
    },
  });
}
