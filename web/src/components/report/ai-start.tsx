"use client";

// The AI tab's first step: choose a model, then run the usual AI analysis.
import Link from "next/link";
import { useState } from "react";
import { availability, initialModel, MODELS, type ModelAccess } from "@/lib/models";
import type { Mode } from "@/lib/types";
import { AnalysisRunner } from "./analysis-runner";

const ACCESS_NOTE: Record<ModelAccess["kind"], string> = {
  free: "Free models use your monthly allowance. Pro models need a plan, or your own key.",
  plan: "Every model is included in your plan.",
  byok: "Your own key pays for these. Pick any model it supports.",
};

export function AiStart({ repo, days, signedIn, access, requested }: { repo: string; days: number; signedIn: boolean; access: ModelAccess; requested?: string }) {
  const [model, setModel] = useState(() => initialModel(access, requested));
  const [started, setStarted] = useState(false);

  if (started) return <AnalysisRunner repo={repo} mode={"ai" as Mode} days={days} signedIn={signedIn} model={model} />;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setStarted(true);
      }}
      className="border border-line-strong bg-panel p-5 shadow-card sm:p-8"
      data-model-picker
    >
      <p className="text-[0.72rem] uppercase tracking-[0.08em] text-blue">AI report · {repo}</p>
      <h1 className="mt-2 text-[1.6rem] font-semibold tracking-tight sm:text-[2rem]">Pick a model to write it</h1>
      <p className="mt-2 max-w-2xl font-sans text-muted">
        The verdict comes from the same fixed rules whichever you choose. The model only changes how the evidence is
        explained. {ACCESS_NOTE[access.kind]}
      </p>

      <fieldset className="mt-6">
        <legend className="sr-only">Model</legend>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {MODELS.map((m) => {
            const a = availability(m, access);
            const locked = !a.ok;
            const checked = model === m.id;
            return (
              <label
                key={m.id}
                className={`relative flex flex-col border p-4 transition-colors ${
                  locked
                    ? "cursor-not-allowed border-dashed border-line-strong opacity-75"
                    : "cursor-pointer border-line-strong bg-bg hover:border-blue has-[:checked]:border-blue has-[:checked]:bg-blue/10 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-blue"
                }`}
              >
                <input
                  type="radio"
                  name="model"
                  value={m.id}
                  checked={checked}
                  disabled={locked}
                  onChange={() => setModel(m.id)}
                  className="sr-only"
                />
                <span className="flex items-start justify-between gap-2">
                  <span>
                    <span className="block font-semibold text-ink">{m.label}</span>
                    <span className="block text-[0.72rem] text-faint">{m.vendor}</span>
                  </span>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-0.5 text-[0.66rem] uppercase tracking-[0.06em] ${
                      m.tier === "free" ? "border-green/50 text-green" : "border-blue/50 text-blue"
                    }`}
                  >
                    {m.tier}
                  </span>
                </span>
                <span className="mt-2 flex-1 font-sans text-[0.88rem] text-muted">{m.goodAt}</span>
                <span className="mt-3 flex items-center justify-between gap-2 text-[0.72rem]">
                  <span className="text-faint">{m.credits == null ? "credits: TBD" : `${m.credits} credits`}</span>
                  {locked ? (
                    a.reason === "upgrade" ? (
                      <span className="inline-flex items-center gap-1 text-blue">
                        <svg className="size-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
                          <rect x="5" y="11" width="14" height="10" rx="2" />
                          <path d="M8 11V7a4 4 0 0 1 8 0v4" />
                        </svg>
                        upgrade to use
                      </span>
                    ) : (
                      <span className="text-faint">not on your key</span>
                    )
                  ) : checked ? (
                    <span className="text-blue">✓ selected</span>
                  ) : null}
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-3">
        <button type="submit" className="btn-primary bg-blue">
          write my AI report <span aria-hidden="true">→</span>
        </button>
        {access.kind === "free" && (
          <span className="font-sans text-[0.85rem] text-muted">
            Want the pro models? <Link href="/pricing#compare" className="text-link">see plans</Link> or{" "}
            <Link href="/settings#byok" className="text-link">add your own key (free)</Link>.
          </span>
        )}
      </div>
    </form>
  );
}
