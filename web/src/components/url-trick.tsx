import Link from "next/link";
import { SITE_HOST } from "@/lib/site";

function Bar({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <div className="flex min-h-13 items-center gap-3 overflow-hidden rounded-full border border-line-strong bg-panel px-4 text-[0.82rem] sm:text-[0.95rem]" aria-label={label}>
      <svg className="size-3.5 shrink-0 text-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <rect x="5" y="11" width="14" height="10" rx="2" />
        <path d="M8 11V7a4 4 0 0 1 8 0v4" />
      </svg>
      <span className="min-w-0 truncate">{children}</span>
    </div>
  );
}

export function UrlTrick() {
  return (
    <div className="max-w-[760px] space-y-3" data-reveal>
      <Bar label="Before: a GitHub URL">
        <span className="text-faint">https://</span>
        <span className="text-orange line-through decoration-2">github.com</span>
        <span className="text-muted">/pallets/flask</span>
      </Bar>
      <p aria-hidden="true" className="pl-6 text-blue">↓</p>
      <Bar label={`After: the same URL on ${SITE_HOST}`}>
        <span className="text-faint">https://</span>
        <span className="bg-green/15 px-1 font-semibold text-green">{SITE_HOST}</span>
        <span className="text-ink">/pallets/flask</span>
      </Bar>
      <p className="pt-4 font-sans text-[0.9rem] text-muted">
        Lazier still: put <code className="font-mono text-ink">{SITE_HOST}/</code> in front of the whole link.{" "}
        <Link href="/https://github.com/pallets/flask" prefetch={false} className="text-link font-mono text-[0.85rem]">
          try it
        </Link>
      </p>
    </div>
  );
}
