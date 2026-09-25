"use client";

import { useEffect, useState } from "react";
import type { ApiError, FindResult } from "@/lib/types";
import { AnalysisProgress } from "../analysis-progress";
import { ErrorPanel } from "../error-panel";
import { FindResults } from "./find-results";

/** Follows a queued /v1/find job (API.md allows 202 for slow searches). */
export function FindRunner({ jobId, days }: { jobId: string; days: number }) {
  const [stage, setStage] = useState({ stage: "Fetching pull requests", progress: 0.05 });
  const [results, setResults] = useState<FindResult[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    const src = new EventSource(`/api/find/${encodeURIComponent(jobId)}/events`);
    src.addEventListener("stage", (e) => setStage(JSON.parse((e as MessageEvent).data)));
    src.addEventListener("done", (e) => {
      src.close();
      const d = JSON.parse((e as MessageEvent).data);
      setResults(d.results ?? d.report?.results ?? []);
    });
    src.addEventListener("error", (e) => {
      src.close();
      const data = (e as MessageEvent).data;
      setError((data && JSON.parse(data).error) || { code: "upstream", message: "Lost the connection to the search. Try again." });
    });
    return () => src.close();
  }, [jobId]);

  if (error) return <ErrorPanel error={error} retryHref="/find" />;
  if (results) return <FindResults results={results} days={days} />;
  return <AnalysisProgress repo="" kicker="searching · welcoming projects" note="Holt is checking which projects reply to newcomers and have issues you could take. This can take a minute." mode="rules" stage={stage.stage} progress={stage.progress} />;
}
