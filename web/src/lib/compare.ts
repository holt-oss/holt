// /compare: reading the list from the URL, the page's one sentence, and which
// column leads on each number. Only what the reports already say; no verdict
// changes. No imports beyond repo parsing and types, so it runs under `node --test`.
import { parseRepoInput } from "./repo.ts";
import { humanHours, pct, timeAgo } from "./format.ts";
import { compactCount, share } from "./repo-about.ts";
import type { Report, Stats, Verdict } from "./types.ts";

export const MAX = 4;

/** Repos from `?repos=` or `?add=` (commas or spaces; names or URLs), de-duplicated, at most MAX (or `max`, to see what was asked for past it). */
export function parseList(v: string | string[] | undefined, max = MAX): string[] {
  const raw = (Array.isArray(v) ? v.join(",") : v ?? "").split(/[,\s]+/);
  const out: string[] = [];
  for (const r of raw) {
    const ref = parseRepoInput(r);
    const name = ref && `${ref.owner}/${ref.repo}`;
    if (name && !out.some((o) => o.toLowerCase() === name.toLowerCase())) out.push(name);
  }
  return out.slice(0, max);
}

/**
 * Words typed where a repo goes that aren't owner/name or a link: "excalidraw".
 * Lower-cased, de-duplicated, in order; the page looks each one up. Anything
 * with a slash, a colon or other odd characters is left out (it isn't a name).
 */
export function bareNames(v: string | string[] | undefined): string[] {
  const raw = (Array.isArray(v) ? v.join(",") : v ?? "").split(/[,\s]+/);
  const out: string[] = [];
  for (const r of raw) {
    const name = r.trim().toLowerCase();
    if (!name || parseRepoInput(r)) continue;
    if (/^[a-z0-9][a-z0-9._-]{0,59}$/.test(name) && !out.includes(name)) out.push(name);
  }
  return out;
}

/** Which search result a typed name means: the most starred one named exactly that (results come most starred first), else the top one. */
export function pickRepo(name: string, results: { repo: string }[]): string | null {
  const exact = results.find((r) => r.repo.split("/")[1]?.toLowerCase() === name.toLowerCase());
  return (exact ?? results[0])?.repo ?? null;
}

export function compareHref(list: string[]): string {
  return list.length ? `/compare?repos=${list.join(",")}` : "/compare";
}

/** Your saved repos not already in the list, newest saved first: one tap adds each. None once the list is full. */
export function savedToAdd(saved: string[], list: string[], limit = 6): string[] {
  if (list.length >= MAX) return [];
  const inList = new Set(list.map((r) => r.toLowerCase()));
  return saved.filter((s) => !inList.has(s.toLowerCase())).slice(0, limit);
}

/** Well-known repos a report offers to compare itself with (report/compare-card.tsx). */
export const EXAMPLE_POOL = ["pallets/flask", "psf/requests", "pytorch/pytorch", "home-assistant/core", "NixOS/nixpkgs", "django/django", "facebook/react", "microsoft/vscode"];

/** One-tap comparisons people often want: the way in from an empty page. */
export const SUGGESTIONS: { label: string; repos: string[] }[] = [
  { label: "flask vs django vs fastapi", repos: ["pallets/flask", "django/django", "fastapi/fastapi"] },
  { label: "react vs vue vs svelte", repos: ["facebook/react", "vuejs/core", "sveltejs/svelte"] },
  { label: "rust vs go", repos: ["rust-lang/rust", "golang/go"] },
];

/** Whether any number gets a best mark: the table's corner and the key under it show the mark only then. */
export function anyLead(lead: Record<Lead, number[]>): boolean {
  return Object.values(lead).some((l) => l.length > 0);
}

export type Lead = "merged" | "reply" | "firstTimers" | "silent" | "closed";

/** A column as the page reads it: what its report says, or null while it has none. */
export type Checked = Pick<Report, "repo" | "verdict" | "stats"> | null;

/**
 * Only these verdicts' numbers can be marked best. A fast reply on a repo
 * rated "Not worth your time" (or one with too little to go on, or not code)
 * mustn't read as a reason to pick it over one that is worth trying.
 */
const CAN_LEAD = new Set<Verdict>(["viable", "long_shot"]);

/** The stats `leaders` should weigh: null for a column with no report or a verdict that can't lead. */
export function contenders(cols: Checked[]): (Stats | null)[] {
  return cols.map((c) => (c && CAN_LEAD.has(c.verdict) ? c.stats : null));
}

/**
 * For each number, the columns (by index) that do best on it: highest share
 * merged, fastest first reply, most first-timers merged, lowest share with no
 * reply, lowest share closed without a word. Only when at least two columns
 * have the number and they differ.
 */
export function leaders(stats: (Stats | null)[]): Record<Lead, number[]> {
  const share = (n: number, d: number) => (d > 0 ? n / d : null);
  const pick = (vals: (number | null)[], better: "high" | "low"): number[] => {
    const known = vals.filter((v): v is number => v != null);
    if (known.length < 2 || known.every((v) => v === known[0])) return [];
    const best = better === "high" ? Math.max(...known) : Math.min(...known);
    return vals.flatMap((v, i) => (v === best ? [i] : []));
  };
  return {
    merged: pick(stats.map((s) => (s ? share(s.outsider_merged, s.outsider_attempts) : null)), "high"),
    reply: pick(stats.map((s) => s?.median_first_response_hours ?? null), "low"),
    firstTimers: pick(stats.map((s) => s?.first_time_merged_authors ?? null), "high"),
    silent: pick(stats.map((s) => (s ? share(s.no_reply, s.outsider_attempts) : null)), "low"),
    closed: pick(stats.map((s) => (s ? share(s.closed_silently, s.outsider_attempts) : null)), "low"),
  };
}

/**
 * The page's one sentence, verdicts first: which repo is worth your time, or
 * the best of the long shots, or that none is. The merge rate only breaks a
 * tie between repos with the same verdict, so a better number never outranks
 * a better verdict. Once there are two or more and every one has a report;
 * otherwise (an empty page too) the question the page answers.
 */
export function compareTitle(cols: Checked[]): string {
  const checked = cols.filter((c) => c != null);
  if (cols.length < 2 || checked.length < cols.length) return "Which one will review your pull request?";
  const top = (group: NonNullable<Checked>[]) => {
    const m = leaders(group.map((c) => c.stats)).merged;
    return m.length === 1 ? group[m[0]].repo : null;
  };
  const worth = checked.filter((c) => c.verdict === "viable");
  const long = checked.filter((c) => c.verdict === "long_shot");
  if (worth.length === 1) return `${worth[0].repo} is the one worth your time.`;
  if (worth.length > 1) {
    const which = worth.length < checked.length ? `${worth.length} of these are` : checked.length === 2 ? "Both are" : `All ${checked.length} are`;
    const t = top(worth);
    return t ? `${which} worth your time; ${t} merges outsiders most often.` : `${which} worth your time.`;
  }
  if (long.length === 1) return `${long[0].repo} is your best shot here, but still a long shot.`;
  if (long.length > 1) {
    const t = top(long);
    return t ? `No sure bets here; ${t} is the best of the long shots.` : "No sure bets here, only long shots.";
  }
  return "None of these looks like a good bet right now.";
}

/** The numbers compared, one row each, in the order they're read. */
export const ROWS: { id: Lead | "way"; label: string }[] = [
  { id: "merged", label: "Outside PRs merged" },
  { id: "reply", label: "Typical first reply" },
  { id: "firstTimers", label: "First-timers merged" },
  { id: "silent", label: "Sat open, no reply" },
  { id: "closed", label: "Closed without a word" },
  { id: "way", label: "Best way in" },
];

export interface Cell {
  /** The number to scan. */
  main: string;
  /** What it's out of, when that matters. */
  sub?: string;
  /** "bad" for a number that's a warning on its own; "none" for nothing to show. */
  tone?: "bad" | "none";
}

/** What the project is, how big and alive (#165's `about`), under the numbers Holt reads. Stars lead. */
export const ABOUT_ROWS: { id: "stars" | "forks" | "issues" | "pushed" | "language"; label: string }[] = [
  { id: "stars", label: "Stars" },
  { id: "forks", label: "Forks" },
  { id: "issues", label: "Open issues" },
  { id: "pushed", label: "Last pushed" },
  { id: "language", label: "Main language" },
];

export type AboutId = (typeof ABOUT_ROWS)[number]["id"];

/** One column's About cells; "–" where GitHub didn't say. An archived repo says so where the last push goes. */
export function aboutCells(about: Report["about"], now: number): Record<AboutId, Cell & { lang?: string }> {
  const none: Cell = { main: "–", tone: "none" };
  if (!about) return { stars: none, forks: none, issues: none, pushed: none, language: none };
  const count = (n: number | null | undefined): Cell => (n == null ? none : { main: compactCount(n) });
  const lang = about.languages[0];
  return {
    stars: { main: compactCount(about.stars) },
    forks: count(about.forks),
    issues: count(about.open_issues),
    pushed: about.archived ? { main: "archived", tone: "bad" } : about.pushed_at ? { main: timeAgo(about.pushed_at, now) || "–" } : none,
    language: lang ? { main: lang.name, sub: share(lang.share), lang: lang.name } : none,
  };
}

/** One column's cells, from what the report already says. */
export function cells(report: Pick<Report, "stats" | "landing">): Record<Lead | "way", Cell> {
  const s = report.stats;
  const n = s.outsider_attempts;
  const none: Cell = { main: "–", tone: "none" };
  const share = (k: number): Cell => (n > 0 ? { main: `${pct(k, n)}%` } : none);
  const top = report.landing[0];
  return {
    merged: n > 0 ? { main: `${pct(s.outsider_merged, n)}%`, sub: `${s.outsider_merged} of ${n}` } : { main: "–", sub: "no outside PRs", tone: "none" },
    reply: s.median_first_response_hours == null ? (n > 0 ? { main: "no replies", tone: "bad" } : none) : { main: humanHours(s.median_first_response_hours) },
    firstTimers: { main: String(s.first_time_merged_authors), ...(s.first_time_merged_authors === 0 && n > 0 ? { tone: "bad" as const } : {}) },
    silent: share(s.no_reply),
    closed: share(s.closed_silently),
    way: top ? { main: top.path.startsWith("(") ? top.path : `${top.path}/` } : { main: "none yet", tone: "none" },
  };
}
