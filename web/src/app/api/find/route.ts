import { NextResponse, type NextRequest } from "next/server";
import { cachedFind } from "@/lib/find-cached";
import { indexFind } from "@/lib/find-index";
import { findQuery, picksFromQuery } from "@/lib/find-picks";
import { findReads } from "@/lib/gate";
import { caller } from "@/lib/session";

/**
 * The /find page refining in place: `{"q": <the page's query string>}` in, a
 * FindStart out. POST, as a search can spend the visitor's work limit. Goes through the same 10-minute cache as the page itself, so
 * tapping back to an earlier pick costs nothing upstream. Signed out, the
 * answer is what Holt's index has for the filters: no GitHub search runs.
 */
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { q?: unknown } | null;
  const picks = typeof body?.q === "string" && body.q.length <= 2000 ? picksFromQuery(body.q) : null;
  if (!picks) {
    return NextResponse.json({ error: { code: "invalid_request", message: "That search didn't make sense. Reload the page and try again." } }, { status: 400 });
  }
  const who = await caller();
  const r = findReads(who.userId) === "search" ? await cachedFind(findQuery(picks), who) : await indexFind(picks);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: r.status });
  return NextResponse.json(r.data, { headers: { "Cache-Control": "no-store" } });
}
