"use client";

// A running check, printed as a log (the expressive design plan, pattern 8):
// each stage Holt reaches prints a line, a finished one gets a tick and how
// long it took, and the cat thinks while it works. The box keeps one height
// from the start (the last six lines show), so nothing below it moves. Screen
// readers hear only the current stage, never the ticking times.
import { useEffect, useState } from "react";
import { eta, logStage, stageTime } from "@/lib/stages";
import { ReactiveCat } from "./reactive-cat";

const LINES = 6;

/** `ahead`: the check's place in the queue while it waits. `estimate`: show how long is left. */
export function AnalysisProgress({ repo, stage, progress, mode, kicker, note, ahead, estimate = false }: { repo: string; stage?: string; progress: number; mode: "rules" | "ai"; kicker?: string; note?: React.ReactNode; ahead?: number; estimate?: boolean }) {
  // Whole seconds since this screen appeared: the log's clock.
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t0 = performance.now();
    const id = window.setInterval(() => setElapsed(Math.floor((performance.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  // Each new stage adds a line (adjusting state during render, not in an effect).
  const [log, setLog] = useState(() => logStage([], stage, 0));
  const lines = logStage(log, stage, elapsed);
  if (lines !== log) setLog(lines);

  const current = lines[lines.length - 1];
  const shown = lines.slice(-LINES);
  // Counted from the first stage past the queue; in the queue, from its place in line.
  const queued = current.title === "Getting in line";
  const began = lines.find((l) => l.title !== "Starting" && l.title !== "Getting in line")?.at ?? elapsed;
  const left = estimate ? (queued ? eta({ mode, elapsed: 0, ahead }) : eta({ mode, elapsed: elapsed - began })) : null;
  const scale = Math.min(1, Math.max(0.03, progress));
  return (
    <div className="scan border border-line-strong bg-panel p-5 shadow-card sm:p-7" aria-busy="true">
      {/* Phones: the cat sits above the text so the headline gets the full width. */}
      <div className="flex flex-col-reverse items-start gap-3 sm:flex-row sm:justify-between sm:gap-4">
        <div className="min-w-0">
          <p className="break-words text-[0.76rem] uppercase tracking-[0.08em] text-faint">{kicker ?? `checking · ${repo}`}</p>
          {/* Room for the longest stage and detail from the start (two lines of
              each on phones), so a new stage never pushes the log down. A
              section-sized heading, not a page title: people watch this often. */}
          <h1 className="mt-2 min-h-[2.5em] text-[1.2rem] font-semibold leading-tight tracking-tight sm:min-h-0 sm:text-[1.4rem]">{current.title}…</h1>
          <p className="mt-1.5 min-h-[3em] max-w-lg font-sans text-[0.92rem] leading-normal text-muted sm:min-h-[1.5em]">{current.detail}</p>
        </div>
        <ReactiveCat mood="thinking" className="shrink-0 text-[1.2rem] sm:text-[1.5rem]" />
      </div>
      <p className="sr-only" aria-live="polite">
        {current.title}. {current.detail}
      </p>

      <div className="mt-5 border border-line bg-bg px-4 py-3 text-[0.82rem] leading-[1.9] sm:px-5 sm:text-[0.85rem]" data-progress-log>
        {repo && (
          <p className="truncate text-muted">
            <span aria-hidden="true" className="text-amber">$ </span>
            holt analyze {repo} --live{mode === "rules" ? " --no-model" : ""}
          </p>
        )}
        <ol aria-label="What Holt has done so far" className="h-[calc(6*1.9em)] overflow-hidden">
          {shown.map((l, i) => {
            const now = l === current;
            const took = (now ? elapsed : shown[i + 1].at) - l.at;
            return (
              <li key={l.title} className={`plog-line flex gap-3 ${now ? "text-ink" : "text-muted"}`}>
                <span aria-hidden="true" className={`w-4 shrink-0 text-center ${now ? "text-blue" : "text-ink"}`}>
                  {now ? "▸" : "✓"}
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {l.title}
                  {now && <span aria-hidden="true" className="plog-caret" />}
                  <span className="sr-only">{now ? " (in progress)" : " (done)"}</span>
                </span>
                <span aria-hidden="true" className="shrink-0 tabular-nums text-faint">
                  {stageTime(took)}
                </span>
              </li>
            );
          })}
        </ol>
        <div className="mt-2 h-1 bg-panel-2" role="progressbar" aria-valuenow={Math.round(scale * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Progress" aria-valuetext={left ?? undefined}>
          <div className="plog-bar h-full origin-left bg-blue" style={{ transform: `scaleX(${scale})` }} />
        </div>
        {estimate && (
          <p aria-hidden="true" className="mt-1 h-[1.9em] text-right text-[0.76rem] tabular-nums text-faint">
            {left}
          </p>
        )}
      </div>
      <p className="mt-5 border-t border-dashed border-line pt-3 font-sans text-[0.85rem] text-faint">
        {note ?? "The first check of a repo takes about 20 seconds. After that it's instant for everyone for a day."}
      </p>
    </div>
  );
}
