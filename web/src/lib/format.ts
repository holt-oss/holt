import { LANGS, MORE_LANGS } from "./profile.ts";
import type { StarterIssue, Stats, Tone } from "./types";

export function pct(n: number, d: number): number {
  return d > 0 ? Math.round((n / d) * 100) : 0;
}

/** 0.8 -> "48 minutes", 30 -> "about a day". */
export function humanHours(hours: number | null | undefined): string {
  if (hours == null || !Number.isFinite(hours)) return "unknown";
  const mins = Math.round(hours * 60);
  if (mins < 1) return "under a minute";
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"}`;
  if (hours < 1.5) return "about an hour";
  if (hours < 24) return `${Math.round(hours)} hours`;
  const days = hours / 24;
  if (days < 1.5) return "about a day";
  if (days < 14) return `${Math.round(days)} days`;
  const weeks = days / 7;
  if (weeks < 8) return `${Math.round(weeks)} weeks`;
  return `${Math.round(days / 30)} months`;
}

export function timeAgo(iso: string, now = Date.now()): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d} day${d === 1 ? "" : "s"} ago`;
  const mo = Math.round(d / 30);
  if (mo < 12) return `${mo} month${mo === 1 ? "" : "s"} ago`;
  const y = Math.round(d / 365);
  return `${y} year${y === 1 ? "" : "s"} ago`;
}

export function shortDate(iso: string): string {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  return t.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export function daysLabel(days: number): string {
  if (days <= 1) return "an evening";
  if (days <= 3) return "a weekend";
  if (days <= 7) return "a week";
  if (days <= 14) return "two weeks";
  return "a month";
}

// Tile colours. The server's `odds` (server/holt_server/schema.py, MERGE_*
// and NO_REPLY_*) uses the same thresholds, so a tile and the odds never pull
// different ways.
export function mergeTone(mergedPct: number): Tone {
  return mergedPct >= 12 ? "good" : mergedPct >= 5 ? "warn" : "bad";
}
export function noReplyTone(noReplyPct: number): Tone {
  return noReplyPct <= 25 ? "good" : noReplyPct <= 50 ? "warn" : "bad";
}

export interface StatLine {
  key: string;
  big: string;
  label: string;
  tone: Tone | "neutral";
  /** 0–1 for an optional meter. */
  meter?: number;
}

export function statLines(s: Partial<Stats>): StatLine[] {
  const out: StatLine[] = [];
  if (s.outsider_attempts != null && s.outsider_merged != null) {
    const p = pct(s.outsider_merged, s.outsider_attempts);
    out.push({
      key: "merged",
      big: `${s.outsider_merged} of ${s.outsider_attempts}`,
      label: `outside PRs merged (${p}%)`,
      tone: mergeTone(p),
      meter: s.outsider_attempts ? s.outsider_merged / s.outsider_attempts : 0,
    });
  }
  if (s.median_first_response_hours !== undefined) {
    const h = s.median_first_response_hours;
    out.push({
      key: "reply",
      big: h == null ? "No replies" : humanHours(h),
      label: h == null ? "to measure: no outside PR got an answer" : "is the typical wait for a first reply",
      tone: h == null ? "bad" : h <= 48 ? "good" : h <= 24 * 7 ? "warn" : "bad",
    });
  }
  if (s.first_time_merged_authors != null) {
    out.push({
      key: "first",
      big: String(s.first_time_merged_authors),
      label: s.first_time_merged_authors === 1 ? "person got their first PR merged here" : "people got their first PR merged here",
      tone: s.first_time_merged_authors > 0 ? "good" : "bad",
    });
  }
  if (s.no_reply != null && s.outsider_attempts) {
    const p = pct(s.no_reply, s.outsider_attempts);
    out.push({
      key: "noreply",
      big: `${p}%`,
      label: `of outside PRs sat open with no reply (${s.no_reply})`,
      tone: noReplyTone(p),
      meter: s.no_reply / s.outsider_attempts,
    });
  }
  if (s.closed_silently != null && s.outsider_attempts) {
    out.push({
      key: "closed",
      big: `${pct(s.closed_silently, s.outsider_attempts)}%`,
      label: `of outside PRs were closed without a word (${s.closed_silently})`,
      tone: "neutral",
      meter: s.closed_silently / s.outsider_attempts,
    });
  }
  if (s.distinct_outsiders != null) {
    out.push({
      key: "people",
      big: String(s.distinct_outsiders),
      label: "different outsiders tried recently",
      tone: "neutral",
    });
  }
  // Bots aren't a tile: the six tiles fill the grid, and "how this was
  // counted" already says how many bot PRs were left out.
  return out;
}

const humanize = (k: string) => k.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const NEGATIVE = /no_reply|ignored|closed|reject|stale|declin|abandon|negative|hostile/;

// Plain labels for the engine's values. The same table as the engine's
// src/holt/agent/labels.py (tests/test_labels.py holds the two together).
const OUTCOME_LABELS: Record<string, string> = {
  merged_after_review: "Merged after review",
  merged_without_engagement: "Merged without review comments",
  changes_requested: "Changes requested",
  closed_with_guidance: "Closed, with a pointer elsewhere",
  closed_dismissive: "Closed with no way forward",
  ignored: "No reply",
};
const FIELD_LABELS: Record<string, string> = {
  repo_kind: "Kind of project",
  onboarding: "Contributor guide",
  outsider_posture: "How outside contributors are treated",
  governance_flags: "Before you contribute",
  is_archived: "Archived",
  inactive: "Activity",
  personal_project: "Whose project this is",
  contribute_elsewhere: "Where to contribute",
  prs_closed: "Who can open pull requests",
};

/** "Merged after review" for an engine outcome value. */
export function outcomeLabel(value: string): string {
  return OUTCOME_LABELS[value] ?? humanize(value);
}

/** "Contributor guide" for an engine field. */
export function fieldLabel(kind: string): string {
  return FIELD_LABELS[kind] ?? humanize(kind);
}

/**
 * Label and tone for an evidence item. Rules mode lists newcomer PRs as
 * kind "outsider_pr" (value "merged" | "no_reply"); AI mode uses "outcome"
 * (value like "merged_after_review") or the engine field a claim is about.
 */
export function evidenceLabel(e: { kind: string; value: string | null }): { label: string; bad: boolean } {
  const value = e.value ?? "";
  const bad = NEGATIVE.test(value);
  if (e.kind === "outsider_pr") {
    return { label: e.value === "merged" ? "Newcomer PR merged" : e.value === "no_reply" ? "Newcomer PR, no reply" : `Newcomer PR: ${humanize(value).toLowerCase()}`, bad };
  }
  if (e.kind === "outcome") return { label: OUTCOME_LABELS[value] ?? humanize(value), bad };
  return { label: FIELD_LABELS[e.kind] ?? humanize(e.kind), bad };
}

/** "#526518" or a short id for an evidence link. */
export function evidenceRef(url: string): string {
  const m = url.match(/github\.com\/[^/]+\/[^/]+\/(pull|issues|discussions|commit)\/([^/#?]+)/);
  if (!m) return "open on GitHub";
  return m[1] === "commit" ? m[2].slice(0, 7) : `#${m[2]}`;
}

/** Someone is already on it: an open pull request, an assignee, or a recent "can I work on this?". */
export function issueTaken(issue: Pick<StarterIssue, "people" | "open_prs">): boolean {
  return Boolean(issue.people || issue.open_prs);
}

/** Said when a repo has starter issues and someone is on every one. */
export const NONE_FREE = "No free starter issue right now";

const LANG_NAMES = new Map([...LANGS, ...MORE_LANGS].map((l) => [l.toLowerCase(), l]));
const LANG_SHORT: Record<string, string> = { js: "JavaScript", ts: "TypeScript", py: "Python", golang: "Go", cpp: "C++", csharp: "C#" };
const WORK: Record<string, string> = { docs: "Docs", tests: "Tests", design: "Design", translations: "Translations" };

/**
 * The skill an issue asks for, when it says so itself: a language one of its
 * labels names ("python", "lang: rust"), else the kind of work when that isn't
 * code. Null otherwise: nothing is guessed.
 */
export function issueSkill(issue: Pick<StarterIssue, "labels" | "areas">): string | null {
  for (const raw of issue.labels) {
    const label = raw.toLowerCase().trim();
    for (const name of [label, label.split(/[:/]/).pop()!.trim()]) {
      // One-letter names ("C", "R") are too easy to hit by accident.
      const lang = LANG_SHORT[name] ?? (name.length > 1 ? LANG_NAMES.get(name) : undefined);
      if (lang) return lang;
    }
  }
  const work = issue.areas?.[0];
  return work && work !== "code" ? WORK[work] ?? null : null;
}

/** The one-line "what to do next" for a starter issue. */
export function nextStep(issue: StarterIssue): string {
  const labels = issue.labels.map((l) => l.toLowerCase());
  const docs = labels.some((l) => l.includes("doc"));
  if (issue.open_prs) return "Look at the open pull request first; if it has stalled, ask to take over.";
  if (issue.people) return "Ask whether it's still free before you start.";
  if (issue.comments === 0) {
    return docs
      ? "Comment on the issue to say you'd like to fix the docs, then open a small pull request."
      : "Comment on the issue to ask if you can take it.";
  }
  if (issue.comments <= 3) return "Read the comments first, then ask if it's still free for you to take.";
  return "Read the discussion; if nobody is working on it, ask a maintainer if you can pick it up.";
}
