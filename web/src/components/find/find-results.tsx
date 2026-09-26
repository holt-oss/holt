import Link from "next/link";
import { humanHours } from "@/lib/format";
import type { FindResult } from "@/lib/types";
import { CatFace } from "../cat-face";
import { StarterIssueCard } from "../report/starter-issues";
import { VerdictPill } from "../report/verdict-pill";

function compact(n: number) {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n);
}

export function FindResults({ results, days }: { results: FindResult[]; days: number }) {
  if (!results.length) {
    return (
      <div className="border border-dashed border-line-strong p-8 text-center">
        <CatFace mood="thinking" className="text-[1.6rem]" />
        <p className="mt-4 text-[1.1rem] font-semibold">No welcoming repos matched all of that.</p>
        <p className="mt-2 font-sans text-muted">Try another language, or turn off the Hacktoberfest filter.</p>
      </div>
    );
  }
  return (
    <ol className="space-y-6">
      {results.map((r, i) => {
        const s = r.stats;
        return (
          <li key={r.repo} className="reveal border border-line-strong bg-panel shadow-soft" style={{ ["--i" as string]: i }}>
            <div className="flex flex-wrap items-start gap-4 border-b border-line p-5 sm:p-6">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`https://github.com/${r.repo.split("/")[0]}.png?size=80`} alt="" width={40} height={40} loading="lazy" className="size-10 rounded-md border border-line-strong bg-panel-2" />
              <div className="min-w-0 flex-1">
                <h2 className="text-[1.15rem] font-semibold tracking-tight [overflow-wrap:anywhere]">
                  <Link href={`/${r.repo}${days !== 7 ? `?days=${days}` : ""}`} className="hover:text-blue">
                    <span className="text-muted">{r.repo.split("/")[0]}/</span>
                    {r.repo.split("/")[1]}
                  </Link>
                </h2>
                {r.description && <p className="mt-1 font-sans text-[0.92rem] text-muted">{r.description}</p>}
                <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[0.75rem] text-faint">
                  {r.language && <span>{r.language}</span>}
                  {r.stars != null && <span>★ {compact(r.stars)}</span>}
                  {s.first_time_merged_authors != null && <span className="text-green">{s.first_time_merged_authors} first-timers merged</span>}
                  {s.median_first_response_hours != null && <span>replies in {humanHours(s.median_first_response_hours)}</span>}
                </p>
                <div className="mt-3 sm:hidden"><VerdictPill verdict={r.verdict} /></div>
              </div>
              <div className="hidden sm:block"><VerdictPill verdict={r.verdict} /></div>
            </div>
            <div className="p-5 sm:p-6">
              <p className="mb-3 text-[0.72rem] uppercase tracking-[0.08em] text-faint">Pick one of these</p>
              <ul className="grid gap-3 md:grid-cols-2">
                {r.issues.slice(0, 4).map((issue) => (
                  <StarterIssueCard key={issue.number} issue={issue} compact />
                ))}
              </ul>
              <Link href={`/${r.repo}`} className="mt-4 inline-block text-[0.8rem] text-green hover:underline">
                [ full report for {r.repo} → ]
              </Link>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
