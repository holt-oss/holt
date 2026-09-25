import type { Metadata } from "next";
import Link from "next/link";
import { CatFace } from "@/components/cat-face";
import { ErrorPanel } from "@/components/error-panel";
import { FindResults } from "@/components/find/find-results";
import { FindRunner } from "@/components/find/find-runner";
import { ShareBar } from "@/components/report/share-bar";
import { cachedFind } from "@/lib/find-cached";
import { caller } from "@/lib/session";
import { hacktoberfest, hacktoberfestOver, SITE_URL } from "@/lib/site";

const YEAR = 2026;

export const metadata: Metadata = {
  title: { absolute: `Hacktoberfest ${YEAR}: repos that will actually review your PR | Holt` },
  description:
    "Welcoming open-source projects for your first Hacktoberfest pull request, with specific starter issues by language, and five tips so your PR doesn't get ignored.",
  alternates: { canonical: "/hacktoberfest" },
  openGraph: {
    title: `Hacktoberfest ${YEAR}: repos that will actually review your PR`,
    description: "Welcoming projects and starter issues, by language. Free, from Holt.",
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

const STEPS = [
  ["Sign up", "Register on the official Hacktoberfest site and link your GitHub or GitLab account. It runs all of October."],
  ["Open pull requests", "Contribute to projects taking part (they have the hacktoberfest topic, or a maintainer adds the hacktoberfest-accepted label)."],
  ["Get them accepted", "Only pull requests a maintainer merges or approves count. Check the official site for this year's exact rules."],
] as const;

const TIPS = [
  ["Ask before you start.", "Comment on the issue and ask if you can take it. Maintainers ignore surprise pull requests far more often than ones they agreed to."],
  ["Read CONTRIBUTING first.", "Follow the project's setup, style and commit rules. It's the fastest way to look like someone worth reviewing."],
  ["Keep it small and focused.", "One issue, one pull request. Link the issue, say what you changed and how you tested it."],
  ["Don't send spam.", "Typo-only or whitespace changes in random repos get labelled spam and can get you disqualified. Holt shows you real issues instead."],
  ["Reply to review, then be patient.", "Answer feedback within a day or two. Busy maintainers may take a week; one polite nudge after that is fine."],
] as const;

export default async function HacktoberfestPage({ searchParams }: PageProps<"/hacktoberfest">) {
  const sp = await searchParams;
  const tab = LANGS.find((l) => l.id === sp.lang) ?? LANGS[0];
  const hf = hacktoberfest();
  const ended = hacktoberfestOver(YEAR);
  const result = await cachedFind({ languages: [...tab.langs], topics: [], days: 7, hacktoberfest: true, limit: 12 }, await caller());
  const here = `/hacktoberfest${tab.id === "all" ? "" : `?lang=${tab.id}`}`;

  return (
    <>
      {/* Campaign header: a limited-time event page, not part of the core site. */}
      <section className="relative overflow-hidden border-b border-hf-line bg-hf-bg">
        <div
          aria-hidden="true"
          className="absolute inset-0 opacity-[0.08]"
          style={{ backgroundImage: "repeating-linear-gradient(135deg, var(--hf) 0 2px, transparent 2px 14px)" }}
        />
        <div className="wrap relative py-10 sm:py-14">
          <div className="mb-6 flex flex-wrap items-center gap-2 text-[0.72rem] uppercase tracking-[0.08em]">
            <span className="rounded-full bg-hf px-3 py-1 font-semibold text-bg">limited-time event</span>
            <span className="rounded-full border border-hf-line px-3 py-1 text-hf">Hacktoberfest {YEAR} · 1–31 October</span>
            {hf && (
              <span className="inline-flex items-center gap-2 rounded-full border border-hf-line px-3 py-1 text-hf">
                <span aria-hidden="true" className="size-1.5 rounded-full bg-orange motion-safe:animate-pulse" />
                {hf.short}
              </span>
            )}
          </div>
          {ended && (
            <p role="status" className="mb-6 max-w-2xl border border-hf-line bg-panel px-4 py-3 font-sans text-[0.92rem] text-muted">
              Hacktoberfest {YEAR} has ended. The projects below still welcome newcomers, and{" "}
              <Link href="/find" className="text-link">/find</Link> works all year.
            </p>
          )}
          <h1 className="display max-w-4xl text-[clamp(2rem,6.5vw,3.6rem)]">
            Your first Hacktoberfest PR, <span className="text-hf">in a repo that will actually review it.</span>
          </h1>
          <p className="prose-sans mt-5 max-w-2xl text-[1.05rem]">
            Every project below takes part in Hacktoberfest, replies to newcomers and merges their work. Each comes with
            open issues you could pick up today, and what to do next.
          </p>
          <p className="mt-3 text-[0.78rem] text-faint">This page is for October. Outside Hacktoberfest, use <Link href="/find" className="text-link">find a project</Link>.</p>
          <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-3">
            <a href="#tips" className="bracket-link bracket-link--hf">[ 5 tips so your PR isn&apos;t ignored ]</a>
            <ShareBar url={`${SITE_URL}/hacktoberfest`} text={`Doing Hacktoberfest ${YEAR}? These repos actually review newcomers' pull requests:`} />
          </div>
        </div>
      </section>

      <div className="wrap py-10 sm:py-12">
        <nav aria-label="Language" className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
          <ul className="flex w-max gap-2 sm:w-auto sm:flex-wrap">
            {LANGS.map((l) => (
              <li key={l.id}>
                <Link
                  href={l.id === "all" ? "/hacktoberfest" : `/hacktoberfest?lang=${l.id}`}
                  scroll={false}
                  aria-current={l.id === tab.id ? "page" : undefined}
                  className={`chip min-h-11 whitespace-nowrap px-4 text-[0.85rem] transition-colors ${l.id === tab.id ? "border-hf bg-hf text-bg" : "hover:border-hf hover:text-ink"}`}
                >
                  {l.label}
                  {l.id !== "all" && <span className="sr-only"> projects</span>}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <section aria-label={`Welcoming Hacktoberfest projects: ${tab.label}`} className="mt-8">
          {!result.ok ? (
            <ErrorPanel error={result.error} retryHref={here} />
          ) : result.data.status === "queued" ? (
            <FindRunner key={tab.id} jobId={result.data.job_id} days={7} retryHref={here} />
          ) : (
            <FindResults results={result.data.results} days={7} />
          )}
        </section>
      </div>

      <section aria-labelledby="how" className="border-t border-line bg-panel py-14 sm:py-20">
        <div className="wrap grid gap-12 lg:grid-cols-2">
          <div>
            <h2 id="how" className="h2">How Hacktoberfest works</h2>
            <ol className="mt-8 space-y-6">
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
            <p className="mt-6 font-sans text-[0.9rem] text-faint">
              Holt isn&apos;t affiliated with Hacktoberfest. For the official rules, see{" "}
              <a className="text-link" href="https://hacktoberfest.com" target="_blank" rel="noopener noreferrer">hacktoberfest.com ↗</a>.
            </p>
          </div>
          <div id="tips" className="scroll-mt-24">
            <h2 className="h2">How not to get your PR ignored</h2>
            <ol className="mt-8 space-y-5">
              {TIPS.map(([title, body]) => (
                <li key={title} className="flex gap-3">
                  <span aria-hidden="true" className="text-green">→</span>
                  <p className="font-sans text-muted">
                    <strong className="font-semibold text-ink">{title}</strong> {body}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      <section className="py-14 text-center">
        <div className="wrap max-w-2xl">
          <CatFace mood="adoring" className="text-[1.8rem]" />
          <p className="mt-4 text-[1.3rem] font-semibold tracking-tight">Already have a repo in mind?</p>
          <p className="mt-2 font-sans text-muted">Check whether it reviews newcomers before you spend your October on it.</p>
          <Link href="/" className="bracket-link mt-6">[ check any repo → ]</Link>
        </div>
      </section>
    </>
  );
}
