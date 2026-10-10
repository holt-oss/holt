import "server-only";
import { findIndex } from "./api";
import { FIND_FIRST, findQuery, type Picks } from "./find-picks";
import type { FindStart, Result } from "./types";

/**
 * A find answered from Holt's index alone (API.md, POST /v1/find/index): what
 * a signed-out visitor's filters get. It reads the database only, so it never
 * starts a GitHub search or a check and counts against no limit.
 */
export async function indexFind(picks: Picks): Promise<Result<FindStart>> {
  const { languages, topics, days, hacktoberfest } = findQuery(picks);
  const r = await findIndex({ languages, topics, days, hacktoberfest }, null, FIND_FIRST);
  return r.ok ? { ok: true, data: { status: "done", results: r.data.results, complete: true } } : r;
}
