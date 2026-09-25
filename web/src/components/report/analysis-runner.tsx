"use client";

import { useEffect, useState } from "react";
import type { Mode } from "@/lib/types";
import { AnalysisProgress } from "../analysis-progress";
import { ErrorPanel } from "../error-panel";
import { useAnalysis } from "../use-analysis";
import { ReportView } from "./report-view";
import type { IssuesState } from "./starter-issues";

export function AnalysisRunner({ repo, mode, days, signedIn, initialIssues }: { repo: string; mode: Mode; days: number; signedIn: boolean; initialIssues: IssuesState }) {
  const { state, retry } = useAnalysis(repo, mode, days);
  const [issues, setIssues] = useState<IssuesState>(initialIssues);

  useEffect(() => {
    if (state.phase !== "done" || issues) return;
    fetch(`/api/repos/${repo}/starter-issues`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setIssues(d?.issues ?? "unavailable"))
      .catch(() => setIssues("unavailable"));
  }, [state.phase, repo, issues]);

  if (state.phase === "error") return <ErrorPanel error={state.error} repo={repo} onRetry={retry} />;
  if (state.phase === "done") return <ReportView report={state.report} issues={issues} signedIn={signedIn} />;
  return <AnalysisProgress repo={repo} mode={mode} stage={state.phase === "running" ? state.stage : undefined} progress={state.phase === "running" ? state.progress : 0.02} />;
}
