import Link from "next/link";

/** The two ways to get AI reports, side by side. No prices here: they live on /pricing. */
export function KeyOrPlan({ wide = false }: { wide?: boolean }) {
  return (
    <div className={`grid gap-px border border-line-strong bg-line ${wide ? "sm:grid-cols-2" : ""}`}>
      <Link href="/settings#byok" className="group bg-panel p-4 transition-colors hover:bg-panel-2">
        <p className="text-[0.72rem] uppercase tracking-[0.08em] text-green">Your own API key</p>
        <p className="mt-1 font-semibold">Free, unlimited</p>
        <p className="mt-1 font-sans text-[0.82rem] text-muted">Paste a key from OpenRouter, Anthropic, OpenAI or Gemini. You pay them a few cents a report.</p>
        <p className="mt-2 text-[0.78rem] text-green group-hover:underline">add a key →</p>
      </Link>
      <Link href="/pricing#compare" className="group bg-panel p-4 transition-colors hover:bg-panel-2">
        <p className="text-[0.72rem] uppercase tracking-[0.08em] text-blue">A plan</p>
        <p className="mt-1 font-semibold">No key needed</p>
        <p className="mt-1 font-sans text-[0.82rem] text-muted">A monthly allowance of AI reports and the priority queue. Cancel anytime.</p>
        <p className="mt-2 text-[0.78rem] text-blue group-hover:underline">compare plans →</p>
      </Link>
    </div>
  );
}
