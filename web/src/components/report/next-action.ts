// What a report offers right under its verdict: something to start on here,
// better places to go, or one line to Find. Decided by the verdict alone.
// No imports beyond types, so it runs under `node --test` and in the browser.
import type { DiscoverRepo, Verdict } from "../../lib/types.ts";

/** start: this repo's starter issues · alternatives: repos that do merge outsiders · find: one link to Find. */
export type NextAction = "start" | "alternatives" | "find";

export function nextAction(verdict: Verdict): NextAction {
  if (verdict === "viable") return "start";
  if (verdict === "long_shot" || verdict === "not_viable") return "alternatives";
  return "find";
}

/**
 * Whether this repo's starter issues wait behind "I still want to contribute
 * here". Not worth your time, Not enough evidence and Personal project list none at all.
 */
export function issuesBehindControl(verdict: Verdict): boolean {
  return verdict === "long_shot" || verdict === "catalogue";
}

/** The first `n` repos worth your time from a board, never the repo being read. */
export function pickAlternatives<T extends Pick<DiscoverRepo, "repo" | "verdict">>(repos: T[], self: string, n = 3): T[] {
  const me = self.toLowerCase();
  return repos.filter((r) => r.verdict === "viable" && r.repo.toLowerCase() !== me).slice(0, n);
}

/** Find, searching the repo's language when it has one (the URL format of lib/find-picks.ts). */
export function findHref(language: string | null | undefined): string {
  const lang = language?.trim().toLowerCase();
  return lang ? `/find?${new URLSearchParams({ lang })}` : "/find";
}

/** The words on the link to Find, under each verdict that gets one. */
export function findLabel(verdict: Verdict, language: string | null | undefined): string {
  const lang = language?.trim() ? `${language.trim()} ` : "";
  if (verdict === "insufficient_evidence") return `Find a ${lang}project with a track record`;
  if (verdict === "catalogue") return `Find a ${lang}project to write code for`;
  return `Find a ${lang}project that merges outsiders`;
}
