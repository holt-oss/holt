// The full report. Shared by the server page (cached report) and the client
// runner (report that just finished streaming), so no server-only imports.
import Link from "next/link";
import { shortDate, timeAgo, verdictLine, VERDICT_TONE } from "@/lib/format";
import { SITE_URL } from "@/lib/site";
import type { Report } from "@/lib/types";
import { CatFace } from "../cat-face";
import { BadgeSnippet } from "./badge-snippet";
import { EvidenceList } from "./evidence-list";
import { LandingMap } from "./landing-map";
import { ShareBar } from "./share-bar";
import { StarterIssues, type IssuesState } from "./starter-issues";
import { StatsGrid } from "./stats-grid";
import { TONE, VERDICT_MOOD } from "./tone";
import { UpgradeCard } from "./upgrade-card";

export function Section({ n, title, id, children, note }: { n: string; title: string; id: string; children: React.ReactNode; note?: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="border-t border-line pt-8">
      <div className="mb-5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-[0.72rem] text-blue">{n}</span>
        <h2 id={id} className="text-[1.25rem] font-semibold tracking-tight sm:text-[1.4rem]">{title}</h2>
        {note && <span className="font-sans text-[0.85rem] text-faint">{note}</span>}
      </div>
      {children}
    </section>
  );
}

export function VerdictHero({ report }: { report: Report }) {
  const tone = VERDICT_TONE[report.verdict];
  const t = TONE[tone];
  return (
    <div className={`relative overflow-hidden border border-line-strong bg-panel shadow-card`}>
      <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-1 ${t.bg}`} />
      <div className="p-5 pl-6 sm:p-8 sm:pl-10">
        <div className="flex items-center justify-between gap-4 text-[0.72rem] uppercase tracking-[0.08em] text-faint">
          <span>verdict · {report.mode === "ai" ? "AI report" : "rules report"} · {report.days}-day budget</span>
          <CatFace mood={VERDICT_MOOD[report.verdict]} blink className="text-[1.1rem] normal-case tracking-normal sm:text-[1.5rem]" />
        </div>
        <h1 className={`display mt-4 text-[2.6rem] sm:text-[4rem] ${t.text}`}>
          {report.headline}
          <span className="text-ink">.</span>
        </h1>
        <p className="mt-4 max-w-2xl font-sans text-[1.05rem] leading-relaxed text-ink sm:text-[1.15rem]">{verdictLine(report)}</p>
        <p className="mt-4 text-[0.74rem] text-faint">
          Based on {report.stats.outsider_attempts} pull requests from outside contributors · data until {shortDate(report.evidence_until)} · checked{" "}
          <time dateTime={report.generated_at} suppressHydrationWarning>{timeAgo(report.generated_at)}</time>
        </p>
      </div>
    </div>
  );
}

export function ReportView({
  report,
  issues,
  signedIn,
}: {
  report: Report;
  issues: IssuesState;
  signedIn: boolean;
}) {
  const repo = report.repo;
  const url = `${SITE_URL}/${repo}`;
  const shareText = `${repo} on Holt: ${report.headline}.`;
  const viable = report.verdict === "viable";

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-10">
      <div className="min-w-0 space-y-10">
        <VerdictHero report={report} />

        {report.summary && (
          <div className="border-l-2 border-blue pl-5">
            <p className="text-[0.72rem] uppercase tracking-[0.08em] text-blue">AI explanation</p>
            <p className="mt-2 font-sans text-[1.02rem] leading-relaxed text-ink">{report.summary}</p>
            <p className="mt-2 text-[0.72rem] text-faint">
              Written by {report.cost?.model ?? "a model"} from the evidence below. The verdict itself comes from fixed rules.
            </p>
          </div>
        )}

        <div className="lg:hidden">
          <ShareBar url={url} text={shareText} />
        </div>

        {!viable && (
          <div className="flex flex-wrap items-center justify-between gap-3 border border-dashed border-line-strong p-4">
            <p className="font-sans text-[0.95rem] text-muted">Looking for somewhere friendlier to start?</p>
            <Link href="/find" className="bracket-link">[ find a welcoming project → ]</Link>
          </div>
        )}

        <Section n="01" id="issues" title={viable ? "Your first contribution" : "Starter issues"} note="open and unclaimed, best first">
          <StarterIssues issues={issues} repo={repo} />
        </Section>

        <Section n="02" id="numbers" title="What happened to outside contributors">
          <StatsGrid stats={report.stats} />
        </Section>

        <Section n="03" id="landing" title="Where newcomer work lands">
          <LandingMap landing={report.landing} neverLanded={report.never_landed} />
        </Section>

        <Section n="04" id="why" title="Why this verdict">
          <ul className="space-y-2 font-sans text-[0.98rem]">
            {report.decided_by.map((d) => (
              <li key={d} className="flex gap-3">
                <span aria-hidden="true" className={TONE[VERDICT_TONE[report.verdict]].text}>→</span>
                <span>{d}</span>
              </li>
            ))}
          </ul>
          {report.unknowns.length > 0 && (
            <div className="mt-5">
              <p className="text-[0.72rem] uppercase tracking-[0.08em] text-faint">What Holt couldn&apos;t check</p>
              <ul className="mt-2 space-y-1.5 font-sans text-[0.92rem] text-muted">
                {report.unknowns.map((u) => (
                  <li key={u} className="flex gap-3">
                    <span aria-hidden="true">?</span>
                    <span>{u}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Section>

        <Section n="05" id="evidence" title="The evidence" note="every claim links to GitHub">
          <EvidenceList evidence={report.evidence} />
        </Section>

        <div className="lg:hidden space-y-4">
          {report.mode === "rules" && <UpgradeCard repo={repo} signedIn={signedIn} />}
          <BadgeSnippet repo={repo} />
        </div>
      </div>

      <aside className="hidden lg:block" aria-label="Share and more">
        <div className="sticky top-24 space-y-4">
          <div className="panel p-4">
            <p className="mb-3 text-[0.72rem] uppercase tracking-[0.08em] text-faint">Share this report</p>
            <ShareBar url={url} text={shareText} />
          </div>
          {report.mode === "rules" && <UpgradeCard repo={repo} signedIn={signedIn} />}
          <BadgeSnippet repo={repo} />
          <Link href={`/compare?repos=${repo}`} className="block text-[0.8rem] text-muted hover:text-ink">
            [ compare with another repo → ]
          </Link>
        </div>
      </aside>
    </div>
  );
}
