// The Get-a-badge answer for one repo: its verdict and numbers, then either the
// snippet to paste (a passing repo) or what would change the verdict.
// No server-only imports: rendered by the page for a cached report and by
// BadgeLive for one that just ran.
import Link from "next/link";
import { badgeOffered, badgeSnippets, whatWouldChangeIt } from "@/lib/badge";
import { timeAgo } from "@/lib/format";
import type { Report } from "@/lib/types";
import { CopyButton } from "../copy-button";
import { StatsGrid } from "../report/stats-grid";
import { VerdictPill } from "../report/verdict-pill";

function Snippet({ label, code }: { label: string; code: string }) {
  return (
    <div>
      <p className="mb-1.5 text-[0.8rem] uppercase tracking-[0.08em] text-faint">{label}</p>
      <div className="grid grid-cols-[1fr_auto] border border-line-strong bg-bg">
        <code className="min-w-0 overflow-x-auto whitespace-nowrap px-3 py-3 text-[0.82rem] text-muted">{code}</code>
        <CopyButton text={code} label="copy" className="min-h-11 border-l border-line-strong px-4 text-[0.85rem] text-muted transition-colors hover:bg-ink hover:text-on-accent" />
      </div>
    </div>
  );
}

export function BadgeResult({ report, site }: { report: Report; site: string }) {
  const repo = report.repo;
  const offered = badgeOffered(report);
  const snippets = badgeSnippets(site, repo);
  const advice = whatWouldChangeIt(report);
  return (
    <div className="space-y-6">
      <div className="panel p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-3">
          <Link href={`/${repo}`} className="text-link text-[1.05rem] font-semibold">{repo}</Link>
          <VerdictPill headline={report.headline} tone={report.tone} />
        </div>
        <p className="prose-sans mt-3 max-w-2xl text-[0.98rem]">{report.verdict_line}</p>
        <p className="mt-2 text-[0.82rem] text-faint">
          Checked {timeAgo(report.generated_at)}. <Link href={`/${repo}`} className="text-link">Full report →</Link>
        </p>
      </div>

      <StatsGrid stats={report.stats} limit={3} />

      {offered ? (
        <section aria-labelledby="your-badge" className="panel space-y-5 p-5 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="your-badge" className="text-[1rem] font-semibold text-ink">Your badge</h2>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`/badge/${repo}.svg?v=${encodeURIComponent(report.generated_at)}`}
              alt="Holt badge preview"
              height={20}
              className="h-5 w-auto"
            />
          </div>
          <Snippet label="Markdown (README.md)" code={snippets.markdown} />
          <Snippet label="HTML" code={snippets.html} />
          <p className="font-sans text-[0.89rem] text-muted">
            The badge states facts from your recent PRs and links to the full report. Holt rechecks daily while it&apos;s in
            use. If your repo stops passing, it turns grey and says &ldquo;see report&rdquo;. Never red.
          </p>
        </section>
      ) : (
        <section aria-labelledby="no-badge" className="panel space-y-4 p-5 sm:p-6">
          <h2 id="no-badge" className="text-[1rem] font-semibold text-ink">No badge yet</h2>
          <p className="font-sans text-[0.92rem] text-muted">
            Badges go to repos that are worth a newcomer&apos;s time. This is what decided yours.
          </p>
          {report.decided_by.length > 0 && (
            <ul className="space-y-2 border-l-2 border-line-strong pl-4 font-sans text-[0.92rem] text-ink">
              {report.decided_by.map((d) => <li key={d}>{d}</li>)}
            </ul>
          )}
          <div>
            <p className="mb-2 font-sans text-[0.92rem] font-medium text-ink">What would change it</p>
            <ul className="list-disc space-y-1.5 pl-5 font-sans text-[0.92rem] text-muted">
              {advice.map((a) => <li key={a}>{a}</li>)}
            </ul>
          </div>
          <p className="font-sans text-[0.89rem] text-faint">
            The same written rules judge every repo, from your last few months of PRs. Check again once things change.
          </p>
        </section>
      )}
    </div>
  );
}
