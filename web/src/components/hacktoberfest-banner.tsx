import Link from "next/link";
import { hacktoberfest } from "@/lib/site";

export function HacktoberfestBanner() {
  const hf = hacktoberfest();
  if (!hf) return null;
  return (
    <div className="relative overflow-hidden border-b border-line bg-panel">
      <div
        aria-hidden="true"
        className="absolute inset-0 opacity-[0.07]"
        style={{ backgroundImage: "repeating-linear-gradient(135deg, var(--orange) 0 10px, transparent 10px 22px)" }}
      />
      <Link
        href="/find?go=1&hacktoberfest=1"
        className="wrap relative flex min-h-11 flex-wrap items-center justify-center gap-x-3 gap-y-1 py-2 text-center text-[0.78rem]"
      >
        <span className="inline-flex items-center gap-2 font-semibold text-orange">
          <span aria-hidden="true" className="inline-block size-1.5 rounded-full bg-orange motion-safe:animate-pulse" />
          {hf.text}
        </span>
        <span className="text-muted">
          <span className="hidden sm:inline">Find a repo that will actually review your pull requests</span>
          <span className="sm:hidden">Find a repo that reviews PRs</span> <span aria-hidden="true">→</span>
        </span>
      </Link>
    </div>
  );
}
