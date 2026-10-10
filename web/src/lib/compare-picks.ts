// Repos ticked on a list's cards to compare (Find, Browse, Hacktoberfest): at
// most MAX, kept for the tab in session storage so they outlast paging, filter
// changes and moving between the lists. No imports beyond compare and the
// sign-in link, so it runs under `node --test`.
import { compareHref, MAX, parseList } from "./compare.ts";
import { signInHref } from "./gate.ts";

export const PICKS_KEY = "holt:compare-picks";
/** Set when a signed-out reader leaves for sign-in with their picks in the callback. */
export const SENT_KEY = "holt:compare-sent";

const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

export const hasPick = (list: readonly string[], repo: string) => list.some((r) => same(r, repo));
export const isFull = (list: readonly string[]) => list.length >= MAX;

/** The list with `repo` added: unchanged when it's already there or the list is full. */
export function addPick(list: readonly string[], repo: string): string[] {
  return hasPick(list, repo) || isFull(list) ? [...list] : [...list, repo];
}

export function removePick(list: readonly string[], repo: string): string[] {
  return list.filter((r) => !same(r, repo));
}

export function togglePick(list: readonly string[], repo: string): string[] {
  return hasPick(list, repo) ? removePick(list, repo) : addPick(list, repo);
}

/** A card's tick: ticked, free to tick, or off because four are picked already. */
export type TickState = "on" | "off" | "full";

export function tickState(list: readonly string[], repo: string): TickState {
  return hasPick(list, repo) ? "on" : isFull(list) ? "full" : "off";
}

/** The name without its owner, for the bar; the owner stays when two picks share a name. */
export function shortName(repo: string, list: readonly string[] = []): string {
  const name = repo.split("/")[1] ?? repo;
  return list.some((r) => !same(r, repo) && same(r.split("/")[1] ?? r, name)) ? repo : name;
}

/** What storage holds, read back: only real owner/name pairs, no duplicates, at most MAX. Anything else is an empty list. */
export function readPicks(raw: string | null | undefined): string[] {
  if (!raw) return [];
  try {
    const v: unknown = JSON.parse(raw);
    return Array.isArray(v) ? parseList(v.filter((x): x is string => typeof x === "string")) : [];
  } catch {
    return [];
  }
}

/** "Compare N →": the compare page, through sign-in (and back to the same list) when signed out. */
export function comparePicksHref(list: readonly string[], signedIn: boolean): string {
  const to = compareHref([...list]);
  return signedIn ? to : signInHref(to);
}

type Storage = Pick<globalThis.Storage, "getItem" | "setItem" | "removeItem">;

export interface PickStore {
  get(): readonly string[];
  subscribe(fn: () => void): () => void;
  toggle(repo: string): void;
  remove(repo: string): void;
  clear(): void;
  /** "Compare N →" was pressed: the picks are done with, now or (signed out) once sign-in comes back. */
  opened(signedIn: boolean): void;
  /** A list page mounted: drop picks that already went to Compare through sign-in. */
  arrived(signedIn: boolean): void;
}

/**
 * The picks, read from `storage` once and written back on every change. A
 * storage that throws (private windows, blocked site data) leaves them in
 * memory for the page. `get` returns the same array until something changes,
 * so it can back `useSyncExternalStore`.
 */
export function createPickStore(storage: () => Storage | null): PickStore {
  let list: readonly string[] | null = null;
  const subs = new Set<() => void>();
  const store = () => {
    try {
      return storage();
    } catch {
      return null;
    }
  };
  const load = () => {
    if (list === null) {
      try {
        list = readPicks(store()?.getItem(PICKS_KEY));
      } catch {
        list = [];
      }
    }
    return list;
  };
  const set = (next: string[]) => {
    const now = load();
    if (next.length === now.length && next.every((r, i) => r === now[i])) return;
    list = next;
    try {
      if (next.length) store()?.setItem(PICKS_KEY, JSON.stringify(next));
      else store()?.removeItem(PICKS_KEY);
    } catch {
      // kept in memory
    }
    for (const fn of subs) fn();
  };
  const sent = (v?: boolean) => {
    try {
      const s = store();
      if (v === undefined) return s?.getItem(SENT_KEY) === "1";
      if (v) s?.setItem(SENT_KEY, "1");
      else s?.removeItem(SENT_KEY);
    } catch {
      // nothing to remember
    }
    return false;
  };
  return {
    get: load,
    subscribe(fn) {
      subs.add(fn);
      return () => subs.delete(fn);
    },
    toggle: (repo) => set(togglePick(load(), repo)),
    remove: (repo) => set(removePick(load(), repo)),
    clear: () => set([]),
    opened(signedIn) {
      // Signed out, they stay until sign-in has happened: backing out of it loses nothing.
      if (signedIn) set([]);
      else sent(true);
    },
    arrived(signedIn) {
      if (!sent()) return;
      if (signedIn) set([]);
      sent(false);
    },
  };
}
