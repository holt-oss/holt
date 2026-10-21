"use client";

import { useEffect, useState } from "react";
import { issueSkill, issueTaken, NONE_FREE, timeAgo } from "@/lib/format";
import type { StarterIssue } from "@/lib/types";

/** How many the quick look shows: enough to choose from, few enough that it never scrolls. */
const SHOWN = 3;

// Issues already fetched in this tab, so paging back and forth doesn't ask again.
const fetched = new Map<string, StarterIssue[] | "unavailable">();

type State = StarterIssue[] | "unavailable" | null;

/**
 * The repo's good first issues, three compact rows. A list that came with its
 * issues (picks, search) uses them; Discover cards don't carry any, so the
 * view asks for them when it opens (`/api/repos/…/starter-issues`, cached for
 * an hour on the server). Rows keep their height while loading.
 */
export function FocusIssues({ repo, initial }: { repo: string; initial: StarterIssue[] }) {
  const [state, setState] = useState<State>(() => (initial.length ? initial : (fetched.get(repo) ?? null)));

  useEffect(() => {
    if (state !== null) return;
    let cancelled = false;
    fetch(`/api/repos/${repo}/starter-issues`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        const next: NonNullable<State> = Array.isArray(d?.issues) ? d.issues : "unavailable";
        if (next !== "unavailable") fetched.set(repo, next);
        if (!cancelled) setState(next);
      })
      .catch(() => !cancelled && setState("unavailable"));
    return () => {
      cancelled = true;
    };
  }, [repo, state]);

  const link = `https://github.com/${repo}/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22`;
  const issues = Array.isArray(state) ? state.slice(0, SHOWN) : [];
  return (
    <section aria-label="Good first issues" className="mt-4">
      <div className="flex items-baseline justify-between gap-3 font-sans text-[0.8rem]">
        <h3 className="text-faint">Good first issues</h3>
        <a href={link} target="_blank" rel="noopener noreferrer" className="text-faint hover:text-blue">
          all on GitHub ↗
        </a>
      </div>
      {state === null ? (
        <ul aria-busy="true" aria-label="Loading good first issues" className="mt-2 grid min-w-0 grid-cols-1 gap-2">
          {Array.from({ length: SHOWN }, (_, i) => (
            <li key={i} className="h-[3.1rem] animate-pulse border border-line bg-panel-2" />
          ))}
        </ul>
      ) : issues.length === 0 ? (
        <p className="mt-2 border border-dashed border-line px-3 py-3 font-sans text-[0.85rem] text-muted">
          {state === "unavailable" ? "Holt can't list its starter issues right now." : "No open, unclaimed starter issues right now."}
        </p>
      ) : (
        <>
          {issues.every(issueTaken) && <p className="mt-2 font-sans text-[0.85rem] text-amber">{NONE_FREE}</p>}
          <ul className="mt-2 grid min-w-0 grid-cols-1 gap-2">
            {issues.map((i) => (
              <IssueRow key={i.number} issue={i} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function IssueRow({ issue }: { issue: StarterIssue }) {
  const taken = issueTaken(issue);
  // The skill, else the label the row always showed.
  const tag = issueSkill(issue) ?? issue.labels[0];
  return (
    <li className="card-hover group relative min-w-0 border border-line bg-panel px-3 py-2">
      <p className={`flex items-baseline gap-2 font-sans text-[0.88rem] leading-snug ${taken ? "text-muted" : "font-semibold text-ink"}`}>
        <span className="shrink-0 font-mono text-[0.8rem] font-normal text-blue">#{issue.number}</span>
        <a href={issue.url} target="_blank" rel="noopener noreferrer" data-umami-event="starter-issue-click" className="min-w-0 truncate after:absolute after:inset-0 group-hover:text-blue">
          {issue.title}
          <span className="sr-only left-0 top-0"> (opens GitHub)</span>
        </a>
      </p>
      <p className="mt-0.5 flex items-center gap-x-2 overflow-hidden whitespace-nowrap font-sans text-[0.76rem] text-faint">
        {issue.on_it && <span className={taken ? "text-amber" : "text-green"}>{issue.on_it}</span>}
        {tag && <span className="truncate before:mr-2 before:content-['·']">{tag}</span>}
        <span className="ml-auto shrink-0">
          {issue.comments} comment{issue.comments === 1 ? "" : "s"}
          {issue.created_at && <> · {timeAgo(issue.created_at)}</>}
        </span>
      </p>
    </li>
  );
}
