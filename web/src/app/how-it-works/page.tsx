import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { CopyButton } from "@/components/copy-button";
import { GITHUB_REPO_URL } from "@/lib/site";
import tui from "../../../public/holt-tui.png";
import { PageHead } from "@/components/page-head";
import { PageTransition } from "@/components/motion/page-transition";

export const metadata: Metadata = {
  title: "How Holt decides",
  description: "Models read the pull request history. Written rules pick the verdict. Every claim links to the GitHub page it came from.",
  alternates: { canonical: "/how-it-works" },
};

const TRACE = [
  { i: "A", name: "classify", copy: "What kind of repo is this?", owner: "model" },
  { i: "B", name: "opportunity", copy: "Is there a way in for outside work?", owner: "model" },
  { i: "C", name: "outcomes", copy: "What happened to outsiders who tried?", owner: "model" },
  { i: "D", name: "verify", copy: "Open every citation. Drop whatever doesn't check out.", owner: "no model" },
  { i: "→", name: "verdict.py", copy: "Written rules pick the verdict from what's left", owner: "no model", decision: true },
  { i: "E", name: "narrate", copy: "Explain an answer it cannot change", owner: "model" },
];

function Block({ n, label, title, children, alt = false }: { n: string; label: string; title: string; children: React.ReactNode; alt?: boolean }) {
  return (
    <section className={`border-t border-line py-10 md:py-14 ${alt ? "bg-section-alt" : ""}`}>
      <div className="wrap grid grid-cols-1 gap-6 md:grid-cols-[148px_minmax(0,1fr)] md:gap-10">
        <aside className="rail"><strong>{n}</strong><span>{label}</span></aside>
        <div>
          <h2 className="h2 h2-sm mb-5 max-w-[770px]">{title}</h2>
          {children}
        </div>
      </div>
    </section>
  );
}

export default function HowItWorks() {
  return (
    <PageTransition>
      <>
        <PageHead>
          <p className="rail mb-4 flex gap-2"><strong className="m-0">how it works</strong><span>for the curious</span></p>
          <h1 className="display max-w-4xl text-[clamp(1.9rem,4.5vw,3rem)]">
            Models read. <span className="text-orange">Rules decide.</span>
          </h1>
          <p className="prose-sans mt-5 max-w-2xl text-[0.98rem]">
            Holt keeps only the evidence it can trace to a real GitHub page, then runs the same written rules on every
            repo.
          </p>
        </PageHead>

        <Block n="01" label="the pipeline" title="Six steps. One of them decides.">
          <div className="relative border-t border-line-strong">
            {TRACE.map((t) => (
              <div
                key={t.name}
                className={`relative grid grid-cols-[40px_1fr_auto] items-baseline gap-x-4 gap-y-1 border-b border-line py-4 md:grid-cols-[62px_170px_1fr_96px] ${t.decision ? "bg-ink/[0.04]" : ""}`}
              >
                <span className="text-[0.82rem] text-blue">{t.i}</span>
                <span className="text-ink">{t.name}</span>
                <span className="col-span-2 col-start-2 row-start-2 font-sans text-[0.9rem] text-muted md:col-span-1 md:col-start-3 md:row-start-1">{t.copy}</span>
                <span className={`text-right text-[0.8rem] uppercase ${t.owner === "no model" ? "text-ink" : "text-faint"}`}>{t.owner}</span>
              </div>
            ))}
          </div>
          <p className="mt-6 text-[0.88rem] text-muted">
            <strong className="font-medium text-ink">Typical input:</strong> 642 pieces of evidence from 200 pull request threads.
          </p>
        </Block>

        <Block alt n="02" label="confidence" title="Don't take our word for it.">
          <p className="prose-sans mb-7 max-w-[740px] text-[0.95rem]">
            No verdict is right every time, so the evidence stays on the page. Open any citation and check it against
            the GitHub thread yourself.
          </p>
          <ul className="grid border-y border-line md:grid-cols-3">
            {[
              ["55 / 55", "same verdict on all three runs"],
              ["read-only", "never writes to GitHub"],
              ["every claim", "links to a real GitHub page"],
            ].map(([a, b], i) => (
              <li key={a} className={`py-5 md:px-6 ${i ? "border-t border-line md:border-l md:border-t-0" : "md:pl-0"}`}>
                <strong className="block text-[1.05rem] font-medium">{a}</strong>
                <span className="text-[0.82rem] text-faint">{b}</span>
              </li>
            ))}
          </ul>
          <p className="mt-6 text-[0.88rem] text-faint">
            That 55/55 is from Holt&apos;s competition days. Treat it as history, not a promise.{" "}
            <a className="text-link" href={`${GITHUB_REPO_URL}/blob/main/docs/research/REPRODUCTION.md`}>[ reproduce it → ]</a>{" "}
            <a className="text-link" href={`${GITHUB_REPO_URL}/blob/main/docs/research/EVALUATION.md`}>[ full evaluation ]</a>
          </p>
        </Block>

        <Block n="03" label="terminal" title="Prefer the terminal? Same engine.">
          {/* Side by side from lg up, so the screenshot fits the same screen as the install line. */}
          <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:items-center">
            <div>
              <p className="prose-sans mb-6 max-w-[740px] text-[0.95rem]">
                Same rules, on your machine, with your own GitHub token. Good for scripts, and for people who never leave
                the terminal.
              </p>
              <div className="grid max-w-[760px] grid-cols-[auto_1fr_auto] items-center border border-line-strong bg-panel">
                <span aria-hidden="true" className="pl-4 text-amber">$</span>
                <code className="min-w-0 overflow-x-auto whitespace-nowrap px-3 py-4 text-[0.9rem]">uv tool install holt-cli</code>
                <CopyButton text="uv tool install holt-cli" className="self-stretch border-l border-line-strong px-4 text-[0.89rem] text-muted transition-colors hover:bg-ink hover:text-on-accent" />
              </div>
              <p className="mt-8">
                <Link href="/" className="bracket-link">[ or just paste a repo → ]</Link>
              </p>
            </div>
            <figure className="m-0 border border-line-strong bg-[#101010]">
              <div className="flex min-h-10 items-center justify-between border-b border-[#292b29] px-4 text-[0.78rem] text-[#8a8a83]">
                <span>holt / terminal app</span>
                <span className="text-[#e7e5dc]">● read-only</span>
              </div>
              <Image src={tui} alt="Holt terminal interface listing assessed repositories and their verdicts" sizes="(min-width: 1120px) 540px, (min-width: 1024px) 50vw, 100vw" className="h-auto w-full" placeholder="blur" />
            </figure>
          </div>
        </Block>
      </>
    </PageTransition>
  );
}
