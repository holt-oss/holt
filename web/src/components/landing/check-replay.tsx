"use client";

// "Watch Holt check a repo" (landing section 02, the expressive design plan
// pattern 3). A recorded check plays when it's reached, in either of two
// places: on the web (the progress log, then the report's verdict landing)
// or in your terminal (`holt analyze`'s own output for the same run). The
// numbers are the example report's (lib/landing-replay.ts).
//
// Both modes sit in one grid cell and every line is always laid out, so the
// box never changes height (no layout shift) and switching modes never jumps.
// The server HTML is the finished state; it's wound back only when it starts
// below the fold. Reduced motion: the finished state, and no replay button.
import { useEffect, useState } from "react";
import type { CatMood } from "@/lib/cat";
import { countAt, countParts, settle } from "@/lib/count-up";
import { plainLine, type Replay, type ReplayLine } from "@/lib/landing-replay";
import { ReactiveCat } from "../reactive-cat";
import { useReducedMotion, useSeen } from "../motion/use-seen";

type Mode = "web" | "terminal";

const TONE_TEXT = { good: "text-green", bad: "text-orange", warn: "text-amber", neutral: "text-ink" } as const;
const TONE_BG = { good: "bg-green", bad: "bg-orange", warn: "bg-amber", neutral: "bg-blue" } as const;
const MOOD: Record<Replay["tone"], CatMood> = { good: "celebrating", bad: "heartbroken", warn: "thinking", neutral: "ready" };
const LINE_STYLE: Record<NonNullable<ReplayLine["style"]>, string> = {
  heading: "font-semibold text-ink",
  verdict: "font-semibold text-green",
  faint: "text-faint",
  good: "text-muted",
  bad: "text-muted",
};

const TYPE_MS = 24;
const LINE_MS = 330;

/** When each step of a mode happens, in ms from the start. The last step is "done". */
function schedule(mode: Mode, r: Replay): number[] {
  if (mode === "web") {
    // Three stages print, then the verdict lands, then its numbers count.
    return [350, 950, 1550, 2250, 2600];
  }
  const typed = Array.from({ length: r.command.length }, (_, i) => 300 + (i + 1) * TYPE_MS);
  const start = 300 + r.command.length * TYPE_MS + 350;
  const lines = r.terminal.map((_, j) => start + j * LINE_MS);
  return [...typed, ...lines, start + r.terminal.length * LINE_MS + 250];
}

export function CheckReplay({ replay }: { replay: Replay }) {
  const reduced = useReducedMotion();
  const { ref, seen, below } = useSeen<HTMLDivElement>();
  const [mode, setMode] = useState<Mode>("web");
  const [run, setRun] = useState(0);
  // How far this run of this mode has got. A new run starts from 0.
  const key = `${mode}-${run}`;
  const [step, setStep] = useState({ key: "", n: 0 });
  const armed = !reduced && (below || run > 0);
  const playing = armed && (seen || run > 0);
  const last = schedule(mode, replay).length;

  useEffect(() => {
    if (!playing) return;
    const timers = schedule(mode, replay).map((t, i) => window.setTimeout(() => setStep({ key, n: i + 1 }), t));
    return () => timers.forEach(clearTimeout);
  }, [playing, key, mode, replay]);

  // Not armed: the finished state (the server HTML). Armed: wound back until it plays.
  const at = !armed ? Infinity : step.key === key ? step.n : 0;
  const done = at >= last;
  const busy = armed && !done && at > 0;

  const restart = (m: Mode) => {
    setMode(m);
    setRun((n) => n + 1);
  };

  const mood: CatMood = done ? MOOD[replay.tone] : busy ? "thinking" : "ready";

  return (
    <div ref={ref} className="ls-replay border border-line-strong bg-panel shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-3 py-2 sm:px-4">
        <div role="group" aria-label="Where to watch the check" className="ls-modes relative grid grid-cols-2 border border-line-strong text-[0.82rem]">
          <span aria-hidden="true" className="ls-modes-pill absolute inset-y-0 left-0 w-1/2 bg-ink" data-mode={mode} />
          {(["web", "terminal"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => (reduced ? setMode(m) : restart(m))}
              className={`relative min-h-11 px-3 transition-colors sm:px-4 ${mode === m ? "text-bg" : "text-muted hover:text-ink"}`}
            >
              {m === "web" ? "on the web" : "in your terminal"}
            </button>
          ))}
        </div>
        <ReactiveCat mood={mood} className="text-[1.15rem]" />
      </div>

      {/* The whole check, in words, whatever the animation is showing. */}
      <p className="sr-only">
        {mode === "web"
          ? `Checking ${replay.repo} on the web: ${replay.stages.join(", ")}. Verdict: ${replay.headline}. ${replay.line} ${replay.stats.map((s) => `${s.big} ${s.label}`).join(". ")}.`
          : `In a terminal: ${replay.command}. ${replay.terminal.map(plainLine).join(" ")}`}
      </p>

      <div aria-hidden="true" className="grid">
        <WebMode replay={replay} at={mode === "web" ? at : Infinity} animate={armed && mode === "web"} hidden={mode !== "web"} key={`w${run}`} />
        <TerminalMode replay={replay} at={mode === "terminal" ? at : Infinity} animate={armed && mode === "terminal"} hidden={mode !== "terminal"} key={`t${run}`} />
      </div>

      {!reduced && (
        <div className="flex justify-end border-t border-dashed border-line px-4 py-1 text-[0.8rem]">
          <button type="button" className="min-h-11 shrink-0 px-2 text-muted hover:text-ink disabled:opacity-40" onClick={() => restart(mode)} disabled={busy}>
            [ replay ]
          </button>
        </div>
      )}
    </div>
  );
}

/** On or off in place: never removed, so nothing moves. */
const show = (on: boolean) => (on ? "ls-on" : "ls-off");

function WebMode({ replay, at, animate, hidden }: { replay: Replay; at: number; animate: boolean; hidden: boolean }) {
  const landed = at >= 4;
  return (
    <div className={`ls-panel px-4 py-4 sm:px-5 ${hidden ? "invisible" : ""}`}>
      <div className="flex items-center gap-2 border border-line-strong bg-bg px-3 py-1.5 text-[0.8rem] text-muted">
        <span className="size-2 rounded-full bg-line-strong" />
        <span className="truncate">
          githolt.com/<span className="text-ink">{replay.repo}</span>
        </span>
      </div>
      <ol className="mt-3 space-y-0.5 text-[0.84rem] sm:text-[0.9rem]">
        {replay.stages.map((s, i) => {
          const now = at === i + 1 && at < 4;
          return (
            <li key={s} className={`flex gap-3 ${show(at > i)} ${now ? "text-ink" : "text-muted"}`}>
              <span className={`w-4 text-center ${now ? "text-blue" : "text-green"}`}>{now ? "▸" : "✓"}</span>
              {s}
            </li>
          );
        })}
      </ol>
      <div className={`ls-card relative mt-4 overflow-hidden border border-line-strong bg-bg ${show(landed)}`} data-landed={animate && landed}>
        <span className={`ls-card-bar absolute inset-y-0 left-0 w-1 ${TONE_BG[replay.tone]}`} />
        <div className="p-4 pl-6">
          <p className="text-[0.75rem] uppercase tracking-[0.08em] text-faint">verdict</p>
          <p className={`ls-card-headline display mt-2 text-[clamp(1.7rem,3.2vw,2.6rem)] ${TONE_TEXT[replay.tone]}`}>
            {replay.headline}
            <span className="text-ink">.</span>
          </p>
          <p className="mt-2 max-w-xl font-sans text-[0.95rem] leading-relaxed text-ink">{replay.line}</p>
          <ul className="mt-4 grid gap-px border border-line bg-line sm:grid-cols-3">
            {replay.stats.map((s, i) => (
              <li key={s.label} className="bg-panel p-3">
                <p className={`text-[1.25rem] font-semibold leading-tight ${TONE_TEXT[s.tone]}`}>
                  <Count text={s.big} go={at >= 5} animate={animate} delay={i * 90} />
                </p>
                <p className="mt-1 font-sans text-[0.82rem] leading-snug text-muted">{s.label}</p>
                {s.meter != null && (
                  <div className="meter mt-2">
                    <span className={`ls-meter block h-full origin-left ${TONE_BG[s.tone]}`} style={{ transform: `scaleX(${Math.max(0.02, s.meter)})`, ["--d" as string]: `${i * 90}ms` }} />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function TerminalMode({ replay, at, animate, hidden }: { replay: Replay; at: number; animate: boolean; hidden: boolean }) {
  const n = replay.command.length;
  const typed = Math.min(at, n);
  const lines = Math.max(0, at - n);
  const done = lines > replay.terminal.length;
  const typing = typed < n;
  return (
    <div className={`ls-panel bg-bg px-4 py-4 text-[0.8rem] leading-[1.75] sm:px-5 sm:text-[0.86rem] ${hidden ? "invisible" : ""}`}>
      <p className="break-all">
        <span className="text-amber">$ </span>
        <span>{replay.command.slice(0, typed)}</span>
        <span className="ls-ghost">{replay.command.slice(typed)}</span>
        {typing && at > 0 && <span className="ls-caret" />}
      </p>
      {replay.terminal.map((l, i) => (
        <p key={i} className={`${show(lines > i)} ${l.style ? LINE_STYLE[l.style] : "text-muted"} ${l.style === "heading" ? "mt-2" : ""}`}>
          {l.style === "heading" && <span className="text-blue"># </span>}
          <Counted line={l} go={lines > i} animate={animate} />
        </p>
      ))}
      <p className={`mt-3 ${show(done)}`}>
        <span className={`ls-stamp inline-block border-2 px-3 py-0.5 text-[1rem] font-semibold ${TONE_TEXT[replay.tone]}`} data-landed={animate && done}>
          ● {replay.headline}.
        </span>
      </p>
    </div>
  );
}

/** 0 → 1 over `ms`, eased, once `go` (and only if `animate`). */
function useProgress(go: boolean, animate: boolean, delay = 0, ms = 600) {
  const [p, setP] = useState(0);
  useEffect(() => {
    if (!go || !animate) return;
    let raf = 0;
    const t0 = performance.now() + delay;
    const tick = (t: number) => {
      const k = (t - t0) / ms;
      setP(settle(k));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [go, animate, delay, ms]);
  return !animate ? 1 : go ? p : 0;
}

/** A stat that counts into place; each number keeps its final width. */
function Count({ text, go, animate, delay }: { text: string; go: boolean; animate: boolean; delay: number }) {
  const p = useProgress(go, animate, delay, 700);
  return (
    <>
      {countParts(text).map((part, i) =>
        "n" in part ? (
          <span key={i} className="inline-block text-right tabular-nums" style={{ minWidth: `${part.final.length}ch` }}>
            {countAt(part, p)}
          </span>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

/** A printed line whose numbers count up as it appears. */
function Counted({ line, go, animate }: { line: ReplayLine; go: boolean; animate: boolean }) {
  const p = useProgress(go, animate && Boolean(line.counts?.length), 0, 500);
  if (!line.counts?.length) return <>{line.text}</>;
  let i = 0;
  return (
    <>
      {line.text.split(/(\{n\})/).map((part, k) => {
        if (part !== "{n}") return <span key={k}>{part}</span>;
        const n = line.counts![i++];
        return (
          <span key={k} className="inline-block text-right tabular-nums text-ink" style={{ minWidth: `${String(n).length}ch` }}>
            {Math.round(n * p)}
          </span>
        );
      })}
    </>
  );
}
