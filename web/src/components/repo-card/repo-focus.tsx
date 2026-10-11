import Link from "next/link";
import { compact } from "@/lib/discover";
import { humanHours } from "@/lib/format";
import { langColor, type CardRepo, type CardStats, type RepoCounts } from "@/lib/repo-card";
import { TONE } from "../report/tone";
import { FocusIssues } from "./focus-issues";
import { OddsMeter } from "./odds-bar";
import { LangDot, RepoAvatar } from "./repo-avatar";

// GitHub-style outline icons, 16px, for the repository's own counts.
const ICON = {
  issues: "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13ZM8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z",
  pulls: "M4.5 3.5a1.5 1.5 0 1 0 0 .01M4.5 5v6M4.5 11a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3ZM11.5 11a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3ZM11.5 11V6.5a2 2 0 0 0-2-2H7m1.5-2L7 4.5l1.5 1.5",
  people: "M6 7.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5ZM1.5 14c0-2.5 2-4.5 4.5-4.5s4.5 2 4.5 4.5M10.5 2.7a2.5 2.5 0 0 1 0 4.6M12 9.8c1.5.6 2.5 2.2 2.5 4.2",
};

function Count({ icon, n, label, extra }: { icon: keyof typeof ICON; n: number; label: string; extra?: string }) {
  return (
    <li className="flex items-center gap-1.5">
      <svg viewBox="0 0 16 16" className="size-3.5 shrink-0 text-faint" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={ICON[icon]} />
      </svg>
      <span>
        <span className="font-semibold tabular-nums text-ink">{compact(n)}</span> {label}
        {extra && <span className="text-faint"> · {extra}</span>}
      </span>
    </li>
  );
}

/** The repository's own size, from GitHub: open issues, pull requests, contributors. Nothing when none are known. */
function Counts({ c }: { c: RepoCounts }) {
  if (c.openIssues == null && c.pullRequests == null && c.contributors == null) return null;
  const one = (n: number, word: string) => (n === 1 ? word : `${word}s`);
  return (
    <ul aria-label="On GitHub" className="mt-3 flex flex-wrap gap-x-5 gap-y-1 border-y border-line py-2 font-sans text-[0.82rem] text-muted">
      {c.openIssues != null && <Count icon="issues" n={c.openIssues} label={`open ${one(c.openIssues, "issue")}`} />}
      {c.pullRequests != null && (
        <Count icon="pulls" n={c.pullRequests} label={one(c.pullRequests, "pull request")} extra={c.openPullRequests != null ? `${compact(c.openPullRequests)} open` : undefined} />
      )}
      {c.contributors != null && <Count icon="people" n={c.contributors} label={one(c.contributors, "contributor")} />}
    </ul>
  );
}

/** What happens to outside pull requests: the marked bar on the left, three small numbers beside it. */
function Numbers({ stats }: { stats: CardStats }) {
  if (!stats.attempts || stats.merged == null) {
    return <p className="mt-3 font-sans text-[0.85rem] text-muted">No outside pull requests to count yet.</p>;
  }
  const facts: { n: string; of?: string; label: string; tone: string }[] = [
    { n: String(stats.merged), of: `/${stats.attempts}`, label: "PRs merged", tone: "text-green" },
    stats.replyHours != null ? { n: humanHours(stats.replyHours), label: "to first reply", tone: "text-blue" } : { n: "None", label: "replied to", tone: "text-faint" },
    ...(stats.firstTimers ? [{ n: String(stats.firstTimers), label: "first-timers in", tone: "text-ink" }] : []),
  ];
  return (
    <div className="mt-3 flex items-end gap-x-6 gap-y-2 flex-wrap">
      <div className="w-[13rem] max-w-full shrink-0 max-sm:w-full">
        <OddsMeter stats={stats} />
      </div>
      <dl className="flex min-w-0 flex-1 flex-wrap justify-end gap-x-5 gap-y-1 pb-px font-sans max-sm:justify-start">
        {facts.map((f) => (
          <div key={f.label} className="whitespace-nowrap">
            <dd className={`text-[1rem] font-semibold leading-none tabular-nums ${f.tone}`}>
              {f.n}
              {f.of && <span className="text-[0.8rem] font-medium text-faint">{f.of}</span>}
            </dd>
            <dt className="mt-0.5 text-[0.72rem] text-muted">{f.label}</dt>
          </div>
        ))}
      </dl>
    </div>
  );
}

/**
 * What a list knows about one repo, sized to fit without scrolling: who it is,
 * the repo's own numbers, what happens to outside pull requests, and three good
 * first issues. The report has the rest.
 */
export function RepoFocus({ r, report, actions, topicBase }: { r: CardRepo; report: string; actions?: React.ReactNode; topicBase?: string }) {
  const [owner, name] = r.repo.split("/");
  return (
    <div className="min-w-0 [overflow-wrap:anywhere]">
      <div className="flex min-w-0 items-start gap-3">
        <RepoAvatar repo={r.repo} size={40} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <h2 id="focus-title" className="min-w-0 text-[1.15rem] font-semibold leading-tight tracking-tight [overflow-wrap:anywhere] sm:text-[1.3rem]">
              <Link href={report} className="hover:text-blue">
                <span className="text-muted">{owner}/</span>
                {name}
              </Link>
            </h2>
            {actions && <div className="-my-2 -mr-2 ml-auto shrink-0">{actions}</div>}
          </div>
          {r.description && <p className="mt-1 line-clamp-2 font-sans text-[0.88rem] leading-snug text-muted" title={r.description}>{r.description}</p>}
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 font-sans text-[0.82rem] text-faint">
            {r.stars != null && (
              <span className="tabular-nums text-ink">
                <span aria-hidden="true" className="text-[#e0a526]">★</span> {compact(r.stars)}<span className="sr-only"> stars</span>
              </span>
            )}
            {r.language && r.languageLabel && (
              <span className="flex items-center gap-1.5">
                <LangDot color={langColor(r.language)} />
                {r.languageLabel}
              </span>
            )}
            {r.topics.slice(0, 3).map((t) =>
              topicBase ? (
                <Link key={t} rel="nofollow" href={`${topicBase}${topicBase.includes("?") ? "&" : "?"}topic=${encodeURIComponent(t)}`} className="border border-line px-1.5 py-px hover:border-blue hover:text-ink">
                  {t}
                </Link>
              ) : (
                <span key={t} className="border border-line px-1.5 py-px">{t}</span>
              ),
            )}
            {r.checkedThisWeek != null && <span className="text-blue">{r.checkedThisWeek} checked it this week</span>}
            <Link href={report} className="btn-primary ml-auto min-h-8 px-3.5 font-sans text-[0.82rem]">
              Report <span aria-hidden="true">→</span>
            </Link>
          </div>
        </div>
      </div>

      <Counts c={r.counts} />
      <Numbers stats={r.stats} />

      {/* Only for what the numbers can't say: no count yet, or picked for this person. */}
      {!r.stats.attempts && (r.reason || r.numbersLine) && <p className="mt-2 line-clamp-2 font-sans text-[0.85rem] leading-snug text-muted">{r.reason} {r.numbersLine}</p>}
      {r.odds && (
        <p className="mt-2 font-sans text-[0.85rem] text-muted">
          Your odds: <span className={`font-semibold ${TONE[r.odds.tone].text}`}>{r.odds.level}</span>, {r.odds.text}.
        </p>
      )}
      {r.why.length > 0 && (
        <ul className="mt-2 space-y-0.5 font-sans text-[0.82rem] text-muted">
          {r.why.slice(0, 2).map((w) => (
            <li key={w} className="flex gap-2">
              <span aria-hidden="true" className="text-blue">✓</span>
              <span className="line-clamp-1">{w}</span>
            </li>
          ))}
        </ul>
      )}

      <FocusIssues repo={r.repo} initial={r.issues} />
    </div>
  );
}
