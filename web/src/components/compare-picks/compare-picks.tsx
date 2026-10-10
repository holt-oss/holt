"use client";

// Tick repos on a list's cards, then compare them: the ticks, and the bar that
// holds the picks (lib/compare-picks.ts). The picks live outside React, so a
// tick re-renders only the ticks whose state changed and the bar, never the list.
import Link from "next/link";
import { createContext, use, useEffect, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { comparePicksHref, createPickStore, shortName, tickState, type TickState } from "@/lib/compare-picks";

const store = createPickStore(() => window.sessionStorage);
const NONE: readonly string[] = [];
const noPicks = () => NONE;
const off = (): TickState => "off";

// Whether the cards under here get a tick.
const Ticks = createContext(false);

/** Around a list of repo cards: each card gets a tick, and the bar shows once one is ticked. */
export function ComparePicks({ signedIn, children }: { signedIn: boolean; children: React.ReactNode }) {
  useEffect(() => store.arrived(signedIn), [signedIn]);
  return (
    <Ticks value={true}>
      {children}
      <Bar signedIn={signedIn} />
    </Ticks>
  );
}

/** A card's tick; nothing outside `ComparePicks`. */
export function CompareTick({ repo }: { repo: string }) {
  return use(Ticks) ? <Tick repo={repo} /> : null;
}

function Tick({ repo }: { repo: string }) {
  const state = useSyncExternalStore(store.subscribe, () => tickState(store.get(), repo), off);
  const full = state === "full";
  // A toggle button, not a checkbox: the page's `:has(:checked)` rules would restyle the whole list on every tick.
  return (
    <button
      type="button"
      className="compare-tick"
      aria-pressed={state === "on"}
      // Still focusable when full, so it can say why.
      aria-disabled={full || undefined}
      aria-label={full ? `Compare ${repo}: four picked already` : `Compare ${repo}`}
      onClick={() => !full && store.toggle(repo)}
      data-umami-event={state === "off" ? "compare-tick" : undefined}
    >
      <span aria-hidden="true" className="compare-tick-box" />
      {full ? "max 4" : "compare"}
    </button>
  );
}

function Bar({ signedIn }: { signedIn: boolean }) {
  const list = useSyncExternalStore(store.subscribe, store.get, noPicks);
  const shown = list.length > 0;
  // Room under the page while the bar is up (globals.css).
  useEffect(() => {
    document.documentElement.toggleAttribute("data-compare-bar", shown);
    return () => document.documentElement.removeAttribute("data-compare-bar");
  }, [shown]);
  if (!shown) return null;
  // On <body>: a moving ancestor (the page's entrance) would otherwise carry a fixed bar with it.
  return createPortal(
    <section aria-label="Compare" className="compare-bar">
      <ul aria-label="Picked" className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto pr-4 [mask-image:linear-gradient(to_right,#000_calc(100%-1rem),transparent)] [scrollbar-width:none]">
        {list.map((repo) => (
          <li key={repo} className="shrink-0">
            <button type="button" onClick={() => store.remove(repo)} aria-label={`Remove ${repo}`} title={repo} className="compare-pick flex h-11 items-center sm:h-9">
              <span className="flex h-8 items-center gap-1.5 border border-line-strong bg-bg px-2 text-[0.8rem] text-ink transition-colors">
                <span className="max-w-[9rem] truncate">{shortName(repo, list)}</span>
                <span aria-hidden="true" className="text-faint">×</span>
              </span>
            </button>
          </li>
        ))}
        {list.length > 1 && (
          <li className="shrink-0">
            <button type="button" onClick={store.clear} className="h-11 px-2 text-[0.8rem] text-faint transition-colors hover:text-ink sm:h-9">
              clear
            </button>
          </li>
        )}
      </ul>
      {list.length > 1 && (
        <Link
          href={comparePicksHref(list, signedIn)}
          prefetch={false}
          // After the click has done its work: the bar leaves once the picks are cleared.
          onClick={() => setTimeout(() => store.opened(signedIn), 0)}
          data-umami-event={signedIn ? "compare-picks" : "compare-picks-signed-out"}
          className="btn-primary min-h-11 shrink-0 whitespace-nowrap px-4 text-[0.85rem] sm:min-h-9"
        >
          Compare {list.length} <span aria-hidden="true">→</span>
        </Link>
      )}
    </section>,
    document.body,
  );
}
