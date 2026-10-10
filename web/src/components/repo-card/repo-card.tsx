import Link from "next/link";
import { compact } from "@/lib/discover";
import { issueSkill, issueTaken, NONE_FREE } from "@/lib/format";
import { issueSummary, langColor, statPills, type CardRepo } from "@/lib/repo-card";
import { VerdictPill } from "../report/verdict-pill";
import { OddsMeter } from "./odds-bar";
import { LangDot, RepoAvatar } from "./repo-avatar";

/**
 * A repo in a list, about a third of the old height: who, the verdict, the
 * marked odds bar, two more numbers and one issue to start with. Everything else is in
 * the focus view (`focusHref`), which `onOpen` shows without a page load.
 * `verdict={false}` leaves the verdict out, for a list where every repo has
 * the same one; the starter issues' summary takes its place. `why` adds the
 * line that says why this repo for this person (a pick's first reason). A
 * click anywhere on the card that isn't a link or a button opens the focus view.
 */
export function RepoCard({ r, report, focusHref, onOpen, actions, verdict = true, why = false }: { r: CardRepo; report: string; focusHref: string; onOpen?: () => void; actions?: React.ReactNode; verdict?: boolean; why?: boolean }) {
  const [owner, name] = r.repo.split("/");
  // Free issues come first, so a taken one here means every one is taken.
  const issue = r.issues[0];
  const taken = issue ? issueTaken(issue) : false;
  const skill = issue ? issueSkill(issue) : null;
  // The merged share is marked on the bar; the other numbers sit under it as plain text, not tags.
  const pills = statPills(r.stats);
  const rest = r.stats.attempts && r.stats.merged != null ? pills.slice(1) : pills;
  const issues = verdict ? null : issueSummary(r.issues);
  // A plain link without JS or with a modifier key; the in-page view otherwise.
  const open = onOpen && ((e: React.MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault();
    onOpen();
  });
  // The rest of the card opens the focus view too; the name link stays the way in for keyboards and screen readers.
  const openFromCard = onOpen && ((e: React.MouseEvent<HTMLElement>) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    if ((e.target as Element).closest("a, button, [role=dialog]")) return;
    if (window.getSelection()?.toString()) return; // selecting text, not opening
    onOpen();
  });
  return (
    <article onClick={openFromCard} className={`app-card flex h-full flex-col border border-line-strong bg-panel p-4 shadow-soft hover:border-blue/60 ${onOpen ? "cursor-pointer" : ""}`}>
      <div className="flex items-start gap-3">
        <RepoAvatar repo={r.repo} />
        {/* Tall enough for a name, two lines of description and the language, so the rows below line up across the grid. */}
        <div className="min-h-[5.5rem] min-w-0 flex-1">
          {/* The whole name, wrapping after the owner first. */}
          <h2 className="text-[1rem] font-semibold leading-tight tracking-tight [overflow-wrap:anywhere]">
            <a href={focusHref} onClick={open} className="hover:text-blue">
              <span className="text-muted">{owner}/</span>
              <wbr />
              {name}
            </a>
          </h2>
          {r.description && <p className="mt-0.5 line-clamp-2 font-sans text-[0.88rem] leading-snug text-muted" title={r.description}>{r.description}</p>}
          {(r.languageLabel || r.stars != null) && (
            <p className="mt-1.5 flex min-w-0 items-center gap-3 text-[0.8rem] text-faint">
              {r.language && r.languageLabel && (
                <span className="flex min-w-0 items-center gap-1.5" title={r.languageLabel}>
                  <LangDot color={langColor(r.language)} />
                  <span className="truncate">{r.languageLabel}</span>
                </span>
              )}
              {r.stars != null && <span className="shrink-0 whitespace-nowrap tabular-nums"><span aria-hidden="true" className="text-[#e0a526]">★</span> {compact(r.stars)}<span className="sr-only"> stars</span></span>}
            </p>
          )}
        </div>
      </div>

      {/* Two lines tall whatever its length, so the rows below line up across the grid. */}
      {why && r.why[0] && (
        <p className="mt-3 line-clamp-2 min-h-[2.75em] border-l-2 border-blue pl-2.5 font-sans text-[0.88rem] leading-snug text-ink" title={r.why[0]}>{r.why[0]}</p>
      )}

      {/* The verdict or the starter issues on the left, the save button on the right. */}
      {(verdict || issues || actions) && (
        <div className="mt-3 flex items-center gap-3">
          {verdict ? (
            <VerdictPill headline={r.headline} tone={r.tone} className="px-1.5 py-0.5 text-[0.76rem]" />
          ) : issues ? (
            <div className="min-w-0 text-[0.8rem] text-faint">
              <p className="font-sans text-[0.88rem] text-muted">
                {issues.count}
                <span aria-hidden="true" className="mx-1.5">·</span>
                <span className={issues.allTaken ? "text-amber" : "text-green"}>{issues.free}</span>
              </p>
              {issues.areas.length > 0 && (
                <ul aria-label="Kinds of work" className="mt-2 flex flex-wrap gap-1.5 text-[0.76rem]">
                  {issues.areas.map((a) => (
                    <li key={a} className="border border-blue/30 bg-blue/10 px-1.5 py-px font-medium capitalize text-blue">{a}</li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
          {actions && <div className="-my-2 ml-auto flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className="mt-3">
        <OddsMeter stats={r.stats} />
      </div>
      {/* The reply time and first-timers, one per line, with the report link beside them. */}
      <div className="mt-2.5 flex items-center justify-between gap-3">
        <div className="min-w-0 font-sans text-[0.88rem] leading-snug text-muted">
          {/* Reply time in blue, so it stands out from the first-timers count. */}
          {rest.map((p) => <p key={p} className={p.startsWith("replies") ? "text-blue" : undefined}>{p}</p>)}
        </div>
        <Link href={report} className="shrink-0 border border-line-strong px-3 py-1.5 font-sans text-[0.85rem] font-semibold text-ink transition-colors hover:border-blue hover:text-blue">report →</Link>
      </div>

      {issue ? (
        <p className="relative mt-3 border-t border-dashed border-line pt-2.5 font-sans text-[0.88rem] leading-snug">
          <span className={`block font-sans text-[0.78rem] ${taken ? "text-amber" : "text-faint"}`}>{taken ? NONE_FREE : "An issue to start with"}</span>
          <a href={issue.url} target="_blank" rel="noopener noreferrer" data-umami-event="starter-issue-click" className={`mt-0.5 line-clamp-2 after:absolute after:inset-0 hover:text-blue ${taken ? "text-muted" : "font-semibold text-ink"}`}>
            <span className="font-mono text-[0.85rem] font-normal text-blue">#{issue.number}</span> {issue.title}
            <span className="sr-only"> (opens GitHub)</span>
          </a>
          {/* Who is on it only when someone is ("unclaimed" above already says when nobody is), then the skill it names. */}
          {(taken && issue.on_it) || skill ? (
            <span className="mt-0.5 flex flex-wrap gap-x-2 text-[0.8rem] text-faint">
              {taken && issue.on_it && <span className="text-amber">{issue.on_it}</span>}
              {skill && <span>{skill}</span>}
            </span>
          ) : null}
        </p>
      ) : r.reason ? (
        <p className="mt-3 line-clamp-2 border-t border-dashed border-line pt-2.5 font-sans text-[0.88rem] leading-snug text-muted">{r.reason}</p>
      ) : null}
    </article>
  );
}
