import { nextStep, timeAgo } from "@/lib/format";
import type { StarterIssue } from "@/lib/types";

export function StarterIssueCard({ issue, compact = false }: { issue: StarterIssue; compact?: boolean }) {
  return (
    <li className="group relative border border-line bg-panel p-4 shadow-soft transition-colors hover:border-blue sm:p-5">
      <div className="flex flex-wrap items-center gap-2 text-[0.72rem] text-faint">
        <span className="text-blue">#{issue.number}</span>
        {issue.labels.slice(0, 3).map((l) => (
          <span key={l} className="chip min-h-0 py-0.5">{l}</span>
        ))}
        <span className="ml-auto">
          {issue.comments} comment{issue.comments === 1 ? "" : "s"}
          {issue.created_at && <> · {timeAgo(issue.created_at)}</>}
        </span>
      </div>
      <h3 className="mt-2 font-sans text-[1rem] font-semibold leading-snug text-ink">
        <a href={issue.url} target="_blank" rel="noopener noreferrer" className="after:absolute after:inset-0 group-hover:text-blue">
          {issue.title}
          <span className="sr-only"> (opens GitHub)</span>
        </a>
      </h3>
      {!compact && issue.why.length > 0 && (
        <ul className="mt-2 space-y-0.5 font-sans text-[0.85rem] text-muted">
          {issue.why.map((w) => (
            <li key={w} className="flex gap-2">
              <span aria-hidden="true" className="text-faint">·</span>
              {w}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 flex gap-2 border-t border-dashed border-line pt-3 text-[0.8rem] text-green">
        <span aria-hidden="true">→</span>
        <span>
          <span className="sr-only">What to do next: </span>
          {nextStep(issue)}
        </span>
      </p>
    </li>
  );
}

/** null = still loading; "unavailable" = the server couldn't list them. */
export type IssuesState = StarterIssue[] | null | "unavailable";

export function StarterIssues({ issues, repo }: { issues: IssuesState; repo: string }) {
  const ghLink = `https://github.com/${repo}/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22`;
  if (issues === "unavailable") {
    return (
      <p className="font-sans text-muted">
        Holt can&apos;t list starter issues for this repo right now.{" "}
        <a className="text-link" href={ghLink} target="_blank" rel="noopener noreferrer">
          See its good first issues on GitHub ↗
        </a>
      </p>
    );
  }
  if (issues === null) {
    return (
      <ul className="grid gap-3" aria-busy="true">
        {[0, 1].map((i) => (
          <li key={i} className="h-32 animate-pulse border border-line bg-panel" />
        ))}
      </ul>
    );
  }
  if (!issues.length) {
    return (
      <p className="font-sans text-muted">
        No open, unclaimed starter issues right now.{" "}
        <a className="text-link" href={ghLink} target="_blank" rel="noopener noreferrer">
          Check GitHub for new ones ↗
        </a>
      </p>
    );
  }
  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {issues.map((i) => (
        <StarterIssueCard key={i.number} issue={i} />
      ))}
    </ul>
  );
}
