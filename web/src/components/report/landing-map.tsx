import type { Report } from "@/lib/types";

export function LandingMap({ landing, neverLanded }: { landing: Report["landing"]; neverLanded: Report["never_landed"] }) {
  if (!landing.length && !neverLanded.length) {
    return <p className="font-sans text-muted">Holt didn&apos;t see enough outside work to map where it lands.</p>;
  }
  const max = Math.max(1, ...landing.map((l) => l.attempted), ...neverLanded.map((l) => l.attempted));
  return (
    <div className="space-y-6">
      {landing.length > 0 && (
        <ul className="space-y-4" aria-label="Folders where outside pull requests were merged">
          {landing.map((l) => (
            <li key={l.path}>
              <div className="flex items-baseline justify-between gap-4 text-[0.85rem]">
                <code className="truncate text-ink">{l.path}/</code>
                <span className="shrink-0 font-sans text-muted">
                  <strong className="font-semibold text-green">{l.merged}</strong> of {l.attempted} merged
                </span>
              </div>
              <div className="relative mt-2 h-2.5 bg-panel-2" aria-hidden="true">
                <span className="meter absolute inset-y-0 left-0 bg-line-strong" style={{ width: `${(l.attempted / max) * 100}%`, height: "100%" }} />
                <span className="absolute inset-y-0 left-0 bg-green" style={{ width: `${(l.merged / max) * 100}%`, animation: "grow .9s cubic-bezier(.16,1,.3,1) both", transformOrigin: "left" }} />
              </div>
            </li>
          ))}
        </ul>
      )}
      {neverLanded.length > 0 && (
        <div>
          <p className="mb-2 text-[0.72rem] uppercase tracking-[0.08em] text-faint">Nothing from outsiders merged yet in</p>
          <ul className="flex flex-wrap gap-2">
            {neverLanded.map((l) => (
              <li key={l.path} className="chip border-orange/40">
                <code className="text-ink">{l.path}/</code>
                <span className="text-muted">{l.attempted} tried</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
