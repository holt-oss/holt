import Link from "next/link";
import { humanHours, pct, VERDICT_TONE } from "@/lib/format";
import type { Report } from "@/lib/types";
import { CatFace } from "../cat-face";
import { TONE, VERDICT_MOOD } from "../report/tone";

export function CompareShell({ repo, removeHref, children }: { repo: string; removeHref: string; children: React.ReactNode }) {
  return (
    <li className="flex min-w-0 flex-col border border-line-strong bg-panel shadow-soft">
      <div className="flex items-center gap-3 border-b border-line p-4">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`https://github.com/${repo.split("/")[0]}.png?size=64`} alt="" width={28} height={28} className="size-7 rounded border border-line-strong bg-panel-2" />
        <Link href={`/${repo}`} className="flex min-h-11 min-w-0 flex-1 items-center truncate text-[0.92rem] font-semibold hover:text-blue">{repo}</Link>
        <Link href={removeHref} className="grid size-11 place-items-center text-faint hover:text-orange" aria-label={`Remove ${repo} from comparison`}>✕</Link>
      </div>
      <div className="flex-1">{children}</div>
    </li>
  );
}

export function CompareBody({ report }: { report: Report }) {
  const s = report.stats;
  const t = TONE[VERDICT_TONE[report.verdict]];
  const top = report.landing[0];
  const rows: [string, React.ReactNode][] = [
    ["Outside PRs merged", <><strong className="text-ink">{s.outsider_merged}</strong> of {s.outsider_attempts} ({pct(s.outsider_merged, s.outsider_attempts)}%)</>],
    ["Typical first reply", s.median_first_response_hours == null ? <span className="text-orange">no replies</span> : humanHours(s.median_first_response_hours)],
    ["First-timers merged", <strong key="f" className={s.first_time_merged_authors ? "text-green" : "text-orange"}>{s.first_time_merged_authors}</strong>],
    ["Never got a reply", `${pct(s.no_reply, s.outsider_attempts)}%`],
    ["Best way in", top ? <code key="c" className="text-ink">{top.path}/</code> : <span className="text-faint">none yet</span>],
  ];
  return (
    <>
      <div className={`p-4 ${t.soft}`}>
        <CatFace mood={VERDICT_MOOD[report.verdict]} className="text-[1.1rem]" />
        <p className={`mt-2 text-[1.35rem] font-semibold leading-tight tracking-tight ${t.text}`}>{report.headline}</p>
      </div>
      <dl className="divide-y divide-line">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[1fr_auto] gap-3 px-4 py-3 text-[0.82rem]">
            <dt className="font-sans text-muted">{k}</dt>
            <dd className="text-right text-muted">{v}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}
