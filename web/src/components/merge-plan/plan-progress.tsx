"use client";
// A merge plan being made, in the free check's style (analysis-progress.tsx):
// a live log where each stage prints a line and a finished one gets a tick and
// its time, a scanning progress bar and the thinking cat. Beside it, the plan
// taking shape: its five sections, each lit when the server is on the stage
// that writes it and ticked once that stage is past. Only what the server says
// moves anything; nothing here pretends to be further along than it is.
// Screen readers hear the current stage only.
import { useEffect, useState } from "react";
import { stageTime } from "@/lib/stages";
import { ReactiveCat } from "../reactive-cat";

const LINES = 6;

/** The server's stage (server/holt_server/merge_plan.py) in plain words, with a line of context, and which step of the plan it is. */
const STEPS: { match: RegExp; title: string; detail: string; step: number }[] = [
  { match: /^starting|getting in line|queue/i, title: "Getting in line", detail: "Your plan starts as soon as the one before it is done.", step: 0 },
  { match: /report and starter issues/i, title: "Reading the report and starter issues", detail: "The verdict, the numbers and the open issues worth starting on.", step: 1 },
  { match: /recent pull requests/i, title: "Reading the recent pull requests", detail: "The last few months of work from people outside the team.", step: 2 },
  { match: /counting/i, title: "Counting replies and merges", detail: "Who got an answer, who got merged, and how long it took.", step: 2 },
  { match: /threads/i, title: "Reading the pull request threads", detail: "What maintainers said, and how each newcomer's PR ended.", step: 2 },
  { match: /what the ai found/i, title: "Checking what the AI found", detail: "Every finding has to link to a real comment, or it's dropped.", step: 2 },
  { match: /year of merged/i, title: "Writing your plan", detail: "A year of merged and closed pull requests, turned into steps for yours.", step: 3 },
];

function planStage(stage: string): { title: string; detail: string; step: number } {
  for (const s of STEPS) if (s.match.test(stage)) return s;
  return { title: stage, detail: "", step: 1 };
}

/** The plan's sections, and the step that writes each (3: the last one writes the rest together). */
const SECTIONS: { label: string; step: number }[] = [
  { label: "What the AI found", step: 2 },
  { label: "Your first pull request", step: 3 },
  { label: "What gets merged", step: 3 },
  { label: "What gets closed", step: 3 },
  { label: "Who reviews", step: 3 },
];

type Line = { title: string; at: number };

export function PlanProgress({ repo, stage, progress }: { repo: string; stage: string; progress: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const t0 = performance.now();
    const id = window.setInterval(() => setElapsed(Math.floor((performance.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  const now = planStage(stage);
  // Each new stage prints a line; one already passed never prints again.
  const [log, setLog] = useState<Line[]>(() => [{ title: now.title, at: 0 }]);
  if (!log.some((l) => l.title === now.title)) setLog([...log, { title: now.title, at: elapsed }]);

  const shown = log.slice(-LINES);
  const scale = Math.min(1, Math.max(0.03, progress));

  return (
    <div className="scan mt-5 border border-line-strong bg-panel p-5 sm:p-7" aria-busy="true" data-merge-plan-making>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-[0.76rem] uppercase tracking-[0.08em] text-faint">writing your merge plan · {repo}</p>
          <h2 className="mt-2 min-h-[2.5em] text-[1.2rem] font-semibold leading-tight tracking-tight sm:min-h-0 sm:text-[1.4rem]">
            {now.title}
            <span aria-hidden="true" className="plog-caret" />
          </h2>
          <p className="mt-1.5 min-h-[3em] max-w-lg font-sans text-[0.92rem] leading-normal text-muted sm:min-h-[1.5em]">{now.detail}</p>
        </div>
        <ReactiveCat mood="thinking" className="shrink-0 text-[1.2rem] sm:text-[1.5rem]" />
      </div>
      <p className="sr-only" aria-live="polite">
        {now.title}. {now.detail}
      </p>

      <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_17rem]">
        {/* The log. */}
        <div className="border border-line bg-bg px-4 py-3 text-[0.82rem] leading-[1.9] sm:px-5 sm:text-[0.85rem]">
          <p className="truncate text-muted">
            <span aria-hidden="true" className="text-amber">$ </span>
            holt plan {repo} --pro
          </p>
          <ol aria-label="What Holt has done so far" className="h-[calc(6*1.9em)] overflow-hidden">
            {shown.map((l, i) => {
              const live = i === shown.length - 1;
              const took = (live ? elapsed : shown[i + 1].at) - l.at;
              return (
                <li key={l.title} className={`plog-line flex gap-3 ${live ? "text-ink" : "text-muted"}`}>
                  <span aria-hidden="true" className={`w-4 shrink-0 text-center ${live ? "text-blue" : "text-ink"}`}>{live ? "▸" : "✓"}</span>
                  <span className="min-w-0 flex-1 truncate">
                    {l.title}
                    <span className="sr-only">{live ? " (in progress)" : " (done)"}</span>
                  </span>
                  <span aria-hidden="true" className="shrink-0 tabular-nums text-faint">{stageTime(took)}</span>
                </li>
              );
            })}
          </ol>
          <div className="mt-2 h-1 overflow-hidden bg-panel-2" role="progressbar" aria-valuenow={Math.round(scale * 100)} aria-valuemin={0} aria-valuemax={100} aria-label="Progress">
            <div className="plog-bar plan-bar h-full origin-left bg-blue" style={{ transform: `scaleX(${scale})` }} />
          </div>
          <p aria-hidden="true" className="mt-1 flex justify-between text-[0.76rem] tabular-nums text-faint">
            <span>{Math.round(scale * 100)}%</span>
            <span>{stageTime(elapsed)}</span>
          </p>
        </div>

        {/* The plan taking shape. */}
        <div aria-hidden="true" className="border border-line bg-bg p-4">
          <p className="mb-3 text-[0.72rem] uppercase tracking-[0.08em] text-faint">Your plan, taking shape</p>
          <ol className="space-y-2">
            {SECTIONS.map((s, i) => {
              const state = now.step > s.step ? "done" : now.step === s.step ? "live" : "wait";
              return (
                <li key={s.label} className="plan-shape flex items-center gap-2.5" data-state={state}>
                  <span className={`text-[0.72rem] tabular-nums ${state === "wait" ? "text-faint" : "text-blue"}`}>{String(i + 1).padStart(2, "0")}</span>
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate text-[0.82rem] ${state === "wait" ? "text-faint" : "text-ink"}`}>{s.label}</span>
                    <span className="plan-shape-lines mt-1 flex gap-1">
                      <span className="sk h-1 w-3/5" />
                      <span className="sk h-1 w-1/4" />
                    </span>
                  </span>
                  <span className={`w-4 shrink-0 text-center text-[0.8rem] ${state === "done" ? "text-ink" : "text-blue"}`}>
                    {state === "done" ? "✓" : state === "live" ? <span className="plan-dot" /> : ""}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      </div>

      <p className="mt-5 border-t border-dashed border-line pt-3 font-sans text-[0.85rem] text-faint">
        You can leave this page: the plan keeps going, and it&apos;s here when you come back.
      </p>
    </div>
  );
}
