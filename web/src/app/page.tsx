import Link from "next/link";
import { CatFace } from "@/components/cat-face";
import { CopyButton } from "@/components/copy-button";
import { HacktoberfestPill } from "@/components/hacktoberfest-pill";
import { CatCompanion } from "@/components/motion/cat-companion";
import { ScrollMarquee } from "@/components/motion/scroll-marquee";
import { PasteBox } from "@/components/paste-box";
import { UrlTrick } from "@/components/url-trick";
import { LiveSample } from "@/components/sample-report";
import { SampleReportSkeleton } from "@/components/sample-report-skeleton";
import { SkeletonReveal } from "@/components/motion/reveal";
import { GITHUB_REPO_URL, SITE_HOST, hacktoberfest } from "@/lib/site";
import { PageTransition } from "@/components/motion/page-transition";

function Rail({ n, label, className = "" }: { n: string; label: string; className?: string }) {
  return (
    <aside className={`rail ${className}`} data-reveal>
      <strong>{n}</strong>
      <span>{label}</span>
    </aside>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="wrap grid grid-cols-1 gap-6 md:grid-cols-[148px_minmax(0,1fr)] md:gap-10">{children}</div>;
}

export default function Home() {
  const hf = hacktoberfest();
  return (
    <PageTransition>
      <>
        {/* 01 — start here */}
        <section data-hero data-cat-section="ready" className="relative overflow-hidden border-b border-line pb-12 pt-5 md:pb-16 md:pt-7">
          <div aria-hidden="true" className="hero-backdrop" />
          <CatCompanion />
          <Grid>
            <Rail n="01" label="start here" className="relative hidden pt-2 md:block" />
            <div className="relative z-10 max-w-[860px]">
              <div className="fade-up mb-4 flex flex-wrap items-center gap-x-4 gap-y-2" style={{ ["--d" as string]: ".1s" }}>
                {hf && <HacktoberfestPill year={hf.year} short={hf.short} />}
                <p className="text-[0.78rem] text-muted">holt / free / for first-time contributors</p>
              </div>
              <h1 className="display mb-5 text-[clamp(2rem,8.9vw,3.15rem)]">
                <span className="headline-line"><span>Find an open-source</span></span>
                <span className="headline-line"><span>project that will</span></span>
                <span className="headline-line"><span className="text-orange"><span className="marker">actually merge</span> your first PR.</span></span>
              </h1>
              <p className="prose-sans fade-up mb-6 max-w-[680px] text-[clamp(1rem,1.45vw,1.12rem)]" style={{ ["--d" as string]: ".3s" }}>
                Paste any GitHub repo. Holt reads its recent pull requests and tells you, in plain English, whether
                newcomers get replies, get merged, and where your work has a real chance of landing.
              </p>
              <div className="fade-up max-w-[760px]" style={{ ["--d" as string]: ".38s" }}>
                <PasteBox />
              </div>
              <p className="fade-up mt-3 font-sans text-[0.85rem] text-faint" style={{ ["--d" as string]: ".42s" }}>
                Already on GitHub? Swap <strong className="text-muted">hub</strong> for <strong className="text-muted">holt</strong>:{" "}
                <code className="font-mono">github.com</code> → <code className="font-mono text-muted">{SITE_HOST}</code>
              </p>
              <div className="fade-up mt-5 flex flex-wrap items-center gap-x-5 gap-y-3" style={{ ["--d" as string]: ".45s" }}>
                <span className="font-sans text-[0.95rem] text-muted">No repo in mind yet?</span>
                <Link href="/find" className="bracket-link bracket-link--orange min-h-12 px-5 text-[0.9rem]">
                  [ find my first contribution → ]
                </Link>
              </div>
              <div className="fade-up mt-8 flex flex-wrap items-center gap-x-3 gap-y-2" style={{ ["--d" as string]: ".5s" }}>
                <span className="award-badge">
                  <span>micro1 winner</span>
                  <span>Most useful real-world workflow</span>
                </span>
                <span className="text-[0.66rem] text-faint">Frontier Engineering Challenge</span>
              </div>
            </div>
          </Grid>
        </section>

        {/* 02 — see the answer */}
        <section data-cat-section="startled" className="py-14 md:py-28">
          <Grid>
            <Rail n="02" label="see the answer" />
            <div>
              <h2 className="h2 mb-6 max-w-[770px]" data-reveal>See the answer before you spend the week.</h2>
              <p className="prose-sans mb-12 max-w-[740px] text-[1.05rem]" data-reveal>
                Holt returns a clear verdict, the numbers behind it, the folders where outside work actually gets merged,
                and open issues you could pick up today. Every claim links to the exact GitHub conversation it came from.
              </p>

              <SkeletonReveal fallback={<SampleReportSkeleton />}>
                <LiveSample />
              </SkeletonReveal>
            </div>
          </Grid>
        </section>

        {/* 03 — the URL trick */}
        <section data-cat-section="determined" className="border-t border-line bg-section-alt py-14 md:py-28">
          <Grid>
            <Rail n="03" label="the url trick" />
            <div>
              <h2 className="h2 mb-6 max-w-[770px]" data-reveal>Already on GitHub? Swap hub for holt.</h2>
              <p className="prose-sans mb-10 max-w-[740px] text-[1.05rem]" data-reveal>
                In any repository URL, change <code className="font-mono text-ink">github.com</code> to{" "}
                <code className="font-mono text-ink">{SITE_HOST}</code> and press enter. You&apos;ll land on that
                repo&apos;s Holt report. Works on phones too.
              </p>
              <UrlTrick />
            </div>
          </Grid>
        </section>

        {/* 04 — what it checks */}
        <section data-cat-section="heartbroken" className="border-t border-line py-14 md:py-28">
          <Grid>
            <Rail n="04" label="what it checks" />
            <div>
              <h2 className="h2 mb-6 max-w-[770px]" data-reveal>Stars don&apos;t tell you what happens to newcomers.</h2>
              <p className="prose-sans mb-12 max-w-[740px] text-[1.05rem]" data-reveal>
                Stars and issue counts describe how popular a project is. Holt looks at the path you will actually take:
                first-time pull requests, how fast someone replies, what gets merged, and which parts of the code outside
                work lands in.
              </p>
              <div className="border-t border-line-strong">
                {[
                  { id: "PR / 4821", quote: "Thanks for this! Merged. Could you also look at the sibling case?", verdict: "→ there's a way in", tone: "text-green", bar: "bg-green" },
                  { id: "PR / 917", quote: "We're rewriting this module internally, closing.", verdict: "→ don't spend the week", tone: "text-orange", bar: "bg-orange" },
                ].map((t) => (
                  <article key={t.id} className="relative grid grid-cols-1 gap-2 border-b border-line py-7 md:grid-cols-[110px_minmax(0,1fr)_200px] md:gap-6" data-reveal>
                    <span aria-hidden="true" className={`absolute -left-3 inset-y-0 w-0.5 md:-left-5 ${t.bar}`} />
                    <div className="text-[0.74rem] text-faint">{t.id}</div>
                    <blockquote className="m-0 font-sans text-[1.06rem] text-ink">“{t.quote}”</blockquote>
                    <div className={`text-[0.8rem] md:text-right ${t.tone}`}>{t.verdict}</div>
                  </article>
                ))}
              </div>
              <p className="mt-6 text-[0.75rem] text-faint" data-reveal>
                <span className="text-blue">evidence:</span> same status, opposite outcome for the contributor.
              </p>
            </div>
          </Grid>
        </section>

        {/* 05 — three answers */}
        <section data-cat-section="celebrating" className="border-t border-line bg-section-alt py-14 md:py-28">
          <Grid>
            <Rail n="05" label="three answers" />
            <div>
              <h2 className="h2 mb-6 max-w-[770px]" data-reveal>Three possible answers. No hedging.</h2>
              <p className="prose-sans mb-12 max-w-[740px] text-[1.05rem]" data-reveal>
                The verdict comes from the same written rules for every repository. An AI can explain the evidence to you,
                but it can&apos;t change the answer.{" "}
                <Link href="/how-it-works" className="text-link font-mono text-[0.9rem]">[ how it decides ]</Link>
              </p>
              <ul className="grid gap-px border border-line bg-line md:grid-cols-3">
                {[
                  { mood: "celebrating" as const, title: "Worth your time", tone: "text-green", body: "Outsiders get replies and get merged. Holt shows you where to start." },
                  { mood: "heartbroken" as const, title: "Not worth your time", tone: "text-orange", body: "Outside pull requests mostly go unanswered or unmerged. Save your week." },
                  { mood: "thinking" as const, title: "Not enough evidence", tone: "text-amber", body: "Too few people have tried recently to say. Holt won't guess." },
                ].map((v) => (
                  <li key={v.title} className="bg-panel p-6" data-reveal>
                    <CatFace mood={v.mood} className="text-[1.4rem]" />
                    <p className={`mt-4 text-[1.2rem] font-semibold tracking-tight ${v.tone}`}>{v.title}</p>
                    <p className="mt-2 font-sans text-[0.95rem] text-muted">{v.body}</p>
                  </li>
                ))}
              </ul>
            </div>
          </Grid>
        </section>

        {/* 06 — open source */}
        <section data-cat-section="adoring" className="relative overflow-clip border-t border-line bg-panel py-14 md:py-28">
          <ScrollMarquee text="OPEN / SOURCE / OPEN / SOURCE / OPEN / SOURCE / OPEN / SOURCE / OPEN / SOURCE /" />
          <div className="relative">
            <Grid>
              <Rail n="06" label="open source" />
              <div>
                <h2 className="h2 mb-6 max-w-[770px]" data-reveal>Use it, inspect it, improve it.</h2>
                <p className="prose-sans mb-8 max-w-[740px] text-[1.05rem]" data-reveal>
                  Holt is open source (Apache-2.0) and built in the open. It&apos;s also a good place for a first
                  contribution: the web app, the rules behind the verdicts, docs, or the terminal app.
                </p>
                <div className="grid max-w-[760px] grid-cols-[auto_1fr_auto] items-center border border-line-strong bg-bg" data-reveal>
                  <span aria-hidden="true" className="pl-4 text-amber">$</span>
                  <code className="min-w-0 overflow-x-auto whitespace-nowrap px-3 py-4 text-[0.9rem]">uv tool install holt-cli</code>
                  <CopyButton text="uv tool install holt-cli" className="self-stretch border-l border-line-strong px-4 text-[0.85rem] text-muted transition-colors hover:bg-green hover:text-on-accent" />
                </div>
                <div className="mt-8 flex flex-wrap items-center gap-x-7 gap-y-4" data-reveal>
                  <a className="bracket-link" href={`${GITHUB_REPO_URL}/blob/main/CONTRIBUTING.md`}>[ start contributing → ]</a>
                  <a className="text-link inline-flex min-h-11 items-center text-[0.85rem]" href={GITHUB_REPO_URL}>[ view source ]</a>
                  <span className="text-[0.75rem] text-faint">Apache-2.0</span>
                </div>
              </div>
            </Grid>
          </div>
        </section>
      </>
    </PageTransition>
  );
}
