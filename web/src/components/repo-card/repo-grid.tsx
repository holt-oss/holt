"use client";

import type Lenis from "lenis";
import { useSearchParams } from "next/navigation";
import { createContext, Suspense, use, useEffect, useRef, useState } from "react";
import { neighbours, type CardRepo } from "@/lib/repo-card";
import { savedSet, withSaved } from "@/lib/saved";
import { CompareTick } from "../compare-picks/compare-picks";
import { useReducedMotion } from "../motion/use-seen";
import { pauseSmoothScroll } from "../motion/smooth-scroll";
import { SaveButton } from "../save-button";
import { RepoCard } from "./repo-card";
import { RepoFocus } from "./repo-focus";

type Common = {
  /** The report link's `days`, when the list was searched with another window than the default week. */
  days?: number;
  /** A slot per repo (by `owner/name`) for extra buttons, on the card and in the focus view. */
  actions?: Partial<Record<string, React.ReactNode>>;
  /** Where a topic in the focus view links to (a board URL; `topic=` is added). */
  topicBase?: string;
  /**
   * The repos this person saved (`savedNames`), fetched once for the page: a
   * save button then goes on every card and in the focus view. Null when
   * signed out (the button offers sign-in); leave it out for no save buttons.
   */
  saved?: string[] | null;
  /** Unsaved cards fade instead of staying as they were (the saved list). */
  fadeUnsaved?: boolean;
  /** False leaves the verdict off the cards (the focus view keeps it): for a list where every repo has the same one. */
  verdict?: boolean;
  /** Each card says why this repo for this person (a pick's first `why` line). */
  why?: boolean;
};

type Card = (r: CardRepo) => React.ReactNode;

// Saves and unsaves made in this tab. A list that mounts again (new search
// results, a page visited earlier) starts from what the server said then, so
// these win over it.
const changed = new Map<string, boolean>();

const PARAM = "focus";

const NAV_BTN = "grid size-11 place-items-center border border-line-strong bg-panel text-muted transition-colors hover:border-blue hover:text-ink disabled:pointer-events-none disabled:opacity-30 sm:size-8";

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}
const reportHref = (repo: string, days?: number) => `/${repo}${days && days !== 7 ? `?days=${days}` : ""}`;

function withFocus(repo: string | null): string {
  const u = new URL(window.location.href);
  if (repo) u.searchParams.set(PARAM, repo);
  else u.searchParams.delete(PARAM);
  return `${u.pathname}${u.search}${u.hash}`;
}

/** A grid of compact repo cards (`.card-grid`, at most `cols` across); `?focus=owner/name` opens one in a focus view (back closes it). */
export function RepoGrid({ repos, cols, tail, ...common }: Common & {
  repos: CardRepo[];
  cols?: number;
  /** More `<li>`s after the cards, in the same grid: the placeholders of a part still loading. */
  tail?: React.ReactNode;
}) {
  return (
    <FocusList
      {...common}
      repos={repos}
      layout={(card) => (
        <ol className="card-grid" style={cols ? ({ "--cols": cols } as React.CSSProperties) : undefined}>
          {repos.map((r, i) => (
            <li key={r.repo} className="reveal min-w-0" style={{ ["--i" as string]: i }}>
              {card(r)}
            </li>
          ))}
          {tail}
        </ol>
      )}
    />
  );
}

type ListProps = Common & { repos: CardRepo[]; layout: (card: Card) => React.ReactNode };

/** Owns which repos are saved, so a card and its focus view agree, and lays the cards out around the focus view. */
function FocusList(props: ListProps) {
  const { saved, actions, fadeUnsaved, verdict, why } = props;
  const [set, setSet] = useState(() => [...changed].reduce((s, [repo, v]) => withSaved(s, repo, v), savedSet(saved ?? [])));
  const isSaved = (repo: string) => set.has(repo.toLowerCase());

  const save = (repo: string, compact: boolean) =>
    saved === undefined ? null : (
      <SaveButton repo={repo} saved={saved === null ? null : isSaved(repo)} onChange={(v) => {
        changed.set(repo.toLowerCase(), v);
        setSet((s) => withSaved(s, repo, v));
      }} compact={compact} small={compact} />
    );
  const actionsFor = (repo: string, compact: boolean) => {
    const extra = actions?.[repo];
    const button = save(repo, compact);
    return extra && button ? <>{extra}{button}</> : extra ?? button;
  };
  const card: Card = (r) => (
    <ListCard r={r} report={reportHref(r.repo, props.days)} actions={actionsFor(r.repo, true)} faded={Boolean(fadeUnsaved && saved && !isSaved(r.repo))} verdict={verdict} why={why} />
  );

  return (
    <Suspense fallback={props.layout(card)}>
      <Focusable {...props} card={card} actionsFor={actionsFor} />
    </Suspense>
  );
}

// Opens a card in the focus view; absent until the address can be read (then cards are plain links).
const OpenFocus = createContext<((repo: string) => void) | null>(null);

function ListCard({ r, report, actions, faded, verdict, why }: { r: CardRepo; report: string; actions: React.ReactNode; faded: boolean; verdict?: boolean; why?: boolean }) {
  const open = use(OpenFocus);
  return (
    <div className={`h-full transition-opacity duration-300 ${faded ? "opacity-55 focus-within:opacity-100 hover:opacity-100" : ""}`}>
      <RepoCard r={r} report={report} onOpen={open ? () => open(r.repo) : undefined} actions={actions} tick={<CompareTick repo={r.repo} />} verdict={verdict} why={why} />
    </div>
  );
}

function Focusable({ repos, layout, days, topicBase, card, actionsFor }: ListProps & {
  card: Card;
  actionsFor: (repo: string, compact: boolean) => React.ReactNode;
}) {
  const focus = useSearchParams().get(PARAM);
  const nb = neighbours(repos.map((r) => r.repo), focus);
  const current = nb ? repos[nb.index] : null;
  const dialog = useRef<HTMLDialogElement>(null);
  const scrollArea = useRef<HTMLDivElement>(null);
  const previewGlide = useRef<Lenis | null>(null);
  const reduced = useReducedMotion();
  const hasCurrent = Boolean(current);
  const pushed = useRef(false);
  const touch = useRef<{ x: number; y: number } | null>(null);

  const open = (repo: string) => {
    pushed.current = true;
    window.history.pushState(null, "", withFocus(repo));
  };
  const go = (repo: string | null) => repo && window.history.replaceState(null, "", withFocus(repo));
  const close = () => {
    if (pushed.current) {
      pushed.current = false;
      window.history.back();
    } else {
      window.history.replaceState(null, "", withFocus(null));
    }
  };

  // The URL is the source of truth: back and forward open and close the view.
  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (hasCurrent && !d.open) d.showModal();
    if (!hasCurrent && d.open) d.close();
    document.documentElement.style.overflow = hasCurrent ? "hidden" : "";
    pauseSmoothScroll(hasCurrent);
    return () => {
      document.documentElement.style.overflow = "";
      pauseSmoothScroll(false);
    };
  }, [hasCurrent]);
  // Give the preview its own wheel glide while the page behind it is paused.
  // Touch and reduced motion keep native scrolling.
  useEffect(() => {
    const wrapper = scrollArea.current;
    const content = wrapper?.firstElementChild as HTMLElement | null;
    if (!hasCurrent || reduced || !wrapper || !content || !matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    let cancelled = false;
    let cleanup: (() => void) | undefined;
    import("lenis").then(({ default: Lenis }) => {
      if (cancelled) return;
      const glide = new Lenis({ wrapper, content, autoRaf: true, lerp: 0.09, allowNestedScroll: true });
      previewGlide.current = glide;
      cleanup = () => {
        glide.destroy();
        previewGlide.current = null;
      };
    });
    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [hasCurrent, reduced]);

  // Moving to another repo starts at its top.
  useEffect(() => {
    const d = dialog.current;
    // A focused navigation button can become disabled at either end of the
    // list. Keep keyboard focus in the modal so arrows still work back again.
    const active = document.activeElement;
    if (d?.open && (!d.contains(active) || (active instanceof HTMLButtonElement && active.disabled))) {
      d.querySelector<HTMLButtonElement>('button[aria-label="Close"]')?.focus({ preventScroll: true });
    }
    previewGlide.current?.scrollTo(0, { immediate: true, force: true });
    scrollArea.current?.scrollTo({ top: 0, left: 0, behavior: "instant" });
  }, [current?.repo]);

  return (
    <>
      <OpenFocus value={open}>{layout(card)}</OpenFocus>
      <dialog
        ref={dialog}
        // Its own scroll area glides independently of the paused page.
        aria-labelledby="focus-title"
        onClose={() => {
          if (new URLSearchParams(window.location.search).has(PARAM)) close();
        }}
        onClick={(e) => e.target === e.currentTarget && close()}
        onKeyDown={(e) => {
          if (e.target instanceof HTMLElement && e.target.closest("input, textarea, select, [contenteditable=true]")) return;
          if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
            // Arrow navigation must never also scroll the preview sideways.
            e.preventDefault();
            go(e.key === "ArrowLeft" ? nb?.prev ?? null : nb?.next ?? null);
          }
        }}
        onTouchStart={(e) => {
          touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        }}
        onTouchEnd={(e) => {
          const t = touch.current;
          touch.current = null;
          if (!t || !nb) return;
          const dx = e.changedTouches[0].clientX - t.x;
          const dy = e.changedTouches[0].clientY - t.y;
          if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) go(dx < 0 ? nb.next : nb.prev);
        }}
        className="repo-preview overflow-hidden bg-bg text-ink backdrop:bg-black/60 backdrop:backdrop-blur-[2px] max-sm:m-0 max-sm:h-dvh max-sm:max-h-none max-sm:w-full max-sm:max-w-none sm:m-auto sm:max-h-[90vh] sm:w-[calc(100%_-_3rem)] sm:max-w-[40rem] sm:border sm:border-line-strong sm:shadow-soft"
      >
        {current && nb && (
          <div className="flex h-full min-w-0 flex-col sm:h-auto sm:max-h-[90vh]">
            <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-1.5 font-sans text-[0.85rem] text-muted sm:px-5">
              <span className="tabular-nums">{nb.index + 1} of {repos.length}</span>
              <div className="flex items-center gap-2">
                <button type="button" onClick={() => go(nb.prev)} disabled={!nb.prev} aria-label="Previous repo" className={NAV_BTN}>
                  <Icon d="M15 5l-7 7 7 7" />
                </button>
                <button type="button" onClick={() => go(nb.next)} disabled={!nb.next} aria-label="Next repo" className={NAV_BTN}>
                  <Icon d="M9 5l7 7-7 7" />
                </button>
                <button type="button" onClick={close} aria-label="Close" className={`${NAV_BTN} ml-1`}>
                  <Icon d="M6 6l12 12M18 6L6 18" />
                </button>
              </div>
            </div>
            <div ref={scrollArea} data-scroll className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain p-4 sm:flex-initial sm:px-5 sm:py-4">
              <div className="min-w-0">
                <div key={current.repo} className="repo-preview-content min-w-0">
                  <RepoFocus r={current} report={reportHref(current.repo, days)} actions={actionsFor(current.repo, true)} topicBase={topicBase} />
                </div>
              </div>
            </div>
            <p className="hidden border-t border-line px-5 py-1.5 font-sans text-[0.8rem] text-faint sm:block">← → to move between repos · Esc to close</p>
          </div>
        )}
      </dialog>
    </>
  );
}
