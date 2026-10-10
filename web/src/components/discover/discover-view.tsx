import Link from "next/link";
import { discover, savedNames } from "@/lib/api";
import { boardHref, boardTitle, emptyText, SORTS, widenBoard } from "@/lib/discover";
import { langColor } from "@/lib/repo-card";
import { currentUser } from "@/lib/session";
import type { DiscoverSort } from "@/lib/types";
import { ErrorPanel } from "../error-panel";
import { EmptyState } from "../shell/app-page";
import { PageTransition } from "../motion/page-transition";
import { FindFrame } from "../find/find-frame";
import { LangDot } from "../repo-card/repo-avatar";
import { BoardList } from "./board-list";

/** /discover and /discover/<language>: Find a project's browse tab, one board as a grid of cards with its order and language chips on top. */
export async function DiscoverView({ sort, language, topic }: { sort: DiscoverSort; language: string | null; topic: string | null }) {
  const user = await currentUser();
  const [result, saved] = await Promise.all([discover(sort, language, topic), savedNames(user?.id)]);
  const here = boardHref({ sort, language, topic });
  const data = result.ok ? result.data : null;
  // The order and language chips: one row in the bar once it's wide enough, two before that.
  const chip = "inline-flex h-10 items-center whitespace-nowrap border px-3 text-[0.8rem] transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue sm:h-8";
  const chipOn = "picked";
  const chipOff = "border-line-strong text-muted hover:border-blue hover:text-ink";
  const filters = (
    <div className="find-bar flex flex-wrap items-center gap-x-4 gap-y-1.5 py-1.5 @3xl:flex-nowrap">
      <nav aria-label="Order" className="w-full @3xl:w-auto @3xl:shrink-0">
        <ul className="grid grid-cols-3 @3xl:flex">
          {SORTS.map((s, i) => (
            <li key={s.id} className={i ? "-ml-px" : ""}>
              <Link
                rel="nofollow"
                href={boardHref({ sort: s.id, language, topic })}
                scroll={false}
                aria-current={s.id === sort ? "page" : undefined}
                className={`relative flex h-10 items-center justify-center border px-2 text-center text-[0.78rem] leading-tight sm:whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue sm:h-8 sm:px-3.5 sm:text-[0.8rem] ${s.id === sort ? "picked z-10" : "border-line-strong text-muted hover:border-blue hover:text-ink"}`}
              >
                {s.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {data && data.languages.length > 0 && (
        <nav aria-label="Language" className="w-full min-w-0 @3xl:w-auto @3xl:flex-1">
          <ul className="flex gap-1.5 overflow-x-auto pr-6 [mask-image:linear-gradient(to_right,#000_calc(100%-1.5rem),transparent)] [scrollbar-width:none]">
            <li className="shrink-0">
              <Link rel="nofollow" href={boardHref({ sort, topic })} scroll={false} aria-current={!language ? "page" : undefined} className={`${chip} ${!language ? chipOn : chipOff}`}>
                Any language
              </Link>
            </li>
            {data.languages.map((l) => {
              const on = l.name.toLowerCase() === language?.toLowerCase();
              return (
                <li key={l.name} className="shrink-0">
                  <Link rel="nofollow" href={boardHref({ sort, language: l.name, topic })} scroll={false} aria-current={on ? "page" : undefined} className={`${chip} gap-2 ${on ? chipOn : chipOff}`}>
                    <LangDot color={langColor(l.name)} />
                    {l.name}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      )}
    </div>
  );

  return (
    <PageTransition>
      <FindFrame tab="browse" title={boardTitle(sort, language)} signedIn={Boolean(user)}>
        <div className="find-tray">{filters}</div>
        {topic && (
          <p className="mt-4 text-[0.8rem] text-faint">
            Only repos tagged <strong className="font-semibold text-ink">{topic}</strong>.{" "}
            <Link rel="nofollow" href={boardHref({ sort, language })} className="text-link">Show all topics</Link>
          </p>
        )}
        <section aria-label={boardTitle(sort, language)} className="mt-5">
          {!result.ok ? (
            <ErrorPanel error={result.error} retryHref={here} />
          ) : data!.repos.length ? (
            // The first part is rendered here; the list loads the rest as it is scrolled. A new board is a new list.
            <BoardList key={here} sort={sort} language={language} topic={topic} saved={saved} first={{ items: data!.repos, next: data!.next ?? null, total: data!.total ?? data!.repos.length }} />
          ) : (
            <EmptyState title={emptyText(sort, language, topic, data!.trending_min)}>
              {widenBoard({ sort, language, topic }).map((w, i) => (
                <Link key={w.href} href={w.href} className={i ? "text-link text-[0.9rem]" : "btn-primary"}>{i ? w.label : `${w.label} →`}</Link>
              ))}
            </EmptyState>
          )}
        </section>
      </FindFrame>
    </PageTransition>
  );
}
