import { SITE_URL } from "@/lib/site";
import { CopyButton } from "../copy-button";

export function BadgeSnippet({ repo }: { repo: string }) {
  const md = `[![Holt](${SITE_URL}/badge/${repo}.svg)](${SITE_URL}/${repo})`;
  return (
    <div className="panel p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[0.85rem] text-ink">Maintainer? Show newcomers they&apos;re welcome.</p>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`/badge/${repo}.svg`} alt="Holt badge preview" height={20} className="h-5 w-auto" loading="lazy" />
      </div>
      <div className="mt-3 grid grid-cols-[1fr_auto] border border-line-strong bg-bg">
        <code className="min-w-0 overflow-x-auto whitespace-nowrap px-3 py-3 text-[0.75rem] text-muted">{md}</code>
        <CopyButton text={md} label="copy" className="border-l border-line-strong px-4 text-[0.78rem] text-muted transition-colors hover:bg-green hover:text-on-accent" />
      </div>
      <p className="mt-2 font-sans text-[0.8rem] text-faint">Paste it into your README. The badge updates when the report does.</p>
    </div>
  );
}
