"use client";
// Get-a-badge for a repo Holt hasn't checked recently: run the free check here,
// then show the same answer as for a cached report.
import { friendlyStage } from "@/lib/stages";
import { useAnalysis } from "../use-analysis";
import { BadgeResult } from "./badge-result";

export function BadgeLive({ repo, site }: { repo: string; site: string }) {
  const { state, retry } = useAnalysis(repo, "rules", 7);
  if (state.phase === "done") return <BadgeResult report={state.report} site={site} />;
  if (state.phase === "error")
    return (
      <div className="panel p-5 font-sans text-[0.92rem]" role="alert">
        <p className="text-orange">{state.error.message}</p>
        {(state.error.code === "upstream" || state.error.code === "internal") && (
          <button type="button" onClick={retry} className="mt-3 min-h-11 text-[0.89rem] text-ink underline">try again</button>
        )}
      </div>
    );
  const p = state.phase === "running" ? state.progress : 0.03;
  return (
    <div className="panel scan p-5" aria-live="polite" aria-busy="true">
      <p className="text-[0.9rem] text-ink">Checking {repo}: {friendlyStage(state.phase === "running" ? state.stage : undefined).title}…</p>
      <div className="mt-3 h-1 bg-panel-2">
        <div className="h-full bg-blue transition-[width] duration-500" style={{ width: `${Math.max(3, p * 100)}%` }} />
      </div>
      <p className="mt-3 font-sans text-[0.87rem] text-faint">A first check takes about 20 seconds.</p>
    </div>
  );
}
