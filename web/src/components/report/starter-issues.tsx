import { issueSkill, issueTaken, NONE_FREE, nextStep, timeAgo } from "@/lib/format";
import type { StarterIssue } from "@/lib/types";
import { Skeleton, SkeletonRegion } from "../skeleton";

export function StarterIssueCard({ issue, compact = false }: { issue: StarterIssue; compact?: boolean }) {
  return (
    <li className="card-hover group relative border border-line bg-panel p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-2 text-[0.8rem] text-faint">
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
        <a href={issue.url} target="_blank" rel="noopener noreferrer" data-umami-event="starter-issue-click" className="after:absolute after:inset-0 group-hover:text-blue">
          {issue.title}
          <span className="sr-only"> (opens GitHub)</span>
        </a>
      </h3>
      {issue.on_it && (
        <p className={`mt-1 font-sans text-[0.88rem] ${issueTaken(issue) ? "text-amber" : "text-green"}`}>{issue.on_it}</p>
      )}
      {!compact && issue.why.length > 0 && (
        <ul className="mt-2 space-y-0.5 font-sans text-[0.89rem] text-muted">
          {issue.why.map((w) => (
            <li key={w} className="flex gap-2">
              <span aria-hidden="true" className="text-faint">·</span>
              {w}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 flex gap-2 border-t border-line pt-3 font-sans text-[0.9rem] text-green">
        <span aria-hidden="true">→</span>
        <span>
          <span className="sr-only">What to do next: </span>
          {nextStep(issue)}
        </span>
      </p>
    </li>
  );
}

/**
 * One issue as a thin row for the report: number, title, its labels, whether
 * anyone is on it, the skill it names, and its age, on one line from `sm` up
 * (two on a phone). The whole row is the link; the next step is in its tooltip
 * and read out after it. A taken issue's title is dimmed.
 */
export function StarterIssueRow({ issue }: { issue: StarterIssue }) {
  const taken = issueTaken(issue);
  const skill = issueSkill(issue);
  const step = nextStep(issue);
  // The skill is one of the labels more often than not; it isn't said twice.
  const labels = issue.labels.filter((l) => l.toLowerCase() !== skill?.toLowerCase()).slice(0, 2);
  return (
    // The title gets its own line, so it is never squeezed by the details;
    // whether anyone is on it, the comments and the age go under it.
    <li className="group relative grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 py-2 hover:bg-panel-2/50" title={step}>
      <span className="font-mono text-[0.82rem] leading-[1.45] text-blue">#{issue.number}</span>
      <a href={issue.url} target="_blank" rel="noopener noreferrer" data-umami-event="starter-issue-click" className={`min-w-0 truncate font-sans text-[0.93rem] leading-[1.4] after:absolute after:inset-0 group-hover:text-blue ${taken ? "text-muted" : "font-medium text-ink"}`}>
        {issue.title}
        <span className="sr-only"> (opens GitHub). {step}</span>
      </a>
      <p className="col-start-2 mt-0.5 flex min-w-0 flex-wrap gap-x-2 font-sans text-[0.78rem] text-faint">
        <span className={taken ? "text-amber" : "text-green"}>{issue.on_it ?? (taken ? "Someone is on it" : "Nobody on it yet")}</span>
        {skill && (
          <>
            <span aria-hidden="true">·</span>
            <span className="text-muted">{skill}</span>
          </>
        )}
        <span aria-hidden="true">·</span>
        <span>
          {issue.comments} comment{issue.comments === 1 ? "" : "s"}
          {issue.created_at && <> · {timeAgo(issue.created_at)}</>}
        </span>
        {labels.length > 0 && (
          <>
            <span aria-hidden="true" className="hidden sm:inline">·</span>
            <span className="hidden max-w-[16rem] truncate sm:inline">{labels.join(", ")}</span>
          </>
        )}
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
  if (issues === null) return <StarterIssuesSkeleton />;
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
    <>
      {issues.every(issueTaken) && <p className="mb-2 font-sans text-[0.89rem] text-amber">{NONE_FREE}</p>}
      <ul className="divide-y divide-line border-y border-line">
        {issues.map((i) => (
          <StarterIssueRow key={i.number} issue={i} />
        ))}
      </ul>
    </>
  );
}

/** Three thin rows, where the issues will stream in. */
export function StarterIssuesSkeleton() {
  return (
    <SkeletonRegion as="ul" label="Loading starter issues…" className="divide-y divide-line border-y border-line">
      {[0, 1, 2].map((i) => (
        <li key={i} className="space-y-1.5 py-2.5">
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-3 w-2/5" />
        </li>
      ))}
    </SkeletonRegion>
  );
}
