import type { Metadata } from "next";
import Link from "next/link";
import { CatFace } from "@/components/cat-face";
import { ChipRow } from "@/components/find/chip-row";
import { FindFrame } from "@/components/find/find-frame";
import { ErrorPanel } from "@/components/error-panel";
import { FindList } from "@/components/find/find-list";
import { FindRunner } from "@/components/find/find-runner";
import { HfLangAdd } from "@/components/find/hf-lang-add";
import { LangDot } from "@/components/repo-card/repo-avatar";
import { ShareBar } from "@/components/report/share-bar";
import { getProfile, savedNames } from "@/lib/api";
import { cachedFind } from "@/lib/find-cached";
import { FIND_FIRST, picksQuery } from "@/lib/find-picks";
import { days as daysOf, langName } from "@/lib/profile";
import { langColor } from "@/lib/repo-card";
import { caller, currentUser } from "@/lib/session";
import { CHECK_HREF } from "@/lib/shell";
import { hacktoberfest, hacktoberfestOver, SITE_URL } from "@/lib/site";
import { PageTransition } from "@/components/motion/page-transition";

const YEAR = 2026;

export const metadata: Metadata = {
  title: { absolute: `Hacktoberfest ${YEAR}: contributions that actually land · Holt` },
  description:
    "Open-source projects that reply to and merge outside contributors, with specific issues by language, and five tips so your pull request gets reviewed.",
  alternates: { canonical: "/hacktoberfest" },
  openGraph: {
    title: `Hacktoberfest ${YEAR}: contributions that actually land`,
    description: "Projects that merge outside work, with issues to start on, by language. Free, from Holt.",
    url: "/hacktoberfest",
  },
};

const LANGS = [
  { id: "all", label: "All languages", langs: [] },
  { id: "python", label: "Python", langs: ["python"] },
  { id: "js", label: "JS / TS", langs: ["javascript", "typescript"] },
  { id: "go", label: "Go", langs: ["go"] },
  { id: "rust", label: "Rust", langs: ["rust"] },
  { id: "java", label: "Java", langs: ["java"] },
  { id: "cpp", label: "C / C++", langs: ["c", "c++"] },
  { id: "ruby", label: "Ruby", langs: ["ruby"] },
  { id: "php", label: "PHP", langs: ["php"] },
] as const;

type Tab = { id: string; label: string; langs: readonly string[] };

/** A language typed into "add a language" (?lang=kotlin): its own tab, if it's a plausible name. */
function typedTab(v: string | string[] | undefined): Tab | null {
  const lang = typeof v === "string" ? v.trim().toLowerCase() : "";
  if (!lang || lang.length > 40 || !/^[a-z0-9][a-z0-9 +#.\-]*$/.test(lang) || LANGS.some((l) => l.id === lang || (l.langs as readonly string[]).includes(lang))) return null;
  return { id: lang, label: langName(lang), langs: [lang] };
}

// The official rules, from the hacktoberfest.com FAQ as of 29 Sep 2026.
// Re-read them each year; they changed completely in 2026.
const RULES_URL = "https://hacktoberfest.com/questions/";
const COUNTS = [
  "Pull requests no longer earn rewards. Maintainers asked for less spam.",
  "Stickers do. Collect them at a Fest, a livestream or a DEV Challenge. Three get you a sticker pack in the mail.",
  "Sign in with MyMLH at hacktoberfest.com. Your dashboard opens by 1 October.",
  "Pull requests are still welcome. Send them where they get merged.",
] as const;

const STEPS = [
  ["Pick a project that merges outside work", "Start from the list above, or paste any repo into Holt. Skip the ones where outside pull requests sit unanswered."],
  ["Take one real issue", "Choose something you understand, ask the maintainers if you can take it, and agree on the approach first."],
  ["See it through to merged", "Answer review, make the changes, and keep going until it lands. One merged fix beats ten ignored pull requests."],
] as const;

const TIPS = [
  ["Ask before you start.", "Comment on the issue and ask if you can take it. Maintainers ignore surprise pull requests far more often than ones they agreed to."],
  ["Read CONTRIBUTING first.", "Follow the project's setup, style and commit rules. It's the fastest way to look like someone worth reviewing."],
  ["Keep it small and focused.", "One issue, one pull request. Link the issue, say what you changed and how you tested it."],
  ["Own every line.", "Send only changes you understand and have tested. Typo-only edits and unreviewed AI-written code get closed as spam. Holt shows you real issues instead."],
  ["Reply to review, then be patient.", "Answer feedback within a day or two. Busy maintainers may take a week; one polite nudge after that is fine."],
] as const;

export default async function HacktoberfestPage({ searchParams }: PageProps<"/hacktoberfest">) {
  const [sp, user] = await Promise.all([searchParams, currentUser()]);
  const [profileR, saved] = await Promise.all([user ? getProfile(user.id) : null, savedNames(user?.id)]);
  const profile = profileR?.ok ? profileR.data.profile : null;
  // With no tab picked, a profile picks the first tab that has one of its languages.
  const typed = typedTab(sp.lang);
  const asked = typeof sp.lang === "string" ? sp.lang.trim().toLowerCase() : "";
  const tab: Tab = LANGS.find((l) => l.id === asked || (l.langs as readonly string[]).includes(asked))
    ?? typed
    ?? (profile && LANGS.find((l) => l.langs.some((x: string) => profile.languages.includes(x))))
    ?? LANGS[0];
  const days = profile ? daysOf(profile.days) : 7;
  const hf = hacktoberfest();
  const ended = hacktoberfestOver(YEAR);
  const result = await cachedFind({ languages: [...tab.langs], topics: [], days, hacktoberfest: true, limit: FIND_FIRST }, await caller(user));
  // Signed in, the list can carry on into the rest of Holt's index, on its button (the page goes on below it). Its route is for accounts (lib/gate.ts).
  const more = user ? picksQuery({ langs: [...tab.langs], topics: [], days, hf: true, level: "experienced", types: [] }) : null;
  const here = `/hacktoberfest${tab.id === "all" ? "" : `?lang=${encodeURIComponent(tab.id)}`}`;
  const fit = profile ? { level: profile.level, contributions: profile.contributions } : null;
  // No results on a language tab: widen to every language; on that tab, the find page.
  const empty = tab.id === "all"
    ? <Link href="/find" className="btn-primary">find a project →</Link>
    : <Link href="/hacktoberfest?lang=all" scroll={false} className="btn-primary">all languages →</Link>;

  return (
    <PageTransition>
      <FindFrame
        tab="hacktoberfest"
        title={<>This October, make contributions <span className="text-hf">that actually land.</span></>}
        signedIn={Boolean(user)}
      >
        <p className="mb-5 flex flex-wrap items-center gap-2 text-[0.8rem] uppercase tracking-[0.08em]">
          <span className="rounded-full border border-hf-line px-3 py-1 text-hf">Hacktoberfest {YEAR} · 1–31 October</span>
          {hf && (
            <span className="inline-flex items-center gap-2 rounded-full border border-hf-line px-3 py-1 text-hf">
              <span aria-hidden="true" className="size-1.5 rounded-full bg-orange motion-safe:animate-pulse" />
              {hf.short}
            </span>
          )}
        </p>
        {ended && (
          <p role="status" className="mb-6 max-w-2xl border border-hf-line bg-panel px-4 py-3 font-sans text-[0.92rem] text-muted">
            Hacktoberfest {YEAR} has ended. The projects below still merge outside work.
          </p>
        )}
        <nav aria-label="Language">
          <ChipRow current={tab.id} className="flex flex-wrap gap-2">
            {LANGS.map((l) => (
              <li key={l.id}>
                <Link
                  href={l.id === "all" ? (profile ? "/hacktoberfest?lang=all" : "/hacktoberfest") : `/hacktoberfest?lang=${l.id}`}
                  scroll={false}
                  aria-current={l.id === tab.id ? "page" : undefined}
                  className={`chip min-h-11 gap-2 whitespace-nowrap px-4 text-[0.89rem] transition-colors ${l.id === tab.id ? "border-hf bg-hf text-bg" : "hover:border-hf hover:text-ink"}`}
                >
                  {l.langs.length > 0 && <LangDot color={langColor(l.langs[0] ?? null)} />}
                  {l.label}
                  {l.id !== "all" && <span className="sr-only"> projects</span>}
                </Link>
              </li>
            ))}
            {typed && (
              <li>
                <Link
                  href={profile ? "/hacktoberfest?lang=all" : "/hacktoberfest"}
                  scroll={false}
                  aria-current="page"
                  aria-label={`${typed.label}, remove`}
                  className="chip min-h-11 gap-2 whitespace-nowrap border-hf bg-hf px-4 text-[0.89rem] text-bg"
                >
                  <LangDot color={langColor(typed.id)} />
                  {typed.label}
                  <span aria-hidden="true" className="opacity-70">×</span>
                </Link>
              </li>
            )}
            <li>
              <HfLangAdd />
            </li>
          </ChipRow>
        </nav>

        <section aria-label={`Welcoming Hacktoberfest projects: ${tab.label}`} className="mt-6">
          {!result.ok ? (
            <ErrorPanel error={result.error} retryHref={here} />
          ) : result.data.status === "queued" ? (
            <FindRunner key={tab.id} jobId={result.data.job_id} index={result.data.results} days={days} retryHref={here} fit={fit} saved={saved} empty={empty} more={more} />
          ) : (
            <FindList key={tab.id} results={result.data.results} fit={fit} more={more} auto={false} days={days} saved={saved} empty={empty} />
          )}
        </section>

        <div className="mt-14 grid grid-cols-1 gap-12 border-t border-line pt-10 lg:grid-cols-2">
          <section aria-labelledby="counts">
            <h2 id="counts" className="h2 h2-sm">What counts in {YEAR}</h2>
            <ul className="mt-6 space-y-3 font-sans text-muted">
              {COUNTS.map((line) => (
                <li key={line} className="flex gap-2">
                  <span aria-hidden="true" className="text-hf">→</span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-[0.8rem] text-faint">
              From the{" "}
              <a className="text-link" href={RULES_URL} target="_blank" rel="noopener noreferrer">hacktoberfest.com FAQ ↗</a>
            </p>
            <h2 id="how" className="h2 h2-sm mt-12">How to make October count</h2>
            <ol className="mt-6 space-y-6">
              {STEPS.map(([title, body], i) => (
                <li key={title} className="grid grid-cols-[2.5rem_1fr] gap-3">
                  <span className="text-[1.4rem] font-semibold text-orange">{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <p className="font-semibold">{title}</p>
                    <p className="mt-1 font-sans text-muted">{body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>
          <section id="tips" aria-labelledby="tips-h" className="scroll-mt-24">
            <h2 id="tips-h" className="h2 h2-sm">How not to get your PR ignored</h2>
            <ol className="mt-6 space-y-5">
              {TIPS.map(([title, body]) => (
                <li key={title} className="flex gap-3">
                  <span aria-hidden="true" className="text-green">→</span>
                  <p className="font-sans text-muted">
                    <strong className="font-semibold text-ink">{title}</strong> {body}
                  </p>
                </li>
              ))}
            </ol>
            <div className="mt-8">
              <ShareBar url={`${SITE_URL}/hacktoberfest`} text={`Contributing this October? These repos actually merge outsiders' pull requests:`} />
            </div>
          </section>
        </div>

        <p className="mt-12 font-sans text-[0.9rem] text-faint">
          Holt isn&apos;t affiliated with Hacktoberfest. For this year&apos;s events, see{" "}
          <a className="text-link" href="https://hacktoberfest.com" target="_blank" rel="noopener noreferrer">hacktoberfest.com ↗</a>.
        </p>
        <div className="mt-10 flex flex-col items-start gap-4 border-t border-line pt-10">
          <CatFace mood="adoring" className="text-[1.5rem] text-green" />
          <p className="text-[1.2rem] font-semibold tracking-tight">Already have a repo in mind?</p>
          <Link href={user ? CHECK_HREF : "/"} className="bracket-link">[ check any repo → ]</Link>
        </div>
      </FindFrame>
    </PageTransition>
  );
}
