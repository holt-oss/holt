import Link from "next/link";
import { badgeSnippets } from "@/lib/badge";
import { SITE_URL } from "@/lib/site";
import { CopyButton } from "../copy-button";

/** On a report: the README badge for a passing repo, or where to see what would earn one. */
export function BadgeSnippet({ repo, offered }: { repo: string; offered: boolean }) {
  const more = `/badge?repo=${repo}`;
  if (!offered) {
    return (
      <div className="border-t border-line pt-5">
        <p className="text-[0.89rem] text-ink">Maintainer of this repo?</p>
        <p className="mt-1 font-sans text-[0.88rem] text-muted">
          See what would earn it a Holt badge. <Link href={more} className="text-link">Get a badge →</Link>
        </p>
      </div>
    );
  }
  const { markdown } = badgeSnippets(SITE_URL, repo);
  return (
    <div className="border-t border-line pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[0.89rem] text-ink">Maintainer? Show newcomers they&apos;re welcome.</p>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`/badge/${repo}.svg`} alt="Holt badge preview" height={20} className="h-5 w-auto" loading="lazy" />
      </div>
      <div className="mt-3 grid grid-cols-[1fr_auto] border border-line-strong bg-bg">
        <code className="min-w-0 overflow-x-auto whitespace-nowrap px-3 py-3 text-[0.82rem] text-muted">{markdown}</code>
        <CopyButton text={markdown} label="copy" className="border-l border-line-strong px-4 text-[0.85rem] text-muted transition-colors hover:bg-ink hover:text-on-accent" />
      </div>
      <p className="mt-2 font-sans text-[0.87rem] text-faint">
        Paste it into your README. The badge updates when the report does. <Link href={more} className="text-link">HTML and more →</Link>
      </p>
    </div>
  );
}
