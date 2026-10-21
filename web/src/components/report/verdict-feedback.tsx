"use client";

import { useId, useState, useSyncExternalStore } from "react";
import { feedbackKey, REASON_MAX, type Vote } from "@/lib/feedback";
import type { Report } from "@/lib/types";

type Saved = { vote: Vote; reason: string | null };
type Status = "idle" | "sending" | "error";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function parse(raw: string | null): Saved | null {
  try {
    const v = JSON.parse(raw || "null") as Saved | null;
    return v && (v.vote === "up" || v.vote === "down") ? v : null;
  } catch {
    return null;
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

function store(key: string, saved: Saved) {
  try {
    localStorage.setItem(key, JSON.stringify(saved));
  } catch {
    // private mode: the answer is still saved on the server
  }
}

/** 👍, or 👎 when `down`: drawn, so it looks the same without an emoji font. */
function Thumb({ down }: { down?: boolean }) {
  return (
    <svg className={`size-4 ${down ? "rotate-180" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M7 10v11M7 10l4-8a2.5 2.5 0 0 1 2.5 2.5V9h5.2a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 17.3 21H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h3" />
    </svg>
  );
}

/**
 * "Was this verdict right?" under the report. Anyone can answer; answering
 * again changes the answer for this version of the report.
 */
export function VerdictFeedback({ report }: { report: Pick<Report, "repo" | "mode" | "days" | "generated_at"> }) {
  const key = feedbackKey(report.repo, report.mode, report.days, report.generated_at);
  // A new version of the report starts fresh.
  return <Feedback key={key} storageKey={key} report={report} />;
}

function Feedback({ storageKey: key, report }: { storageKey: string; report: Pick<Report, "repo" | "mode" | "days" | "generated_at"> }) {
  const { repo, mode, days, generated_at } = report;
  // What this browser answered before, for this version of the report; then
  // whatever is answered here.
  const remembered = useSyncExternalStore(subscribe, () => read(key), () => null);
  const [mine, setSaved] = useState<Saved | null>(null);
  const saved = mine ?? parse(remembered);
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const reasonId = useId();

  async function send(vote: Vote, reason: string | null): Promise<boolean> {
    setStatus("sending");
    setError("");
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo, mode, days, generated_at, vote, reason }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.error?.message || "That didn't go through. Try again.");
      const next: Saved = { vote, reason: body?.reason ?? null };
      setSaved(next);
      store(key, next);
      setStatus("idle");
      return true;
    } catch (e) {
      setError(e instanceof Error && e.message !== "Failed to fetch" ? e.message : "That didn't go through. Try again.");
      setStatus("error");
      return false;
    }
  }

  async function choose(vote: Vote) {
    if (status === "sending" || saved?.vote === vote) return;
    // A new answer starts without the old reason: it was about the other one.
    if (await send(vote, null)) {
      setDraft("");
      setEditing(true);
    }
  }

  async function submitReason(e: React.FormEvent) {
    e.preventDefault();
    if (!saved || status === "sending") return;
    if (await send(saved.vote, draft)) setEditing(false);
  }

  const busy = status === "sending";
  const btn = (vote: Vote, label: string) => {
    const on = saved?.vote === vote;
    return (
      <button
        type="button"
        onClick={() => choose(vote)}
        aria-pressed={on}
        disabled={busy}
        className={`inline-flex min-h-11 items-center gap-2 border px-4 text-[0.89rem] transition-colors disabled:opacity-60 ${
          on ? "picked" : "border-line-strong text-muted hover:border-ink hover:text-ink"
        }`}
      >
        <Thumb down={vote === "down"} />
        {label}
      </button>
    );
  };

  return (
    <section aria-labelledby={`${reasonId}-q`} className="border border-line-strong p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h2 id={`${reasonId}-q`} className="text-[0.98rem] font-semibold tracking-tight">
            Was this verdict right?
          </h2>
          <p className="mt-1 font-sans text-[0.89rem] text-muted">Know this project? Tell us. It helps us get verdicts right.</p>
        </div>
        <div className="flex gap-2">
          {btn("up", "Yes")}
          {btn("down", "No")}
        </div>
      </div>

      {saved && editing && (
        <form onSubmit={submitReason} className="mt-4">
          <label htmlFor={reasonId} className="block font-sans text-[0.89rem] text-muted">
            Thanks! Want to say why? <span className="text-faint">(optional)</span>
          </label>
          <textarea
            id={reasonId}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={REASON_MAX}
            rows={2}
            placeholder={saved.vote === "up" ? "e.g. I had a first PR merged here within a week" : "e.g. They do merge outside work, just slowly"}
            className="mt-2 block w-full resize-y border border-line-strong bg-panel px-3 py-2 font-sans text-[0.95rem] text-ink placeholder:text-faint focus:border-blue focus:outline-none"
          />
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <button type="submit" disabled={busy || (!draft.trim() && !saved.reason)} className="btn-ghost disabled:opacity-60">
              {busy ? "sending…" : "send"}
            </button>
            <button type="button" onClick={() => setEditing(false)} className="text-[0.87rem] text-faint hover:text-ink">
              skip
            </button>
          </div>
        </form>
      )}

      <p className="mt-3 font-sans text-[0.88rem] empty:mt-0" aria-live="polite">
        {status === "error" ? (
          <span className="text-orange">{error}</span>
        ) : saved && !editing ? (
          <span className="text-faint">
            Thanks, we saved your answer{saved.reason ? " and your reason" : ""}.{" "}
            <button type="button" onClick={() => { setDraft(saved.reason ?? ""); setEditing(true); }} className="underline decoration-dotted underline-offset-2 hover:text-ink">
              {saved.reason ? "edit your reason" : "add a reason"}
            </button>
          </span>
        ) : null}
      </p>
    </section>
  );
}
