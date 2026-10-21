"use client";
// /compare's one table: a column per repo, the verdict and its reason first,
// then every number on its own row so the eye runs straight across, the best
// marked on each (among repos worth trying: lib/compare.ts, `contenders`).
// Columns whose check is still running fill in when it lands (and the marks
// move with them). Phones: each row's label sits above its numbers, and three
// or four columns swipe sideways, a column at a time (the page says so above).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ABOUT_ROWS, aboutCells, anyLead, cells, contenders, leaders, ROWS, type Cell, type Lead } from "@/lib/compare";
import { fullStats, langColor } from "@/lib/repo-card";
import { friendlyStage } from "@/lib/stages";
import type { Report, StarterIssue } from "@/lib/types";
import { TONE } from "../report/tone";
import { OddsBar } from "../repo-card/odds-bar";
import { LangDot, RepoAvatar } from "../repo-card/repo-avatar";
import { useAnalysis } from "../use-analysis";

export type Column = { repo: string; removeHref: string } & (
  | { kind: "report"; report: Report }
  /** Not checked recently, signed in: the check runs here. */
  | { kind: "live" }
  /** Anything else (sign in to check, an error), drawn by the server. */
  | { kind: "note"; note: React.ReactNode }
);

/** `now` is the server's clock, so "2 days ago" reads the same before and after hydration. */
export function CompareTable({ columns, issues, label, now }: { columns: Column[]; issues: React.ReactNode[]; label: string; now: number }) {
  const [landed, setLanded] = useState<Record<string, Report>>({});
  const router = useRouter();
  // The page's sentence and key are the server's: read them again now this column has a report.
  const onLanded = useCallback(
    (repo: string, r: Report) => {
      setLanded((m) => ({ ...m, [repo]: r }));
      router.refresh();
    },
    [router],
  );
  const reports = columns.map((c) => (c.kind === "report" ? c.report : landed[c.repo] ?? null));
  const lead = leaders(contenders(reports));
  const all = reports.map((r) => r && cells(r));
  const about = reports.map((r) => r && aboutCells(r.about, now));

  return (
    <div className="cmp-scroll" data-many={columns.length > 2 || undefined}>
      <div role="table" aria-label={label} className="cmp" style={{ "--n": columns.length } as React.CSSProperties}>
        <div role="row" className="cmp-row cmp-head">
          <div role="columnheader" className="cmp-label cmp-corner">
            {anyLead(lead) && <span className="text-faint"><span className="text-green">▲</span> best of these</span>}
          </div>
          {columns.map((c, i) => (
            <ColumnHead key={c.repo} repo={reports[i]?.repo ?? c.repo} removeHref={c.removeHref} tone={reports[i]?.tone} />
          ))}
        </div>

        <div role="row" className="cmp-row">
          <div role="rowheader" className="cmp-label sr-only">Verdict</div>
          {columns.map((c, i) => {
            const r = reports[i];
            return (
              <div role="cell" key={c.repo} className="cmp-cell">
                {r ? (
                  <>
                    <p className={`inline-flex items-center gap-2 text-[0.95rem] font-semibold tracking-tight ${TONE[r.tone].text}`}>
                      <span aria-hidden="true" className={`size-1.5 rounded-full ${TONE[r.tone].bg}`} />
                      {r.headline}
                    </p>
                    <OddsBar stats={fullStats(r.stats)} className="mt-3 h-1.5" />
                    <p className="mt-3 font-sans text-[0.84rem] leading-snug text-muted">{r.verdict_line}</p>
                  </>
                ) : c.kind === "live" ? (
                  <LiveCheck repo={c.repo} onLanded={onLanded} />
                ) : c.kind === "note" ? (
                  c.note
                ) : null}
              </div>
            );
          })}
        </div>

        <Group label="Outside pull requests" />
        {ROWS.map((row, n) => (
          <div role="row" key={row.id} className="cmp-row">
            <div role="rowheader" className="cmp-label"><span>{row.label}</span></div>
            {columns.map((c, i) => {
              const cell = all[i]?.[row.id];
              const best = row.id !== "way" && lead[row.id as Lead].includes(i);
              return (
                <div role="cell" key={c.repo} className="cmp-cell">
                  {cell ? (
                    <Value cell={cell} best={best} code={row.id === "way"} />
                  ) : (
                    <>
                      <span className="text-faint">–</span>
                      {/* Say once, at the top of an empty column, why it's empty. */}
                      {n === 0 && <span className="cmp-sub">{c.kind === "live" ? "after the check" : "not checked yet"}</span>}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        ))}

        <Group label="The project" />
        {ABOUT_ROWS.map((row) => (
          <div role="row" key={row.id} className="cmp-row">
            <div role="rowheader" className="cmp-label"><span>{row.label}</span></div>
            {columns.map((c, i) => {
              const cell = about[i]?.[row.id];
              return (
                <div role="cell" key={c.repo} className="cmp-cell">
                  {cell ? (
                    <span className={`cmp-main ${row.id === "stars" ? "cmp-stars" : ""} ${cell.tone === "bad" ? "text-orange" : cell.tone === "none" ? "text-faint" : "text-ink"}`}>
                      {cell.lang && <LangDot color={langColor(cell.lang)} />}
                      {row.id === "stars" && cell.tone !== "none" && <span aria-hidden="true" className="text-amber">★</span>}
                      {cell.main}
                      {row.id === "stars" && cell.tone !== "none" && <span className="sr-only"> stars</span>}
                    </span>
                  ) : (
                    <span className="text-faint">–</span>
                  )}
                  {cell?.sub && <span className="cmp-sub">{cell.sub}</span>}
                </div>
              );
            })}
          </div>
        ))}

        <Group label="Where to start" />
        <div role="row" className="cmp-row">
          <div role="rowheader" className="cmp-label"><span>Starter issues</span></div>
          {columns.map((c, i) => (
            <div role="cell" key={c.repo} className="cmp-cell">
              {c.kind === "report" ? issues[i] : landed[c.repo] ? <LiveIssues repo={c.repo} /> : <span className="text-faint">–</span>}
            </div>
          ))}
        </div>

        <div role="row" className="cmp-row cmp-foot">
          <div role="rowheader" className="cmp-label sr-only">Report</div>
          {columns.map((c, i) => (
            <div role="cell" key={c.repo} className="cmp-cell">
              {reports[i] && (
                <Link href={`/${reports[i].repo}`} className="inline-flex min-h-11 items-center gap-1.5 text-[0.85rem] text-blue transition-colors hover:text-ink">
                  Full report <span aria-hidden="true">→</span>
                  <span className="sr-only"> for {reports[i].repo}</span>
                </Link>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/** A repo's name, with a bar in its verdict's colour across the top of the column (none until it's checked). */
function ColumnHead({ repo, removeHref, tone }: { repo: string; removeHref: string; tone?: Report["tone"] }) {
  const [owner, name] = repo.split("/");
  return (
    <div role="columnheader" className={`cmp-cell cmp-col-head relative border-t-2 ${tone ? TONE[tone].border : "border-transparent"}`}>
      {/* The name wraps (a narrow column would cut it to a few letters); the remove button sits in the corner, off the name's line. */}
      <div className="flex items-start gap-2.5 pr-4">
        <span className="hidden sm:block"><RepoAvatar repo={repo} size={28} /></span>
        <Link href={`/${repo}`} className="-my-1.5 min-w-0 flex-1 py-1.5 leading-tight [overflow-wrap:anywhere] hover:text-blue" title={repo}>
          <span className="line-clamp-2 text-[0.78rem] text-faint">{owner}/</span>
          <span className="line-clamp-3 text-[0.98rem] font-semibold tracking-tight">{name}</span>
        </Link>
      </div>
      <Link href={removeHref} className="absolute right-0 top-0 grid size-11 place-items-center text-faint transition-colors hover:text-orange" aria-label={`Remove ${repo}`}>
        <svg className="size-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </Link>
    </div>
  );
}

/** A small heading between groups of rows. */
function Group({ label }: { label: string }) {
  return (
    <div role="row" className="cmp-row cmp-group">
      <div role="rowheader" className="cmp-label">
        <span>{label}</span>
      </div>
    </div>
  );
}

function Value({ cell, best, code }: { cell: Cell; best: boolean; code: boolean }) {
  const colour = best ? "text-green" : cell.tone === "bad" ? "text-orange" : cell.tone === "none" ? "text-faint" : "text-ink";
  const main = code && cell.tone !== "none" ? <code className="break-all text-[0.86rem]">{cell.main}</code> : cell.main;
  return (
    <>
      <span className={`cmp-main ${colour}`}>
        {main}
        {best && (
          <span className="cmp-best" title="Best of these">
            ▲<span className="sr-only"> (best of these)</span>
          </span>
        )}
      </span>
      {cell.sub && <span className="cmp-sub">{cell.sub}</span>}
    </>
  );
}

/** A repo nobody checked recently: the check runs in its verdict cell. */
function LiveCheck({ repo, onLanded }: { repo: string; onLanded: (repo: string, r: Report) => void }) {
  const { state, retry } = useAnalysis(repo, "rules", 7);
  const report = state.phase === "done" ? state.report : null;
  useEffect(() => {
    if (report) onLanded(repo, report);
  }, [report, repo, onLanded]);
  if (state.phase === "error")
    return (
      <div className="font-sans text-[0.86rem]" role="alert">
        <p className="text-orange">{state.error.message}</p>
        {(state.error.code === "upstream" || state.error.code === "internal") && (
          <button type="button" onClick={retry} className="mt-2 min-h-11 text-link">try again</button>
        )}
      </div>
    );
  const p = state.phase === "running" ? state.progress : 0.03;
  return (
    <div aria-live="polite" aria-busy="true">
      <p className="text-[0.84rem] text-ink">{friendlyStage(state.phase === "running" ? state.stage : undefined).title}…</p>
      <div className="mt-2.5 h-1.5 bg-panel-2">
        <div className="h-full bg-blue transition-[width] duration-500" style={{ width: `${Math.max(3, p * 100)}%` }} />
      </div>
    </div>
  );
}

/** Starter issues for a column whose check just landed (the others come from the server). */
function LiveIssues({ repo }: { repo: string }) {
  const [issues, setIssues] = useState<StarterIssue[] | null | "none">(null);
  useEffect(() => {
    const ctl = new AbortController();
    fetch(`/api/repos/${repo}/starter-issues`, { signal: ctl.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { issues?: StarterIssue[] } | null) => setIssues(d?.issues ?? "none"))
      .catch(() => {});
    return () => ctl.abort();
  }, [repo]);
  if (issues === null) return <IssuesSkeleton />;
  return <Issues issues={issues === "none" ? null : issues} />;
}

/** Up to two issues to start with, each with who's already on it. Null when they couldn't be read. */
export function Issues({ issues }: { issues: StarterIssue[] | null }) {
  if (!issues) return <span className="text-faint">–</span>;
  if (!issues.length) return <span className="text-[0.86rem] text-faint">none open</span>;
  return (
    <ul className="space-y-3">
      {issues.slice(0, 2).map((i) => (
        <li key={i.number} className="relative font-sans text-[0.86rem] leading-snug">
          <a href={i.url} target="_blank" rel="noopener noreferrer" data-umami-event="starter-issue-click" className="line-clamp-2 text-ink transition-colors after:absolute after:inset-0 hover:text-blue">
            <span className="font-mono text-[0.8rem] text-blue">#{i.number}</span> {i.title}
            <span className="sr-only"> (opens GitHub)</span>
          </a>
          {i.on_it && <span className={`mt-0.5 block text-[0.78rem] ${i.people || i.open_prs ? "text-amber" : "text-muted"}`}>{i.on_it}</span>}
        </li>
      ))}
    </ul>
  );
}

export function IssuesSkeleton() {
  return (
    <span aria-hidden="true" className="block space-y-2">
      <span className="sk block h-3 w-11/12" />
      <span className="sk block h-3 w-2/3" />
    </span>
  );
}
