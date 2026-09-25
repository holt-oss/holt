"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiError, Mode, Report } from "@/lib/types";

export type AnalysisState =
  | { phase: "starting" }
  | { phase: "running"; stage: string; progress: number }
  | { phase: "done"; report: Report }
  | { phase: "error"; error: ApiError };

const LOST: ApiError = { code: "upstream", message: "We lost the connection while the report was running. It may have finished; try again." };

/** Start (or reuse) an analysis and follow its progress over SSE. */
export function useAnalysis(repo: string, mode: Mode, days: number, enabled = true) {
  const [state, setState] = useState<AnalysisState>({ phase: "starting" });
  const [attempt, setAttempt] = useState(0);
  const es = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    (async () => {
      let res: Response;
      try {
        res = await fetch("/api/analyses", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ repo, mode, days }),
        });
      } catch {
        if (!cancelled) setState({ phase: "error", error: LOST });
        return;
      }
      const body = await res.json().catch(() => null);
      if (cancelled) return;
      if (!res.ok) {
        setState({ phase: "error", error: body?.error ?? LOST });
        return;
      }
      if (body.status === "done") {
        setState({ phase: "done", report: body.report });
        return;
      }
      setState({ phase: "running", stage: "Getting in line", progress: 0.02 });
      const src = new EventSource(`/api/analyses/${encodeURIComponent(body.job_id)}/events`);
      es.current = src;
      src.addEventListener("stage", (e) => {
        const d = JSON.parse((e as MessageEvent).data);
        setState({ phase: "running", stage: d.stage, progress: d.progress ?? 0 });
      });
      src.addEventListener("done", (e) => {
        src.close();
        setState({ phase: "done", report: JSON.parse((e as MessageEvent).data).report });
      });
      src.addEventListener("error", (e) => {
        const data = (e as MessageEvent).data;
        src.close();
        let error = LOST;
        if (data) {
          try {
            error = JSON.parse(data).error ?? LOST;
          } catch {}
        }
        setState((s) => (s.phase === "done" ? s : { phase: "error", error }));
      });
    })();
    return () => {
      cancelled = true;
      es.current?.close();
    };
  }, [repo, mode, days, attempt, enabled]);

  const retry = useCallback(() => {
    setState({ phase: "starting" });
    setAttempt((a) => a + 1);
  }, []);
  return { state, retry };
}
