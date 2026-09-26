import { statLines } from "@/lib/format";
import type { Stats } from "@/lib/types";
import { TONE } from "./tone";

/** `reveal`: the tiles step in (60ms, then 50ms apart), for a report that just arrived. */
export function StatsGrid({ stats, limit, reveal }: { stats: Partial<Stats>; limit?: number; reveal?: boolean }) {
  const lines = statLines(stats).slice(0, limit);
  return (
    <ul className="grid gap-px overflow-hidden border border-line bg-line shadow-soft sm:grid-cols-2 lg:grid-cols-3">
      {lines.map((s, i) => {
        const t = TONE[s.tone];
        return (
          <li key={s.key} className={`bg-panel p-5 ${reveal ? "reveal" : ""}`} style={reveal ? { ["--d0" as string]: "60ms", ["--i" as string]: i } : undefined}>
            <p className={`text-[1.6rem] font-semibold leading-tight tracking-tight ${s.tone === "neutral" ? "text-ink" : t.text}`}>{s.big}</p>
            <p className="mt-1 font-sans text-[0.9rem] leading-snug text-muted">{s.label}</p>
            {s.meter != null && (
              <div className="meter mt-3" aria-hidden="true">
                <span className={t.bg} style={{ width: `${Math.max(2, Math.round(s.meter * 100))}%` }} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
