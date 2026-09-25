"use client";

import { friendlyStage } from "@/lib/stages";
import { useAnalysis } from "../use-analysis";
import { CompareBody } from "./compare-card";

export function CompareLive({ repo }: { repo: string }) {
  const { state, retry } = useAnalysis(repo, "rules", 7);
  if (state.phase === "done") return <CompareBody report={state.report} />;
  if (state.phase === "error")
    return (
      <div className="p-4 font-sans text-[0.88rem]" role="alert">
        <p className="text-orange">{state.error.message}</p>
        {(state.error.code === "upstream" || state.error.code === "internal") && (
          <button type="button" onClick={retry} className="mt-3 text-[0.8rem] text-green underline">try again</button>
        )}
      </div>
    );
  const p = state.phase === "running" ? state.progress : 0.03;
  return (
    <div className="scan p-4" aria-live="polite" aria-busy="true">
      <p className="text-[0.85rem] text-ink">{friendlyStage(state.phase === "running" ? state.stage : undefined).title}…</p>
      <div className="mt-3 h-1 bg-panel-2">
        <div className="h-full bg-blue transition-[width] duration-500" style={{ width: `${Math.max(3, p * 100)}%` }} />
      </div>
      <p className="mt-3 font-sans text-[0.8rem] text-faint">First check takes about a minute.</p>
    </div>
  );
}
