import { VERDICT_HEADLINE, VERDICT_TONE } from "@/lib/format";
import type { Verdict } from "@/lib/types";
import { TONE } from "./tone";

export function VerdictPill({ verdict, className = "" }: { verdict: Verdict; className?: string }) {
  const t = TONE[VERDICT_TONE[verdict]];
  return (
    <span className={`inline-flex items-center gap-2 border px-2 py-1 text-[0.72rem] font-semibold ${t.text} ${t.border} ${t.soft} ${className}`}>
      <span aria-hidden="true" className={`size-1.5 rounded-full ${t.bg}`} />
      {VERDICT_HEADLINE[verdict]}
    </span>
  );
}
