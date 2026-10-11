"use client";

// "Your first pull request" as a horizontal timeline: six numbered nodes on
// one track, the line between them filling green as steps get done, each
// node's title under it. Choosing a node opens that step below: what to do,
// the comment to post, its sources, and "mark as done". Ticks are a
// per-visitor convenience kept in this browser only (localStorage), so the
// page renders the same without them.
import { useMemo, useState, useSyncExternalStore } from "react";
import { CopyButton } from "@/components/copy-button";
import type { PlanStep } from "@/lib/merge-plan";
import { PlanText, Sources } from "./plan-bits";

const key = (repo: string) => `holt:plan-steps:${repo}`;
const listeners = new Set<() => void>();

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  window.addEventListener("storage", onChange); // other tabs
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function read(repo: string): string {
  try {
    return localStorage.getItem(key(repo)) ?? "[]";
  } catch {
    return "[]";
  }
}

/** A step title without Markdown backticks, for the short labels on the track. */
const plain = (s: string) => s.replace(/`/g, "");

export function PlanSteps({ repo, steps, show = steps.length }: { repo: string; steps: PlanStep[]; show?: number }) {
  const raw = useSyncExternalStore(subscribe, () => read(repo), () => "[]");
  const done = useMemo(() => {
    let saved: unknown = [];
    try {
      saved = JSON.parse(raw);
    } catch {}
    return steps.map((_, i) => Array.isArray(saved) && saved[i] === true);
  }, [raw, steps]);
  const [picked, setPicked] = useState<number | null>(null);

  const setDone = (i: number, value: boolean) => {
    try {
      localStorage.setItem(key(repo), JSON.stringify(done.map((d, j) => (j === i ? value : d))));
    } catch {}
    listeners.forEach((l) => l());
  };

  const locked = show < steps.length;
  const count = done.filter(Boolean).length;
  const firstOpen = done.findIndex((d) => !d);
  const active = locked ? 0 : (picked ?? (firstOpen === -1 ? steps.length - 1 : firstOpen));
  const step = steps[active];
  // How far the track is filled: up to the last step that's done.
  const lastDone = done.lastIndexOf(true);
  const fill = steps.length > 1 && lastDone >= 0 ? (lastDone / (steps.length - 1)) * 100 : 0;

  return (
    <div>
      <div className="mb-8 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        {locked && <p className="font-sans text-[0.95rem] text-muted">{steps.length} steps. The first one is free.</p>}
        {!locked && (
          <p className="text-[0.8rem] uppercase tracking-[0.08em] text-faint" aria-live="polite">
            {count === steps.length ? "all done · open your PR" : `${count} of ${steps.length} done`}
          </p>
        )}
      </div>

      {/* The track. */}
      <div className="relative">
        <div aria-hidden="true" className="absolute top-5 h-0.5 bg-line-strong" style={{ left: `calc(100% / ${steps.length * 2})`, right: `calc(100% / ${steps.length * 2})` }}>
          <div className="h-full bg-ink transition-[width] duration-500 ease-out" style={{ width: `${fill}%` }} />
        </div>
        <ol className="relative grid" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }} role="tablist" aria-label="Steps">
          {steps.map((s, i) => {
            const isActive = i === active;
            const isLocked = locked && i > 0;
            return (
              <li key={i} className="flex flex-col items-center px-1 text-center">
                <button
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  aria-controls="plan-step-panel"
                  disabled={isLocked}
                  onClick={() => setPicked(i)}
                  className={`relative grid size-10 place-items-center rounded-full border-2 text-[0.95rem] font-semibold tabular-nums transition-[background-color,border-color,box-shadow] duration-200 disabled:cursor-not-allowed ${
                    done[i]
                      ? "border-ink bg-ink text-on-accent"
                      : isActive
                        ? "border-blue bg-panel text-blue shadow-[0_0_0_5px_color-mix(in_oklab,var(--blue)_16%,transparent)]"
                        : "border-line-strong bg-panel text-muted hover:border-ink hover:text-ink"
                  }`}
                >
                  <span aria-hidden="true">{isLocked ? "·" : done[i] ? "✓" : i + 1}</span>
                  <span className="sr-only">
                    Step {i + 1}: {plain(s.title)}
                    {done[i] ? " (done)" : ""}
                  </span>
                </button>
                <p
                  aria-hidden="true"
                  className={`mt-3 hidden max-w-[16ch] text-[0.82rem] leading-snug md:block ${isActive ? "font-semibold text-ink" : isLocked ? "text-faint" : "text-muted"}`}
                >
                  {isLocked ? "locked" : plain(s.title)}
                </p>
              </li>
            );
          })}
        </ol>
      </div>

      {/* The chosen step. */}
      <div
        id="plan-step-panel"
        role="tabpanel"
        className="relative mt-8 overflow-hidden border border-line-strong bg-panel shadow-card"
      >
        <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-1 ${done[active] ? "bg-ink" : "bg-blue"}`} />
        <div key={active} className="p-5 pl-6 sm:p-8 sm:pl-10">
          <p className="text-[0.8rem] uppercase tracking-[0.08em] text-faint">
            step {active + 1} of {steps.length}
            {done[active] && <span className="text-ink"> · done</span>}
          </p>
          <h3 className="mt-2 text-[1.3rem] font-semibold leading-snug tracking-tight sm:text-[1.6rem]">
            <PlanText text={step.title} />
          </h3>
          {step.detail && (
            <p className="mt-3 max-w-[70ch] font-sans text-[1.02rem] leading-relaxed text-muted">
              <PlanText text={step.detail} />
            </p>
          )}
          {step.copy && (
            <div className="mt-5 max-w-[760px] border border-line-strong bg-bg">
              <div className="flex items-center justify-between border-b border-line-strong pl-4">
                <span className="text-[0.75rem] uppercase tracking-[0.08em] text-faint">{step.copy.label}</span>
                <CopyButton text={step.copy.text} className="self-stretch border-l border-line-strong px-4 py-2 text-[0.85rem] text-muted transition-colors hover:bg-ink hover:text-on-accent" />
              </div>
              <p className="px-4 py-3 font-sans text-[0.98rem] leading-relaxed text-ink">{step.copy.text}</p>
            </div>
          )}
          {step.link && (
            <a href={step.link.url} target="_blank" rel="noopener noreferrer" className="text-link mt-4 inline-flex min-h-9 items-center text-[0.88rem]">
              {step.link.label} ↗
            </a>
          )}
          <Sources sources={step.sources} className="mt-3" />

          {!locked && (
            <div className="mt-7 flex flex-wrap items-center gap-3 border-t border-dashed border-line-strong pt-5">
              <button
                type="button"
                onClick={() => {
                  setDone(active, !done[active]);
                  if (!done[active] && active < steps.length - 1) setPicked(active + 1);
                }}
                className={done[active] ? "btn-ghost" : "btn-primary"}
              >
                {done[active] ? "mark as not done" : active < steps.length - 1 ? "done, next step →" : "done ✓"}
              </button>
              <span className="ml-auto flex gap-2">
                <button type="button" className="btn-ghost" disabled={active === 0} onClick={() => setPicked(active - 1)}>
                  ← previous
                </button>
                <button type="button" className="btn-ghost" disabled={active === steps.length - 1} onClick={() => setPicked(active + 1)}>
                  next →
                </button>
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
