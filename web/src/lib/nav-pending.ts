// The page a click is on its way to, once it has kept the visitor waiting.
// A report has no loading screen to show at the click (see the report page:
// one would hold a ready verdict back), so until its answer arrives the page
// you were on stays up; the pending line (components/motion/nav-pending.tsx)
// says the click was heard. Next tells us when a navigation starts
// (instrumentation-client.ts); the line's component tells us when the page changed.
// No runtime imports, so it runs under `node --test` and in the browser.

/** A navigation quicker than this shows no line at all. */
export const SHOW_AFTER_MS = 100;
/** A navigation that never lands (the tab went offline) doesn't leave the line up. */
export const GIVE_UP_AFTER_MS = 20_000;

let pending: string | null = null;
let timers: ReturnType<typeof setTimeout>[] = [];
const listeners = new Set<() => void>();

function set(path: string | null) {
  if (pending === path) return;
  pending = path;
  for (const l of listeners) l();
}

function clearTimers() {
  for (const t of timers) clearTimeout(t);
  timers = [];
}

/** A navigation from the page at `from` to the one at `to` has started (pathnames). */
export function navigationStarted(to: string, from: string): void {
  clearTimers();
  set(null);
  // The same page with another query (a filter, the report's tabs) has its own pending state.
  if (to === from) return;
  timers = [setTimeout(() => set(to), SHOW_AFTER_MS), setTimeout(() => set(null), GIVE_UP_AFTER_MS)];
}

/** The page changed: whatever was on its way has arrived, or was given up for another. */
export function navigationSettled(): void {
  clearTimers();
  set(null);
}

/** The pathname being opened, once it has taken longer than SHOW_AFTER_MS. */
export function pendingPath(): string | null {
  return pending;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
