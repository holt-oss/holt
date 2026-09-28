// Landing page "Fig. 01". Shows a real cached report when the API has one;
// otherwise a static figure that is labelled as an example, never as real.
import Link from "next/link";
import { getReport, MOCK, starterIssues } from "@/lib/api";
import { humanHours, nextStep } from "@/lib/format";
import { areaLabel } from "@/lib/landing";
import { caller } from "@/lib/session";
import type { Tone } from "@/lib/types";
import { CatFace } from "./cat-face";
import { TONE, TONE_MOOD } from "./report/tone";
import { VerdictPill } from "./report/verdict-pill";

// A repo the current engine rates Worth your time. The example below is its
// real report from githolt.com on 28 Sep 2026, trimmed; Holt listed no
// starter issues for it that day, so the example shows none either.
const REPO = "home-assistant/core";

interface Sample {
  repo: string;
  headline: string;
  tone: Tone;
  stats: [string, string][];
  lands: [path: string, merged: number, attempted: number][];
  issue: { n: number; title: string; label: string; step: string } | null;
  caption: string;
}

const EXAMPLE: Sample = {
  repo: REPO,
  headline: "Worth your time",
  tone: "good",
  stats: [
    ["43 of 58", "outside pull requests merged"],
    ["15 hours", "typical wait for a first reply"],
    ["30", "people's first PR merged here"],
  ],
  lands: [
    ["homeassistant/components/", 41, 55],
    ["tests/components/", 27, 38],
    ["(root)", 14, 18],
  ],
  issue: null,
  caption: "an example report",
};

async function load(): Promise<Sample> {
  if (MOCK) return EXAMPLE; // mock data is not a real run
  const [r, i] = await Promise.all([getReport(REPO), caller().then((c) => starterIssues(REPO, 1, c))]);
  if (!r.ok) return EXAMPLE;
  const s = r.data.stats;
  const issue = i.ok ? i.data.issues[0] : undefined;
  return {
    repo: r.data.repo,
    headline: r.data.headline,
    tone: r.data.tone,
    stats: [
      [`${s.outsider_merged} of ${s.outsider_attempts}`, "outside pull requests merged"],
      [s.median_first_response_hours == null ? "none" : humanHours(s.median_first_response_hours), "typical wait for a first reply"],
      [String(s.first_time_merged_authors), "people's first PR merged here"],
    ],
    lands: r.data.landing.slice(0, 3).map((l) => [areaLabel(l), l.merged, l.attempted]),
    issue: issue ? { n: issue.number, title: issue.title, label: issue.labels[0] ?? "starter issue", step: nextStep(issue) } : null,
    caption: "a real report, trimmed",
  };
}

export async function LiveSample() {
  return <SampleFigure sample={await load()} />;
}

function SampleFigure({ sample }: { sample: Sample }) {
  const t = TONE[sample.tone];
  const max = Math.max(1, ...sample.lands.map(([, , a]) => a));
  return (
    <figure className="relative m-0 border border-line-strong bg-panel shadow-card">
      <div className="flex min-h-10 items-center justify-between border-b border-line px-4 text-[0.7rem] text-faint">
        <span>{sample.repo} / report</span>
        <span className="text-green">● read-only</span>
      </div>
      <div className="grid gap-8 p-5 sm:p-8 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <div className="flex items-center justify-between">
            <VerdictPill headline={sample.headline} tone={sample.tone} />
            <CatFace mood={TONE_MOOD[sample.tone]} className="text-[1.3rem]" />
          </div>
          <p className={`display mt-4 text-[clamp(2rem,5vw,3.2rem)] ${t.text}`}>
            {sample.headline}
            <span className="text-ink">.</span>
          </p>
          <ul className="mt-6 grid gap-px border border-line bg-line sm:grid-cols-3">
            {sample.stats.map(([big, label]) => (
              <li key={label} className="bg-panel p-3">
                <p className="text-[1.15rem] font-semibold tracking-tight">{big}</p>
                <p className="font-sans text-[0.78rem] leading-snug text-muted">{label}</p>
              </li>
            ))}
          </ul>
        </div>
        <div className="space-y-6">
          {sample.lands.length > 0 && (
            <div>
              <p className="mb-3 text-[0.7rem] uppercase tracking-[0.08em] text-faint">where newcomer work lands</p>
              <ul className="space-y-3">
                {sample.lands.map(([path, m, a]) => (
                  <li key={path}>
                    <div className="flex justify-between gap-3 text-[0.78rem]">
                      <code className="truncate">{path}</code>
                      <span className="shrink-0 text-muted">
                        <span className="text-green">{m}</span> of {a} merged
                      </span>
                    </div>
                    <div className="relative mt-1.5 h-2 bg-panel-2">
                      <span className="absolute inset-y-0 left-0 bg-line-strong" style={{ width: `${(a / max) * 100}%` }} />
                      <span className="absolute inset-y-0 left-0 bg-green" style={{ width: `${(m / max) * 100}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {sample.issue && (
            <div className="border border-line p-4">
              <p className="text-[0.7rem] text-blue">
                #{sample.issue.n} · {sample.issue.label}
              </p>
              <p className="mt-1 font-sans text-[0.92rem] font-semibold">{sample.issue.title}</p>
              <p className="mt-2 text-[0.75rem] text-green">→ {sample.issue.step}</p>
            </div>
          )}
        </div>
      </div>
      <figcaption className="flex flex-col justify-between gap-1 border-t border-line px-4 py-3 text-[0.72rem] text-faint sm:flex-row">
        <span>
          <em className="not-italic text-muted">Fig. 01</em> — {sample.caption}
        </span>
        <Link href={`/${sample.repo}`} className="inline-flex min-h-11 items-center text-green hover:underline sm:min-h-0">
          {sample.caption === "an example report" ? "see the live report →" : "open the full report →"}
        </Link>
      </figcaption>
    </figure>
  );
}
