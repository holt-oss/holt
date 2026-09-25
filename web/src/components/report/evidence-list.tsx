import { evidenceLabel, evidenceRef } from "@/lib/format";
import type { EvidenceItem } from "@/lib/types";

function Item({ e }: { e: EvidenceItem }) {
  const { label, bad } = evidenceLabel(e);
  return (
    <li className="grid gap-1 border-b border-line py-4 sm:grid-cols-[150px_1fr_auto] sm:gap-5">
      <span className={`text-[0.72rem] uppercase tracking-[0.06em] ${bad ? "text-orange" : "text-green"}`}>{label}</span>
      <div className="min-w-0">
        <p className="font-sans text-[0.93rem] text-ink">{e.text}</p>
        {e.quote && <blockquote className="mt-1.5 border-l-2 border-line-strong pl-3 font-sans text-[0.88rem] italic text-muted">“{e.quote}”</blockquote>}
      </div>
      <a
        href={e.url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex min-h-11 items-center self-start text-[0.8rem] text-blue hover:underline"
      >
        {evidenceRef(e.url)} <span aria-hidden="true">&nbsp;↗</span>
        <span className="sr-only"> on GitHub</span>
      </a>
    </li>
  );
}

export function EvidenceList({ evidence }: { evidence: EvidenceItem[] }) {
  if (!evidence.length) return <p className="font-sans text-muted">No evidence items.</p>;
  const first = evidence.slice(0, 5);
  const rest = evidence.slice(5);
  return (
    <div className="border-t border-line-strong">
      <ul>{first.map((e) => <Item key={e.id} e={e} />)}</ul>
      {rest.length > 0 && (
        <details className="group">
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 py-3 text-[0.82rem] text-green [&::-webkit-details-marker]:hidden">
            <span className="group-open:hidden">[ show {rest.length} more ]</span>
            <span className="hidden group-open:inline">[ show fewer ]</span>
          </summary>
          <ul>{rest.map((e) => <Item key={e.id} e={e} />)}</ul>
        </details>
      )}
    </div>
  );
}
