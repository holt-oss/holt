"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { track } from "@/lib/analytics";
import { defaultPicks, PICKS_COOKIE, picksQuery, searchKey, widen, type Picks, type PicksSource } from "@/lib/find-picks";
import { signInHref } from "@/lib/gate";
import { personalise, type Fit } from "@/lib/profile";
import type { ApiError, FindResult, FindStart, Result } from "@/lib/types";
import type { Prefs } from "@/lib/profile-flow";
import { saveFromFind } from "@/app/profile/actions";
import { ComparePicks } from "../compare-picks/compare-picks";
import { ErrorPanel } from "../error-panel";
import { EmptyState } from "../shell/app-page";
import { FindFilters } from "./find-filters";
import { FindList } from "./find-list";
import { FindResultsSkeleton } from "./find-skeleton";
import { useFindJob } from "./use-find-job";

/** Taps closer together than this make one search: each new search can spend the visitor's hourly limit. */
const SETTLE_MS = 700;

type Shown = { key: string; result: Result<FindStart> };

/**
 * /find after the first paint: the filters apply as they're tapped. Experience
 * and work type only reorder what's already here; languages, time, topics and
 * the Hacktoberfest switch start a new (cached) search once the taps settle.
 * Signed out, the same filters are answered from Holt's index alone
 * (app/api/find/route.ts), and a search of GitHub waits for sign-in.
 */
export function FindView({ initialPicks, initial, source, hf, saved, signedIn = true, profile = null, notice }: {
  initialPicks: Picks;
  initial: Result<FindStart>;
  source: PicksSource;
  hf: { note: string; on: boolean } | null;
  saved: string[] | null;
  signedIn?: boolean;
  /** The saved profile, for "save as my profile"; null without one. */
  profile?: Prefs | null;
  /** A one-off note (profile saved), just under the filters. */
  notice?: React.ReactNode;
}) {
  const [picks, setPicks] = useState(initialPicks);
  const [shown, setShown] = useState<Shown>({ key: searchKey(initialPicks), result: initial });
  const [retry, setRetry] = useState(0);
  // A new server render (a link to /find with other picks) starts over from it.
  const [from, setFrom] = useState({ initialPicks, initial });
  if (from.initialPicks !== initialPicks || from.initial !== initial) {
    setFrom({ initialPicks, initial });
    setPicks(initialPicks);
    setShown({ key: searchKey(initialPicks), result: initial });
  }

  const key = searchKey(picks);
  const pending = key !== shown.key;
  const q = picksQuery(picks);

  // The URL and the remembered picks follow every change. A search opened
  // from a link counts as picked; a profile or the defaults don't, so a later
  // profile change still shows through.
  const seen = useRef<string | null>(null);
  useEffect(() => {
    const prev = seen.current;
    seen.current = q;
    if (prev === q) return; // the same picks again (a strict-mode re-run)
    if (prev === null && source !== "url") return;
    try {
      if (prev !== null) window.history.replaceState(null, "", `/find?${q}`);
      document.cookie = `${PICKS_COOKIE}=${encodeURIComponent(q)}; path=/; max-age=${60 * 60 * 24 * 180}; samesite=lax`;
    } catch {
      // Remembering is a convenience; the search still runs.
    }
  }, [q, source]);

  useEffect(() => {
    if (!pending) return;
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      track("find-run");
      let result: Result<FindStart>;
      try {
        const res = await fetch("/api/find", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ q }), signal: ctl.signal });
        const body = await res.json();
        result = res.ok ? { ok: true, data: body } : { ok: false, status: res.status, error: body.error ?? { code: "upstream", message: "The search didn't answer. Try again." } };
      } catch {
        if (ctl.signal.aborted) return;
        result = { ok: false, status: 0, error: { code: "upstream", message: "Couldn't reach Holt. Check your connection and try again." } };
      }
      setShown({ key, result });
    }, SETTLE_MS);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
    // `retry` re-runs a failed search with the same picks.
  }, [pending, key, q, retry]);

  const retryNow = () => {
    setShown((s) => ({ ...s, key: "" }));
    setRetry((n) => n + 1);
  };
  const fit = { level: picks.level, contributions: picks.types };
  const isDefault = q === picksQuery(defaultPicks(hf?.on ?? false));
  const untouched = picks === initialPicks;

  // The search's state.
  const r = shown.result;
  // A new search comes with what Holt has already checked (`results`), shown
  // while the search adds to it; if the search fails, that still stands.
  const index = r.ok && r.data.status === "queued" ? r.data.results : null;
  const job = useFindJob(r.ok && r.data.status === "queued" ? r.data.job_id : null);
  const searching = index !== null && !job.results && !job.error;
  const raw: FindResult[] | null = !r.ok ? null : r.data.status === "done" ? r.data.results : job.results ?? (index?.length ? index : null);
  const error = !r.ok ? r.error : index?.length ? null : job.error;
  const fitted = raw ? personalise(raw, fit) : null;
  // Nothing of the index fits yet: wait for the search rather than say "none".
  const list = searching && !fitted?.length ? null : fitted;

  // "save as my profile": only with a profile to update, and picks that differ from it.
  const [saving, setSaving] = useState<"idle" | "saving" | "saved" | "adult" | "error">("idle");
  const [savedAs, setSavedAs] = useState<Picks | null>(null);
  const differs = profile !== null && !sameAsProfile(picks, savedAs ? { languages: savedAs.langs, topics: savedAs.topics, days: savedAs.days, level: savedAs.level, contributions: savedAs.types } : profile);
  const saveAsProfile = async () => {
    setSaving("saving");
    const res = await saveFromFind({ languages: picks.langs, topics: picks.topics, days: picks.days, level: picks.level, contributions: picks.types }).catch(() => ({ ok: false as const, adult: false }));
    if (res.ok) setSavedAs(picks);
    setSaving(res.ok ? "saved" : res.adult ? "adult" : "error");
  };

  // Under the bar, scrolling away with the results: where the picks came from, and what to do with them.
  const reset = () => setPicks(defaultPicks(hf?.on ?? false));
  const action = "min-h-6 text-muted underline decoration-dotted underline-offset-4 hover:text-ink disabled:opacity-60";
  const fromProfile = source === "profile" && untouched;
  const lastSearch = source === "last" && untouched && !differs;
  const canSave = differs && saving !== "adult";
  const aside = fromProfile || lastSearch || canSave || !isDefault || (saving === "saved" && !differs) || saving === "adult" || saving === "error";

  return (
    <>
      <FindFilters picks={picks} onChange={setPicks} hf={hf} busy={pending} />
      <p role="status" className="sr-only">{pending ? "Updating…" : ""}</p>
      {aside && (
        <p className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[0.8rem] text-faint">
          {fromProfile && (
            <span>
              Started from your profile. <Link href="/settings/profile" className="text-link">edit it</Link>
            </span>
          )}
          {lastSearch && <span>Your last search.</span>}
          {saving === "saved" && !differs && <span role="status" className="text-ink">Saved as your profile.</span>}
          {saving === "adult" && <Link href="/settings/profile" className="text-link">finish your profile in settings</Link>}
          {saving === "error" && <span role="status" className="text-orange">Couldn&apos;t save. Try again.</span>}
          {canSave && (
            <button type="button" onClick={saveAsProfile} disabled={saving === "saving"} className={action}>
              {saving === "saving" ? "saving…" : "save as my profile"}
            </button>
          )}
          {!isDefault && (
            <button type="button" onClick={reset} className={action}>
              reset filters
            </button>
          )}
        </p>
      )}
      {notice}
      {/* The list carries on into the index once the search has settled on these picks; a search still running, or about to, keeps to its own results. */}
      <ComparePicks signedIn={signedIn}>
        <Results pending={pending} signIn={signedIn ? null : signInHref(`/find?${q}`)} list={list} raw={raw ?? []} fit={fit} more={searching || pending ? null : picksQuery({ ...picks, level: "experienced", types: [] })} searching={searching} error={error} progress={job.stage.progress} days={picks.days} saved={saved} picks={picks} setPicks={setPicks} onRetry={retryNow} />
      </ComparePicks>
    </>
  );
}

function sameAsProfile(p: Picks, prof: Pick<Prefs, "languages" | "topics" | "days" | "level" | "contributions">): boolean {
  const same = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));
  return same(p.langs, prof.languages) && same(p.topics, prof.topics) && same(p.types, prof.contributions) && p.days === prof.days && p.level === prof.level;
}

function Results({ pending, signIn, list, raw, fit, more, searching, error, progress, days, saved, picks, setPicks, onRetry }: {
  pending: boolean;
  /** Signed out: sign-in and back to these picks, offered when the index has nothing for them. */
  signIn: string | null;
  /** The personalised results, or null while the search runs with nothing to show yet. */
  list: FindResult[] | null;
  /** The same results before they were fitted to the reader, and what fits them. */
  raw: FindResult[];
  fit: Fit;
  /** The search as a query string, when the list may load the rest of the index (FindList). */
  more: string | null;
  /** The search is still adding to `list`. */
  searching: boolean;
  error: ApiError | null;
  progress: number;
  days: number;
  saved: string[] | null;
  picks: Picks;
  setPicks: (p: Picks) => void;
  onRetry: () => void;
}) {
  let body: React.ReactNode;
  if (error) {
    body = <ErrorPanel error={error} onRetry={onRetry} />;
  } else if (!list) {
    body = (
      <>
        <p className="mb-3 text-[0.82rem] text-faint">Checking which repos reply to outsiders. A new search takes up to a minute.</p>
        <SearchProgress progress={progress} />
        <FindResultsSkeleton count={3} />
      </>
    );
  } else if (!list.length) {
    body = <Empty picks={picks} setPicks={setPicks} signIn={signIn} />;
  } else {
    body = (
      <>
        {searching && <SearchProgress progress={progress} />}
        <FindList results={raw} fit={fit} more={more} days={days} saved={saved} />
      </>
    );
  }

  return (
    <section aria-label="Results" aria-busy={pending || (!list && !error)} className="mt-5">
      <div className={`transition-opacity duration-200 ${pending ? "pointer-events-none opacity-40" : ""}`}>{body}</div>
    </section>
  );
}

function SearchProgress({ progress }: { progress: number }) {
  const pct = Math.round(Math.min(1, Math.max(0.05, progress)) * 100);
  return (
    <div className="mb-5 h-1 bg-panel-2" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Search progress">
      <div className="h-full bg-blue transition-[width] duration-500 ease-out" style={{ width: `${pct}%` }} />
    </div>
  );
}

function Empty({ picks, setPicks, signIn }: { picks: Picks; setPicks: (p: Picks) => void; signIn: string | null }) {
  const fixes = widen(picks);
  return (
    <EmptyState title={fixes.length ? "No repos match all of that." : "No repos match that. Try another language."}>
      {fixes.map((f, i) => (
        <button key={f.label} type="button" onClick={() => setPicks(f.picks)} className={i ? "text-link text-[0.9rem]" : "btn-primary"}>
          {f.label}
        </button>
      ))}
      {signIn && (
        <Link href={signIn} prefetch={false} className="text-link text-[0.9rem]">
          sign in to search GitHub <span aria-hidden="true">→</span>
        </Link>
      )}
    </EmptyState>
  );
}
