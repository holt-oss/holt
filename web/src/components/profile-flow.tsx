"use client";
// A first-time profile flow (not mounted yet; for /me): four quick questions, one at a time, big
// chips to tap. Each answer is saved as it's given, so leaving half-way still
// leaves something to pick from. The full form is in Settings → Profile.
import { useEffect, useRef, useState, useTransition } from "react";
import { finish, saveStep, skip } from "@/app/profile/actions";
import { CONTRIBUTIONS, LANGS, LEVELS, TIME } from "@/lib/profile";
import { after, answer, BLANK, current, progress, QUESTIONS, toggle, type FlowStep, type Prefs, type QuestionId } from "@/lib/profile-flow";
import { CatFace } from "./cat-face";

const CHOICES: Record<QuestionId, { value: string; label: string; hint?: string }[]> = {
  languages: LANGS.map((l) => ({ value: l.toLowerCase(), label: l })),
  days: TIME.map((t) => ({ value: String(t.days), label: t.label })),
  level: LEVELS.map((l) => ({ value: l.id, label: l.label, hint: l.hint })),
  contributions: CONTRIBUTIONS.map((c) => ({ value: c.id, label: c.label })),
};

const NOTE: Partial<Record<QuestionId, string>> = {
  languages: "Pick any. Holt only suggests repos written in these.",
  contributions: "Issues like these come first. Pick none for no preference.",
};

const CHIP =
  "min-h-12 border px-4 text-[0.92rem] transition-colors focus-visible:outline-2 focus-visible:outline-blue disabled:opacity-60";
const ON = "picked";
const OFF = "border-line-strong hover:border-blue";

export function ProfileFlow({ adultConfirmed, startAt = "start" }: { adultConfirmed: boolean; startAt?: FlowStep }) {
  const [step, setStep] = useState<FlowStep>(startAt);
  const [prefs, setPrefs] = useState<Prefs>(BLANK);
  // Multi-choice answers wait for "next"; single ones save on tap.
  const [picked, setPicked] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const heading = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);

  // Move focus to each new question, so keyboards and screen readers follow along.
  useEffect(() => {
    if (moved.current) heading.current?.focus();
    moved.current = true;
  }, [step]);

  function go(next: Prefs | null, from: FlowStep) {
    setError(null);
    const to = after(from);
    const land = () => {
      setStep(to);
      if (typeof to === "number") setPicked(current(next ?? prefs, QUESTIONS[to].id).filter(() => QUESTIONS[to].multi));
    };
    if (!next) return land();
    start(async () => {
      const r = await saveStep(next);
      if (!r.ok) {
        setError(r.adult ? "Profiles are for adults, so this can't be saved." : "That didn't save. Try again in a minute.");
        return;
      }
      setPrefs(next);
      land();
    });
  }

  const q = typeof step === "number" ? QUESTIONS[step] : null;

  return (
    <section id="profile-flow" aria-labelledby="flow-h" className="scroll-mt-24 border border-blue/50 bg-panel p-5 shadow-soft sm:p-6">
      <div className="flex items-center justify-between gap-4">
        <CatFace mood={step === "done" ? "celebrating" : q ? "thinking" : "ready"} className="text-[0.95rem]" />
        {q && (
          <span className="flex items-center gap-3 text-[0.85rem] text-faint">
            <span aria-hidden="true" className="flex gap-1">
              {QUESTIONS.map((_, i) => (
                <span key={i} className={`h-1 w-5 ${i <= (step as number) ? "bg-blue" : "bg-line"}`} />
              ))}
            </span>
            {progress(step as number)}
          </span>
        )}
      </div>

      <div aria-live="polite">
        {step === "start" && (
          <>
            <h2 id="flow-h" ref={heading} tabIndex={-1} className="mt-3 text-[1.2rem] font-semibold tracking-tight outline-none">
              Let Holt pick repos for you
            </h2>
            <p className="prose-sans mt-1 text-[0.95rem] text-muted">Four quick taps: your languages, how long you&apos;d wait for a reply, your experience, what you like doing.</p>
            {!adultConfirmed && <p className="mt-2 font-sans text-[0.89rem] text-faint">Profiles are for people 18 or older.</p>}
            <div className="mt-4 flex flex-wrap items-center gap-4">
              <button type="button" onClick={() => go(null, "start")} className="btn-primary">
                {adultConfirmed ? "start" : "I'm 18 or older, start"}
              </button>
              <SkipAll />
            </div>
          </>
        )}

        {q && (
          <>
            <h2 id="flow-h" ref={heading} tabIndex={-1} className="mt-3 text-[1.2rem] font-semibold tracking-tight outline-none">
              {q.title}
            </h2>
            {NOTE[q.id] && <p className="mt-1 font-sans text-[0.89rem] text-muted">{NOTE[q.id]}</p>}
            <div
              role="group"
              aria-labelledby="flow-h"
              className={`mt-4 ${q.id === "level" ? "grid gap-2 sm:grid-cols-2" : q.id === "days" ? "grid grid-cols-2 gap-2 sm:grid-cols-4" : "flex flex-wrap gap-2"}`}
            >
              {CHOICES[q.id].map((c) => {
                const on = q.multi ? picked.includes(c.value) : current(prefs, q.id).includes(c.value);
                return (
                  <button
                    key={c.value}
                    type="button"
                    disabled={pending}
                    aria-pressed={on}
                    onClick={() => (q.multi ? setPicked((p) => toggle(p, c.value)) : go(answer(prefs, q.id, c.value), step))}
                    className={`${CHIP} ${on ? ON : OFF} ${c.hint ? "flex flex-col items-start gap-1 py-3 text-left" : ""}`}
                  >
                    <span className={c.hint ? "font-semibold" : ""}>{c.label}</span>
                    {c.hint && <span className={`font-sans text-[0.87rem] ${on ? "" : "text-muted"}`}>{c.hint}</span>}
                  </button>
                );
              })}
            </div>
            {error && <p role="alert" className="mt-3 font-sans text-[0.9rem] text-orange">{error}</p>}
            <div className="mt-5 flex flex-wrap items-center gap-4">
              {q.multi && (
                <button type="button" disabled={pending} onClick={() => go(answer(prefs, q.id, picked), step)} className="btn-primary">
                  {pending ? "saving…" : step === QUESTIONS.length - 1 ? "done" : "next"}
                </button>
              )}
              <button type="button" disabled={pending} onClick={() => go(step === QUESTIONS.length - 1 ? prefs : null, step)} className="text-[0.89rem] text-muted hover:text-ink">
                skip this one
              </button>
              {!q.multi && pending && <span className="text-[0.89rem] text-faint">saving…</span>}
              <span className="ml-auto"><SkipAll /></span>
            </div>
          </>
        )}

        {step === "done" && (
          <>
            <h2 id="flow-h" ref={heading} tabIndex={-1} className="mt-3 text-[1.2rem] font-semibold tracking-tight outline-none">
              Saved. Your picks start from this now.
            </h2>
            <p className="prose-sans mt-1 text-[0.95rem] text-muted">Change it any time in Settings.</p>
            <form action={finish} className="mt-4">
              <button type="submit" className="bracket-link">[ here are repos picked for you → ]</button>
            </form>
          </>
        )}
      </div>
    </section>
  );
}

function SkipAll() {
  return (
    <form action={skip}>
      <input type="hidden" name="back" value="/me" />
      <button type="submit" className="text-[0.89rem] text-muted hover:text-ink">skip for now</button>
    </form>
  );
}
