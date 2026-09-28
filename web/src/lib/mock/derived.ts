// MOCK_API=1 only. The real server derives these fields once, in
// server/holt_server/schema.py; the mock stands in for it with a rough copy so
// mock pages have something to render. The app itself never computes them.
import type { Odds, Report, Stats, Tone, Verdict } from "../types";

const HEADLINE: Record<Verdict, string> = {
  viable: "Worth your time",
  not_viable: "Not worth your time",
  insufficient_evidence: "Not enough evidence",
};
const TONE: Record<Verdict, Tone> = { viable: "good", not_viable: "bad", insufficient_evidence: "warn" };

export function verdictView(verdict: Verdict): { headline: string; tone: Tone } {
  return { headline: HEADLINE[verdict], tone: TONE[verdict] };
}

function odds(verdict: Verdict, s: Stats): Odds | null {
  if (verdict !== "viable" || !s.outsider_attempts) return null;
  const merged = s.outsider_merged / s.outsider_attempts;
  const silent = s.no_reply / s.outsider_attempts;
  const mergeBand = merged >= 0.12 ? 0 : merged >= 0.05 ? 1 : 2;
  const band = Math.max(mergeBand, silent <= 0.25 ? 0 : silent <= 0.5 ? 1 : 2);
  if (band === 2 && mergeBand < 2) return { level: "long", tone: "bad", text: "many outside pull requests here never get a reply, so pick your first one carefully" };
  return [
    { level: "good", tone: "good", text: "most outside pull requests get a reply, and plenty get merged" },
    { level: "fair", tone: "warn", text: "some outside pull requests land; a well-chosen starter issue helps" },
    { level: "long", tone: "bad", text: "most outside pull requests here don't land, so pick your first one carefully" },
  ][band] as Odds;
}

function line(verdict: Verdict, s: Stats, decidedBy: string[]): string {
  const merged = `${s.outsider_merged} of ${s.outsider_attempts}`;
  if (verdict === "viable") return "Outside contributors get real replies here, and their work gets merged.";
  if (verdict === "not_viable") return decidedBy.at(-1) ?? `Only ${merged} pull requests from outside contributors were merged.`;
  return "Too few outside contributors have tried recently for Holt to say either way.";
}

function numbers(s: Stats): string {
  const n = s.outsider_attempts;
  if (!n) return "Nobody outside the project's team opened a pull request.";
  const out = [`Of ${n} pull requests from outside contributors, ${s.outsider_merged} were merged (${Math.round((100 * s.outsider_merged) / n)}%).`];
  if (s.median_first_response_hours != null) out.push(`When a maintainer replied, it was typically within ${hoursPhrase(s.median_first_response_hours)}.`);
  if (s.no_reply) out.push(`${Math.round((100 * s.no_reply) / n)}% got no reply at all.`);
  return out.join(" ");
}

function nextStep(r: Stored): string {
  if (r.verdict === "not_viable") return "Put your time into a project that answers outside contributors; Holt's Find page lists some.";
  if (r.verdict !== "viable") return "There's too little to go on. Before writing code, open an issue and ask whether a pull request would be welcome.";
  const best = r.landing.find((a) => a.path !== "(root)" && a.merged >= 3);
  return best
    ? `Best bet: a small change in ${best.path}, where ${best.merged} of ${best.attempted} outside pull requests were merged.`
    : "Best bet: a small, focused change; a starter issue is a good place to find one.";
}

type Derived = "headline" | "tone" | "verdict_line" | "odds" | "rule_codes" | "numbers_line" | "first_timer_line" | "next_step" | "stat_line" | "counted" | "sample" | "asks" | "budget_independent";
type Stored = Omit<Report, Derived>;

export function withDerived(r: Stored): Report {
  const s = r.stats;
  const k = s.first_time_merged_authors;
  return {
    ...r,
    ...verdictView(r.verdict),
    rule_codes: [],
    sample: null,
    asks: [],
    budget_independent: r.mode === "rules",
    verdict_line: line(r.verdict, s, r.decided_by),
    numbers_line: numbers(s),
    first_timer_line: !s.outsider_attempts ? null : k ? `${k} ${k === 1 ? "person" : "people"} got their first pull request merged here.` : "Nobody got their first pull request merged here in this period.",
    next_step: nextStep(r),
    stat_line: s.outsider_attempts ? `${s.outsider_merged} of ${s.outsider_attempts} outside PRs merged` : null,
    counted: [
      ...(r.decided_by.length ? [{ topic: "What decided it", text: r.decided_by.join(" ") }] : []),
      { topic: "The rule", text: "These rules are fixed; no AI chooses the verdict." },
    ],
    odds: odds(r.verdict, s),
  };
}

// The engine's wording for a reply time (holt.agent.verdict.hours_phrase).
function hoursPhrase(h: number): string {
  if (h < 1) {
    const m = Math.max(1, Math.round(h * 60));
    return `${m} minute${m === 1 ? "" : "s"}`;
  }
  if (h < 48) return `${h} hour${h === 1 ? "" : "s"}`;
  return `${(h / 24).toFixed(1)} days`;
}
