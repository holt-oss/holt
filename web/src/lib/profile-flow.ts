// The first-time profile flow on /me: one question at a time, each answer
// saved as it's given. The full form stays in Settings → Profile.
// No imports beyond types and profile.ts, so it runs under `node --test`.
import { contributions, days, level } from "./profile.ts";
import type { ContributionType, Level, ProfilePrefs } from "./types";

export type Prefs = Omit<ProfilePrefs, "updated_at">;

export const QUESTIONS = [
  { id: "languages", title: "Which languages can you read?", multi: true },
  { id: "days", title: "How long would you wait for a first reply?", multi: false },
  { id: "level", title: "Have you contributed to open source before?", multi: false },
  { id: "contributions", title: "What would you like to work on?", multi: true },
] as const;

export type QuestionId = (typeof QUESTIONS)[number]["id"];

/** Where the flow is: before the first question, on one (0-3), or done. */
export type FlowStep = "start" | number | "done";

/** What a profile holds before anything is answered: the settings form's defaults. */
export const BLANK: Prefs = { languages: [], topics: [], days: 7, level: "newcomer", contributions: [] };

export function progress(step: number): string {
  return `${step + 1} of ${QUESTIONS.length}`;
}

/** The step after this one, whether it was answered or skipped. */
export function after(step: FlowStep): FlowStep {
  if (step === "start") return 0;
  if (step === "done") return "done";
  return step + 1 < QUESTIONS.length ? step + 1 : "done";
}

/** The profile with one question's answer in it. Everything else is kept. */
export function answer(p: Prefs, id: QuestionId, value: string | string[]): Prefs {
  const vs = [value].flat();
  switch (id) {
    case "languages":
      return { ...p, languages: [...new Set(vs.map((v) => v.trim().toLowerCase()).filter((v) => v && v.length <= 40))].slice(0, 10) };
    case "days":
      return { ...p, days: days(vs[0], p.days) };
    case "level":
      return { ...p, level: level(vs[0], p.level) as Level };
    case "contributions":
      return { ...p, contributions: contributions(vs) as ContributionType[] };
  }
}

/** A multi-choice answer with one choice flipped. */
export function toggle(list: readonly string[], v: string): string[] {
  return list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
}

/** What a question currently holds, to light up its chips. */
export function current(p: Prefs, id: QuestionId): string[] {
  switch (id) {
    case "languages":
      return p.languages;
    case "days":
      return [String(p.days)];
    case "level":
      return [p.level];
    case "contributions":
      return p.contributions;
  }
}
