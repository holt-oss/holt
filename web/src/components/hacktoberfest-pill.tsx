"use client";

// A small, dismissible, clearly seasonal link to /hacktoberfest. Shown only
// in the weeks around October (the server decides) and hidden before paint
// once dismissed (the head script sets data-hf-dismissed).
import Link from "next/link";
import { HF_KEY } from "./theme-toggle";

export function HacktoberfestPill({ year, short }: { year: number; short: string }) {
  function dismiss() {
    try {
      localStorage.setItem(HF_KEY, "1");
    } catch {}
    document.documentElement.dataset.hfDismissed = "1";
  }
  return (
    <div className="hf-pill inline-flex max-w-full items-stretch overflow-hidden rounded-full border border-hf-line bg-hf-bg text-[0.74rem] leading-none">
      <Link href="/hacktoberfest" className="flex min-h-11 min-w-0 items-center gap-2 py-1.5 pl-3 pr-2 text-hf hover:underline sm:min-h-9">
        <span aria-hidden="true" className="relative flex size-2 shrink-0">
          <span className="absolute inset-0 rounded-full bg-orange motion-safe:animate-ping" />
          <span className="relative size-2 rounded-full bg-orange" />
        </span>
        <strong className="shrink-0 font-semibold">Hacktoberfest {year}</strong>
        <span className="hidden text-muted sm:inline">· Oct 1–31 ·</span>
        <span className="truncate text-muted">
          {short} <span className="hidden sm:inline">· limited time</span>
        </span>
        <span aria-hidden="true">→</span>
      </Link>
      <button
        type="button"
        onClick={dismiss}
        className="grid min-h-11 w-11 shrink-0 place-items-center border-l border-hf-line text-[1rem] text-muted hover:text-ink sm:min-h-9 sm:w-9"
        aria-label="Hide the Hacktoberfest notice"
      >
        <span aria-hidden="true">×</span>
      </button>
    </div>
  );
}
