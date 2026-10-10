// What a signed-out visitor sees on a report that isn't one of the examples
// (lib/gate.ts): the verdict and its reason, in the page's HTML so shared
// links and search engines get the answer, and one sign-in card for the rest.
// It never starts a check: with no report yet it only offers one.
import Link from "next/link";
import { EXAMPLES_PATH } from "@/lib/examples";
import { timeAgo } from "@/lib/format";
import { signInHref } from "@/lib/gate";
import type { Report } from "@/lib/types";
import { CatFace } from "../cat-face";
import { TONE, TONE_MOOD } from "./tone";

/** What the full report holds, in the order it shows them. */
const INSIDE = [
  { title: "Starter issues", body: "Open issues you could take today, best first." },
  { title: "The README", body: "The project's own words, to get the feel of it." },
  { title: "Where newcomer work lands", body: "The folders where outside work gets merged, and where it doesn't." },
  { title: "The evidence", body: "Every claim links to the GitHub thread it came from." },
];

export function ReportTeaser({ repo, report, back }: { repo: string; report: Report | null; back: string }) {
  const t = report ? TONE[report.tone] : TONE.neutral;
  return (
    <div className="max-w-4xl space-y-6" data-teaser>
      <div className="relative overflow-hidden border border-line-strong bg-panel shadow-card" data-verdict-hero>
        <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-1 ${t.bg}`} />
        <div className="p-4 pl-5 sm:p-5 sm:pl-7">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              {report ? (
                <h1 className={`inline-flex items-center gap-2 border px-2.5 py-1 text-[0.95rem] font-semibold sm:text-[1rem] ${t.text} ${t.border} ${t.soft}`}>
                  <span aria-hidden="true" className={`size-1.5 rounded-full ${t.bg}`} />
                  {report.headline}
                </h1>
              ) : (
                <h1 className="text-[1.05rem] font-semibold tracking-tight [overflow-wrap:anywhere] sm:text-[1.2rem]">Is {repo} worth your time?</h1>
              )}
              <span className="text-[0.78rem] uppercase tracking-[0.08em] text-faint">{report ? "rules report" : "not checked yet"}</span>
            </div>
            <CatFace mood={report ? TONE_MOOD[report.tone] : "thinking"} blink className="text-[1rem] normal-case tracking-normal sm:text-[1.2rem]" />
          </div>
          {report ? (
            <>
              <p className="mt-3 max-w-3xl font-sans text-[1rem] leading-snug text-ink sm:text-[1.05rem]" data-line="reason">
                {report.verdict_line}
              </p>
              <p className="mt-3 text-[0.78rem] text-faint">
                checked <time dateTime={report.generated_at} suppressHydrationWarning>{timeAgo(report.generated_at)}</time>
              </p>
            </>
          ) : (
            <p className="mt-3 max-w-3xl font-sans text-[1rem] leading-snug text-ink sm:text-[1.05rem]">
              Holt hasn&apos;t checked this repo recently. Sign in and it reads the recent pull requests now: do outsiders
              get replies, and does their work get merged? It takes about 20 seconds.
            </p>
          )}
        </div>
      </div>

      <section aria-labelledby="teaser-signin" className="border border-line-strong bg-panel p-4 sm:p-5" data-signin-card>
        <h2 id="teaser-signin" className="text-[1.05rem] font-semibold tracking-tight sm:text-[1.15rem]">
          {report ? "See why, and where to start" : "Check this repo, free"}
        </h2>
        <p className="mt-1.5 max-w-2xl font-sans text-[0.93rem] text-muted">
          {report ? "The full report is free with an account. Inside:" : "You get the verdict and the full report:"}
        </p>
        <ul className="mt-4 grid gap-px border border-line bg-line sm:grid-cols-2 xl:grid-cols-4">
          {INSIDE.map((s) => (
            <li key={s.title} className="bg-panel-2 p-3.5">
              <p className="text-[0.92rem] font-semibold tracking-tight">{s.title}</p>
              <p className="mt-1 font-sans text-[0.86rem] leading-snug text-muted">{s.body}</p>
            </li>
          ))}
        </ul>
        <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3">
          <Link href={signInHref(back)} prefetch={false} className="btn-primary whitespace-nowrap max-sm:px-3">
            {report ? "sign in for the full report" : "sign in to check it"} <span aria-hidden="true">→</span>
          </Link>
          <Link href={EXAMPLES_PATH} className="text-link inline-flex min-h-11 items-center text-[0.89rem]">
            [ read an example first ]
          </Link>
        </div>
      </section>
    </div>
  );
}
