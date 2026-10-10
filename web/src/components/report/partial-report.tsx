// What a signed-out visitor sees on a report that isn't one of the examples
// (lib/gate.ts), once it has one: the verdict, its reason, the odds and one
// number, in the page's HTML so shared links and search engines get the
// answer. The rest of the report sits locked under one sign-in button: its
// real section names over neutral placeholders, never made-up numbers.
// (With no report, the page shows ReportTeaser, which offers a check.)
import Link from "next/link";
import { statLines, timeAgo } from "@/lib/format";
import { signInHref } from "@/lib/gate";
import { fullStats } from "@/lib/repo-card";
import { SITE_URL } from "@/lib/site";
import type { Report } from "@/lib/types";
import { CatFace } from "../cat-face";
import { OddsBar } from "../repo-card/odds-bar";
import { Skeleton, SkeletonText } from "../skeleton";
import { ShareMenu } from "./share-bar";
import { TONE, TONE_MOOD } from "./tone";
import { VerdictCat } from "./verdict-cat";

/**
 * A real report, partly: the verdict, its reason, the odds and the first
 * number; the rest locked. `land`: the check just finished on this page, so
 * the answer lands as it does on the full report (report-view.tsx, VerdictHero).
 */
export function PartialReport({ report, back, land }: { report: Report; back: string; land?: boolean }) {
  const t = TONE[report.tone];
  // No outside PR to count (pull requests off, say): no odds, and no "0 of 0".
  const lead = report.stats.outsider_attempts > 0 ? statLines(report.stats)[0] : undefined;
  return (
    <div className="max-w-4xl space-y-6" data-teaser>
      {/* The same compact card as the full report's (report-view.tsx, VerdictHero), with the odds and one number. */}
      <div className="relative overflow-hidden border border-line-strong bg-panel shadow-card" data-verdict-hero>
        <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-1 ${t.bg} ${land ? "land-bar" : ""}`} />
        <div className="p-4 pl-5 sm:p-5 sm:pl-7">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <h1 className={`inline-flex items-center gap-2 border px-2.5 py-1 text-[0.95rem] font-semibold sm:text-[1rem] ${t.text} ${t.border} ${t.soft}`}>
                <span aria-hidden="true" className={`size-1.5 rounded-full ${t.bg}`} />
                {report.headline}
              </h1>
            </div>
            {land ? (
              <VerdictCat mood={TONE_MOOD[report.tone]} className="text-[1rem] normal-case tracking-normal sm:text-[1.2rem]" />
            ) : (
              <CatFace mood={TONE_MOOD[report.tone]} blink className="text-[1rem] normal-case tracking-normal sm:text-[1.2rem]" />
            )}
          </div>
          <p className="mt-3 max-w-3xl font-sans text-[1rem] leading-snug text-ink sm:text-[1.05rem]" data-line="reason">
            {report.verdict_line}
          </p>
          {lead && (
            <div className="mt-3 max-w-2xl" data-odds>
              <OddsBar stats={fullStats(report.stats)} className="h-2.5" />
              <p className="mt-2 font-sans text-[0.93rem] text-muted" data-line="lead-number">
                <span className={`mr-2 font-mono text-[1.15rem] font-semibold tracking-tight ${lead.tone === "neutral" ? "text-ink" : TONE[lead.tone].text}`}>{lead.big}</span>
                {lead.label}
              </p>
            </div>
          )}
          <p className="mt-3 text-[0.78rem] text-faint">
            checked <time dateTime={report.generated_at} suppressHydrationWarning>{timeAgo(report.generated_at)}</time>
          </p>
        </div>
      </div>

      <div className="flex justify-end">
        <ShareMenu url={`${SITE_URL}/${report.repo}`} text={`${report.repo} on Holt: ${report.headline}.`} />
      </div>

      <section aria-label="The full report" className="relative" data-locked>
        {/* The report's own sections over placeholders: no numbers, real or made up, until sign-in. */}
        <div aria-hidden="true" inert className="pointer-events-none select-none space-y-8 blur-[3px] sk-still [mask-image:linear-gradient(#000_40%,transparent)]">
          {LOCKED.map((s) => (
            <div key={s.title}>
              <p className="mb-3 text-[1.05rem] font-semibold tracking-tight sm:text-[1.15rem]">{s.title}</p>
              {s.body}
            </div>
          ))}
        </div>
        <div className="absolute inset-x-0 top-10 flex justify-center sm:top-14">
          <Link href={signInHref(back)} prefetch={false} className="btn-primary whitespace-nowrap max-sm:px-3" data-signin-card>
            sign in for the full report <span aria-hidden="true">→</span>
          </Link>
        </div>
      </section>
    </div>
  );
}

/** The full report's sections, as placeholders: starter issues as thin rows, the README, where work lands, the evidence. */
const LOCKED = [
  {
    title: "Starter issues",
    body: (
      <span className="block space-y-2">
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-4/5" />
      </span>
    ),
  },
  { title: "README", body: <SkeletonText lines={4} last="55%" /> },
  {
    title: "Where newcomer work lands",
    body: (
      <span className="block space-y-3">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
        <Skeleton className="h-3 w-3/5" />
      </span>
    ),
  },
  { title: "The evidence", body: <SkeletonText lines={3} last="40%" /> },
];
