// Profile preferences (API.md, "Profile"): the choices, reading them from a
// form or a URL, and applying them to find results. No imports beyond types,
// so it runs under `node --test` and in the browser.
import type { ContributionType, FindResult, Level, ProfilePrefs } from "./types";

/** Cookie that hides the onboarding card; the profile section in settings stays. */
export const SKIP_COOKIE = "holt_profile_skip";

export const LANGS = ["Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "C++", "Ruby", "PHP", "Nix"];

/** Suggested while typing a language in on /find (GitHub's spelling), past the ones with chips. */
export const MORE_LANGS = [
  "Assembly", "C", "C#", "Clojure", "Crystal", "CSS", "Dart", "Dockerfile", "Elixir", "Elm", "Erlang", "F#", "Fortran",
  "Gleam", "Groovy", "Haskell", "HTML", "Julia", "Jupyter Notebook", "Kotlin", "Lua", "MATLAB", "Nim", "Objective-C",
  "OCaml", "Perl", "PowerShell", "R", "Scala", "Shell", "Solidity", "Svelte", "Swift", "Vue", "Zig",
];

/** Suggested while typing a topic on /find: common GitHub topics. */
export const POPULAR_TOPICS = [
  "accessibility", "ai", "android", "api", "cli", "compiler", "data-science", "database", "deep-learning", "devops",
  "django", "docker", "documentation", "education", "fastapi", "flask", "flutter", "game", "hacktoberfest", "ios",
  "kubernetes", "linux", "llm", "machine-learning", "nextjs", "nodejs", "rails", "react", "security", "self-hosted",
  "svelte", "terminal", "testing", "visualization", "vue", "web",
];

/** A language id (lowercase) as a name: GitHub's spelling when we know it, else a leading capital. */
export function langName(id: string): string {
  return [...LANGS, ...MORE_LANGS].find((l) => l.toLowerCase() === id) ?? id.charAt(0).toUpperCase() + id.slice(1);
}

export const TIME = [
  { days: 1, label: "an evening" },
  { days: 3, label: "a weekend" },
  { days: 7, label: "a week" },
  { days: 30, label: "a month" },
] as const;

export const CONTRIBUTIONS: { id: ContributionType; label: string }[] = [
  { id: "code", label: "Code" },
  { id: "docs", label: "Docs" },
  { id: "tests", label: "Tests" },
  { id: "design", label: "Design" },
  { id: "translations", label: "Translations" },
];

export const LEVELS: { id: Level; label: string; hint: string }[] = [
  { id: "newcomer", label: "New to open source", hint: "Only issues the maintainers labelled for first-timers." },
  { id: "experienced", label: "I've contributed before", hint: "Also issues asking for help, and small unlabelled fixes." },
];

/** What personalises results; the rest of a profile goes into the search itself. */
export interface Fit {
  level: Level;
  contributions: ContributionType[];
}

const isContribution = (v: string): v is ContributionType => CONTRIBUTIONS.some((c) => c.id === v);
const isLevel = (v: string): v is Level => LEVELS.some((l) => l.id === v);

/** A days value from the time choices, else the default week. */
export function days(v: unknown, fallback = 7): number {
  const n = Number(v);
  return TIME.some((t) => t.days === n) ? n : fallback;
}

export function level(v: unknown, fallback: Level = "experienced"): Level {
  return typeof v === "string" && isLevel(v) ? v : fallback;
}

export function contributions(vs: unknown[]): ContributionType[] {
  return [...new Set(vs.filter((v): v is string => typeof v === "string").map((v) => v.trim().toLowerCase()).filter(isContribution))];
}

/** Topics as typed ("web framework, CLI") into GitHub topic form. */
export function topics(v: string): string[] {
  const out = v
    .split(/[,\n]/)
    .map((t) => t.trim().toLowerCase().replace(/\s+/g, "-"))
    .filter((t) => /^[a-z0-9][a-z0-9-]{0,49}$/.test(t));
  return [...new Set(out)].slice(0, 10);
}

/** The body for PUT /v1/me/profile from the profile form. */
export function fromForm(form: FormData): Omit<ProfilePrefs, "updated_at"> & { adult_confirmed: boolean } {
  const langs = form.getAll("lang").filter((v): v is string => typeof v === "string").map((v) => v.trim().toLowerCase()).filter((v) => v && v.length <= 40);
  return {
    languages: [...new Set(langs)].slice(0, 10),
    topics: topics(String(form.get("topics") ?? "")),
    days: days(form.get("days")),
    contributions: contributions(form.getAll("type")),
    level: level(form.get("level"), "newcomer"),
    adult_confirmed: form.get("adult") === "on",
  };
}

/**
 * Applies experience and contribution types to find results. A newcomer keeps
 * only issues labelled for first-timers, and a repo left with none is dropped;
 * issues nobody is on come first, then those matching the chosen contribution
 * types. Never changes a verdict or which repos passed it.
 */
export function personalise(results: FindResult[], fit: Fit | null): FindResult[] {
  if (!fit) return results;
  const wanted = new Set(fit.contributions);
  const matches = (areas: ContributionType[] | undefined) => (areas ?? []).some((a) => wanted.has(a));
  const out: FindResult[] = [];
  for (const r of results) {
    let issues = fit.level === "newcomer" ? r.issues.filter((i) => i.beginner !== false) : r.issues;
    // Nobody on it first (as the server ranks them), then the wanted kinds of work.
    const busy = (i: FindResult["issues"][number]) => Boolean(i.people || i.open_prs);
    if (wanted.size) issues = [false, true].flatMap((b) => [...issues.filter((i) => busy(i) === b && matches(i.areas)), ...issues.filter((i) => busy(i) === b && !matches(i.areas))]);
    if (issues.length) out.push({ ...r, issues });
  }
  // Repos with a matching issue first; otherwise the server's order stands.
  if (!wanted.size) return out;
  return [...out.filter((r) => matches(r.issues[0]?.areas)), ...out.filter((r) => !matches(r.issues[0]?.areas))];
}

/** A one-line description of a profile, for "using your profile: …" notes. */
export function describe(p: Pick<ProfilePrefs, "languages" | "days" | "level" | "contributions">): string {
  const lang = p.languages.length ? p.languages.map((l) => LANGS.find((x) => x.toLowerCase() === l) ?? l).join(", ") : "any language";
  const time = `replies within ${TIME.find((t) => t.days === p.days)?.label ?? `${p.days} days`}`;
  const who = p.level === "newcomer" ? "first-timer issues only" : "all starter issues";
  const kinds = p.contributions.length ? `, ${p.contributions.join(" and ")} first` : "";
  return `${lang} · ${time} · ${who}${kinds}`;
}

/** A /find search that uses a profile, as the find form would submit it. */
export function findHref(p: Omit<ProfilePrefs, "updated_at">, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams({ go: "1" });
  for (const l of p.languages) q.append("lang", l);
  q.set("days", String(p.days));
  if (p.topics.length) q.set("topics", p.topics.join(", "));
  q.set("level", p.level);
  for (const t of p.contributions) q.append("type", t);
  for (const [k, v] of Object.entries(extra)) q.set(k, v);
  return `/find?${q}`;
}
