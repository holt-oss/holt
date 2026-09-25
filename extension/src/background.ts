// Fetches Holt's public endpoints for the content script. Only GETs, no
// cookies, and only the owner/repo of the page being viewed is sent.
import { publicApiUrl } from "./config";
import { parseRepo } from "./repo";
import type { Lookup, LookupMessage } from "./types";

const TTL_MS = 15 * 60 * 1000;
const MAX_ENTRIES = 300;
const cache = new Map<string, { at: number; value: Lookup<unknown> }>();

export async function fetchLookup(
  url: string,
  fetchFn: typeof fetch = fetch,
): Promise<Lookup<unknown>> {
  try {
    const res = await fetchFn(url, {
      credentials: "omit",
      headers: { Accept: "application/json" },
    });
    if (res.status === 404) return { state: "missing" };
    if (!res.ok) return { state: "error" };
    const data: unknown = await res.json();
    if (!data || typeof data !== "object") return { state: "error" };
    return { state: "found", data };
  } catch {
    return { state: "error" };
  }
}

async function cachedLookup(url: string): Promise<Lookup<unknown>> {
  const hit = cache.get(url);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.value;
  const value = await fetchLookup(url);
  // Errors are not cached, so a flaky network does not stick for 15 minutes.
  if (value.state !== "error") {
    if (cache.size >= MAX_ENTRIES) cache.delete(cache.keys().next().value!);
    cache.set(url, { at: Date.now(), value });
  }
  return value;
}

function isLookupMessage(m: unknown): m is LookupMessage {
  const x = m as LookupMessage;
  return (
    !!x && x.type === "holt:lookup" &&
    (x.kind === "report" || x.kind === "starter-issues") &&
    typeof x.owner === "string" && typeof x.repo === "string"
  );
}

if (typeof chrome !== "undefined" && chrome.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((msg: unknown, sender, sendResponse) => {
    if (sender.id !== chrome.runtime.id || !isLookupMessage(msg)) return false;
    // Re-validate: never build a URL from anything that is not a plain owner/repo.
    const r = parseRepo(`/${msg.owner}/${msg.repo}`);
    if (!r || r.owner !== msg.owner || r.repo !== msg.repo) {
      sendResponse({ state: "error" });
      return false;
    }
    cachedLookup(publicApiUrl(msg.kind, r.owner, r.repo)).then(sendResponse);
    return true; // keeps the channel open for the async answer
  });
}
