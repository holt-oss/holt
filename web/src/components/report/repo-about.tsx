// In a report's header, under the repo name: what the project is (as many lines as it needs; two on a phone),
// how big and alive it is (one row, stars first) and, on a line of its own, the
// website and GitHub link. The licence, start year, branch and topics are in the
// sidebar (project-sidebar.tsx).
// Public data from GitHub (the server's `about`): every visitor sees it.
import { CircleDot, Clock, GitFork, Star } from "lucide-react";
import { timeAgo } from "@/lib/format";
import { aboutNumbers, flags, readmeShown, siteLabel, type RepoAbout as About } from "@/lib/repo-about";


/** The name column of the report header: name, the description under it
 * (wrapping, never cut off), then the numbers. */
export function RepoAbout({ about, repo, verdict }: { about: About; repo: string; /** The verdict tag: last in the row of numbers. */ verdict?: React.ReactNode }) {
  const readme = readmeShown(about);
  const [stars, ...counts] = aboutNumbers(about);
  const marks = flags(about);
  const line = about.description ?? readme;
  const [owner, name] = repo.split("/");
  return (
    <div className="relative min-w-0" data-repo-about>
      <p className="text-[1.05rem] font-semibold tracking-tight [overflow-wrap:anywhere] sm:text-[1.25rem]">
        <span className="text-muted">{owner}/</span>
        {name}
      </p>
      {/* Two lines at most on a phone, so the verdict isn't pushed down; in full from `sm` up. */}
      {line && <p className="mt-1 line-clamp-2 max-w-3xl font-sans text-[0.9rem] leading-snug text-muted [overflow-wrap:anywhere] sm:line-clamp-none">{line}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.82rem] text-muted sm:gap-x-4">
        {marks.map((f) =>
          f.repo ? (
            <a key={f.kind} href={`/${f.repo}`} className="shrink-0 whitespace-nowrap border border-line-strong px-1.5 text-[0.76rem] text-ink hover:text-blue">
              {f.text}
            </a>
          ) : (
            <span key={f.kind} className="shrink-0 border border-amber/60 px-1.5 text-[0.76rem] text-amber">
              {f.text}
            </span>
          ),
        )}
        {stars && (
          <span className="inline-flex shrink-0 items-center gap-1 text-[1rem] font-semibold text-ink" title={`${about.stars} ${stars.label} on GitHub`}>
            <Star aria-hidden="true" strokeWidth={1.75} className="size-4 text-amber" />
            {stars.value}
            <span className="sr-only"> {stars.label}</span>
          </span>
        )}
        {counts.map((n) => (
          <span key={n.label} className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap">
            {n.label.startsWith("fork") ? <GitFork aria-hidden="true" strokeWidth={1.75} className="size-3.5 text-faint" /> : <CircleDot aria-hidden="true" strokeWidth={1.75} className="size-3.5 text-faint" />}
            <span className="font-semibold text-ink">{n.value}</span>
            <span className="sr-only sm:not-sr-only">{n.label.replace("open ", "")}</span>
          </span>
        ))}
        {about.pushed_at && (
          <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap">
            <Clock aria-hidden="true" strokeWidth={1.75} className="size-3.5 text-faint" />
            <span className="sr-only sm:not-sr-only">pushed</span> <time dateTime={about.pushed_at} suppressHydrationWarning>{timeAgo(about.pushed_at)}</time>
          </span>
        )}
        {verdict}
      </div>
      <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-0.5 font-mono text-[0.8rem]" data-repo-details>
        {about.homepage && (
          <a href={about.homepage} target="_blank" rel="noopener noreferrer nofollow" className="max-w-full truncate text-blue/80 hover:text-blue">
            {siteLabel(about.homepage)} ↗
          </a>
        )}
        <a href={`https://github.com/${repo}`} target="_blank" rel="noopener noreferrer" className="text-blue/80 hover:text-blue">
          github.com/{repo} ↗
        </a>
      </p>
    </div>
  );
}
