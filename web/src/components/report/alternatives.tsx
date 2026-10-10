// Under a Long shot or Not worth your time: a few repos that do merge
// outsiders, from the "most welcoming" board (API.md, GET /v1/discover) for
// this repo's language. Server only (it reads the board); where a report is
// drawn in the browser, ReportView shows FindLine instead.
import Link from "next/link";
import { discover } from "@/lib/api";
import type { Verdict } from "@/lib/types";
import { Skeleton, SkeletonRegion } from "../skeleton";
import { FindLine } from "./find-line";
import { findHref, pickAlternatives } from "./next-action";

// A few more than shown: the board may hold the repo being read.
const ASKED = 6;

export async function Alternatives({ repo, language, verdict }: { repo: string; language: string | null; verdict: Verdict }) {
  let board = await discover("welcoming", language, null, ASKED);
  let picks = board.ok ? pickAlternatives(board.data.repos, repo) : [];
  // Nothing in this language yet: the most welcoming repos in any.
  if (!picks.length && language) {
    board = await discover("welcoming", null, null, ASKED);
    picks = board.ok ? pickAlternatives(board.data.repos, repo) : [];
    language = null;
  }
  if (!picks.length) return <FindLine verdict={verdict} language={language} />;

  return (
    <section aria-labelledby="alternatives" data-alternatives>
      <h2 id="alternatives" className="mb-3 text-[1.05rem] font-semibold tracking-tight sm:text-[1.15rem]">Try these instead</h2>
      <ul className="divide-y divide-line border-y border-line">
        {picks.map((r) => (
          <li key={r.repo} className="group relative py-2.5 hover:bg-panel-2/50">
            <Link href={`/${r.repo}`} data-umami-event="alternative-click" className="block truncate font-sans text-[0.95rem] font-medium leading-[1.4] text-ink after:absolute after:inset-0 group-hover:text-blue">
              {r.repo}
            </Link>
            <p className="mt-0.5 font-sans text-[0.82rem] leading-snug text-muted">{r.reason}</p>
          </li>
        ))}
      </ul>
      <p className="mt-3">
        <Link href={findHref(language)} className="text-link tap">
          {language ? `more ${language} projects` : "more projects"} <span aria-hidden="true">→</span>
        </Link>
      </p>
    </section>
  );
}

/** Three rows, where the alternatives stream in. */
export function AlternativesSkeleton() {
  return (
    <SkeletonRegion as="ul" label="Loading other projects…" className="divide-y divide-line border-y border-line">
      {[0, 1, 2].map((i) => (
        <li key={i} className="space-y-1.5 py-2.5">
          <Skeleton className="h-4 w-2/5" />
          <Skeleton className="h-3 w-4/5" />
        </li>
      ))}
    </SkeletonRegion>
  );
}
