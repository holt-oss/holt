import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { CopyButton } from "@/components/copy-button";
import { GITHUB_REPO_URL } from "@/lib/site";
import tui from "../../../public/holt-tui.png";
import { PageHead } from "@/components/page-head";

export const metadata: Metadata = {
  title: "How Holt decides",
  description: "Holt gathers pull request history, turns it into cited findings, checks every source, and applies one fixed set of rules.",
};

const TRACE = [
  { i: "A", name: "classify", copy: "What kind of repository is this?", owner: "model" },
  { i: "B", name: "opportunity", copy: "Is there a real route in for outside work?", owner: "model" },
  { i: "C", name: "outcomes", copy: "What happened to people who tried?", owner: "model" },
  { i: "D", name: "verify", copy: "Open every citation; drop anything that doesn't check out", owner: "no model" },
  { i: "→", name: "verdict.py", copy: "One written rule over the verified evidence", owner: "no model", decision: true },
  { i: "E", name: "narrate", copy: "Explain an answer it cannot change", owner: "model" },
];

const SCORES = [
  { label: "README + metadata prompt", v: 0.21 },
  { label: "Same evidence, one prompt", v: 0.32 },
  { label: "Holt", v: 0.63, holt: true },
];

function Block({ n, label, title, children, alt = false }: { n: string; label: string; title: string; children: React.ReactNode; alt?: boolean }) {
  return (
    <section className={`border-t border-line py-16 md:py-20 ${alt ? "bg-section-alt" : ""}`}>
      <div className="wrap grid gap-6 md:grid-cols-[148px_minmax(0,1fr)] md:gap-10">
        <aside className="rail"><strong>{n}</strong><span>{label}</span></aside>
        <div>
          <h2 className="h2 mb-6 max-w-[770px]">{title}</h2>
          {children}
        </div>
      </div>
    </section>
  );
}

export default function HowItWorks() {
  return (
    <>
      <PageHead>
        <p className="rail mb-4 flex gap-2"><strong className="m-0">how it works</strong><span>for the curious</span></p>
        <h1 className="display max-w-4xl text-[clamp(2.1rem,6vw,3.8rem)]">
          One procedure. <span className="text-orange">A verdict you can check.</span>
        </h1>
        <p className="prose-sans mt-6 max-w-2xl text-[1.08rem]">
          Holt gathers contribution history, turns it into cited findings, checks every source, and applies a fixed set
          of rules. A model can explain the evidence, but it can&apos;t override the final decision.
        </p>
      </PageHead>

      <Block n="01" label="the pipeline" title="Models read. Rules decide.">
        <div className="relative border-t border-line-strong">
          {TRACE.map((t) => (
            <div
              key={t.name}
              className={`relative grid grid-cols-[40px_1fr_auto] items-baseline gap-x-4 gap-y-1 border-b border-line py-4 md:grid-cols-[62px_170px_1fr_96px] ${t.decision ? "bg-green/[0.06]" : ""}`}
            >
              <span className="text-[0.75rem] text-blue">{t.i}</span>
              <span className="text-ink">{t.name}</span>
              <span className="col-span-2 col-start-2 row-start-2 font-sans text-[0.9rem] text-muted md:col-span-1 md:col-start-3 md:row-start-1">{t.copy}</span>
              <span className={`text-right text-[0.72rem] uppercase ${t.owner === "no model" ? "text-green" : "text-faint"}`}>{t.owner}</span>
            </div>
          ))}
        </div>
        <p className="mt-6 text-[0.82rem] text-muted">
          <strong className="font-medium text-ink">Typical input:</strong> 642 evidence records across 200 pull-request conversations.
        </p>
      </Block>

      <Block alt n="02" label="confidence" title="Useful enough to guide you. Open enough to question.">
        <p className="prose-sans mb-10 max-w-[740px] text-[1.05rem]">
          We tested Holt against what later happened to real contributors, using outcomes it couldn&apos;t see while
          analysing. The bars show how well each approach agreed with those outcomes, where 0 is a coin flip and 1 is
          perfect. Holt did far better than asking a model to judge from the README, but no score makes every call
          right, so the evidence stays visible.
        </p>
        <div className="border-t border-line-strong">
          {SCORES.map((s) => (
            <div key={s.label} className="grid grid-cols-[1fr_54px] items-center gap-3 border-b border-line py-5 md:grid-cols-[230px_1fr_64px] md:gap-6">
              <span className={`text-[0.8rem] ${s.holt ? "text-green" : "text-muted"}`}>{s.label}</span>
              <div className="meter col-span-2 row-start-2 md:col-span-1 md:row-start-auto" aria-hidden="true">
                <span className={s.holt ? "bg-green" : "bg-faint"} style={{ width: `${s.v * 100}%` }} />
              </div>
              <span className={`text-right ${s.holt ? "text-green" : "text-muted"}`}>{s.v.toFixed(2)}</span>
            </div>
          ))}
        </div>
        <ul className="mt-10 grid border-y border-line md:grid-cols-3">
          {[
            ["55 / 55", "verdicts identical across three runs"],
            ["read-only", "never writes to GitHub"],
            ["every claim", "links to a real GitHub page"],
          ].map(([a, b], i) => (
            <li key={a} className={`py-5 md:px-6 ${i ? "border-t border-line md:border-l md:border-t-0" : "md:pl-0"}`}>
              <strong className="block text-[1.25rem] font-medium">{a}</strong>
              <span className="text-[0.75rem] text-faint">{b}</span>
            </li>
          ))}
        </ul>
        <p className="mt-6 text-[0.82rem] text-faint">
          Score: Matthews correlation, out of sample.{" "}
          <a className="text-link" href={`${GITHUB_REPO_URL}/blob/main/REPRODUCTION.md`}>[ reproduce the result → ]</a>{" "}
          <a className="text-link" href={`${GITHUB_REPO_URL}/blob/main/docs/EVALUATION.md`}>[ full evaluation ]</a>
        </p>
      </Block>

      <Block n="03" label="terminal" title="Prefer the terminal? Same engine.">
        <p className="prose-sans mb-8 max-w-[740px] text-[1.05rem]">
          The Holt CLI and terminal app run the same rules on your machine with your own GitHub token.
        </p>
        <div className="mb-10 grid max-w-[760px] grid-cols-[auto_1fr_auto] items-center border border-line-strong bg-panel">
          <span aria-hidden="true" className="pl-4 text-amber">$</span>
          <code className="overflow-x-auto whitespace-nowrap px-3 py-4 text-[0.9rem]">uv tool install holt-cli</code>
          <CopyButton text="uv tool install holt-cli" className="self-stretch border-l border-line-strong px-4 text-[0.85rem] text-muted transition-colors hover:bg-green hover:text-on-accent" />
        </div>
        <figure className="m-0 border border-line-strong bg-[#101010]">
          <div className="flex min-h-10 items-center justify-between border-b border-[#292b29] px-4 text-[0.7rem] text-[#8a8a83]">
            <span>repository assessment / terminal interface</span>
            <span className="text-[#69c7a6]">● read-only</span>
          </div>
          <Image src={tui} alt="Holt terminal interface listing assessed repositories and their verdicts" sizes="(min-width: 1120px) 900px, 100vw" className="h-auto w-full" placeholder="blur" />
        </figure>
        <p className="mt-8">
          <Link href="/" className="bracket-link">[ or just paste a repo → ]</Link>
        </p>
      </Block>
    </>
  );
}
