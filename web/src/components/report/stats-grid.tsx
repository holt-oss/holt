import { statLines } from "@/lib/format";
import type { Stats } from "@/lib/types";
import { TONE } from "./tone";

export function StatsGrid({ stats, limit }: { stats: Partial<Stats>; limit?: number }) {
  const lines = statLines(stats).slice(0, limit);
  return (
    <ul className="grid gap-px overflow-hidden border border-line bg-line shadow-soft sm:grid-cols-2 lg:grid-cols-3">
      {lines.map((s, i) => {
        const t = TONE[s.tone];
        return (
          <li key={s.key} className="fade-up bg-panel p-5" style={{ ["--d" as string]: `${0.05 * i}s` }}>
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
