"use client";

import { startTransition, useEffect, useState, ViewTransition } from "react";
import type { ApiError, FindResult } from "@/lib/types";
import { AnalysisProgress } from "../analysis-progress";
import { ErrorPanel } from "../error-panel";
import { FindResults } from "./find-results";

/** Follows a queued /v1/find job (API.md allows 202 for slow searches). */
export function FindRunner({ jobId, days, retryHref = "/find" }: { jobId: string; days: number; retryHref?: string }) {
  const [stage, setStage] = useState({ stage: "Fetching pull requests", progress: 0.05 });
  const [results, setResults] = useState<FindResult[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    const src = new EventSource(`/api/find/${encodeURIComponent(jobId)}/events`);
    src.addEventListener("stage", (e) => setStage(JSON.parse((e as MessageEvent).data)));
    src.addEventListener("done", (e) => {
      src.close();
      const d = JSON.parse((e as MessageEvent).data);
      // A transition, so the progress panel crossfades into the list.
      startTransition(() => setResults(d.results ?? d.report?.results ?? []));
    });
    src.addEventListener("error", (e) => {
      src.close();
      const data = (e as MessageEvent).data;
      setError((data && JSON.parse(data).error) || { code: "upstream", message: "Lost the connection to the search. Try again." });
    });
    return () => src.close();
  }, [jobId]);

  if (error) return <ErrorPanel error={error} retryHref={retryHref} />;
  if (results)
    return (
      <ViewTransition enter="sk-in" default="none">
        <div>
          <FindResults results={results} days={days} />
        </div>
      </ViewTransition>
    );
  return (
    <ViewTransition exit="sk-out" default="none">
      <div>
        <AnalysisProgress repo="" kicker="searching · welcoming projects" note="Holt is checking which projects reply to newcomers and have issues you could take. This can take a minute." mode="rules" stage={stage.stage} progress={stage.progress} />
      </div>
    </ViewTransition>
  );
}
