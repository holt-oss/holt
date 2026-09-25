import Link from "next/link";
import { CatFace } from "@/components/cat-face";
import { CopyButton } from "@/components/copy-button";
import { HacktoberfestBanner } from "@/components/hacktoberfest-banner";
import { CatCompanion } from "@/components/motion/cat-companion";
import { PasteBox } from "@/components/paste-box";
import { UrlTrick } from "@/components/url-trick";
import { VerdictPill } from "@/components/report/verdict-pill";
import { GITHUB_REPO_URL } from "@/lib/site";

function Rail({ n, label, className = "" }: { n: string; label: string; className?: string }) {
  return (
    <aside className={`rail ${className}`} data-reveal>
      <strong>{n}</strong>
      <span>{label}</span>
    </aside>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="wrap grid gap-6 md:grid-cols-[148px_minmax(0,1fr)] md:gap-10">{children}</div>;
}

// A static sample, so the landing page stays fast and never waits on the API.
const SAMPLE = {
  repo: "pallets/flask",
  stats: [
    ["17 of 64", "outside pull requests merged"],
    ["3 hours", "typical wait for a first reply"],
    ["12", "people's first PR merged here"],
  ],
  lands: [
    ["docs/", 8, 14],
    ["src/flask/", 6, 31],
    ["tests/", 3, 9],
  ] as const,
  issue: { n: 5642, title: "Document how to test streaming responses", step: "Comment on the issue to ask if you can take it." },
};

export default function Home() {
  return (
    <>
      <HacktoberfestBanner />

      {/* 01 — start here */}
      <section data-hero data-cat-section="ready" className="relative border-b border-line pb-14 pt-8 md:pb-20 md:pt-10">
        <CatCompanion />
        <Grid>
          <Rail n="01" label="start here" className="hidden pt-1 md:block" />
          <div className="relative z-10 max-w-[880px]">
            <p className="fade-up mb-6 text-[0.78rem] text-muted" style={{ ["--d" as string]: ".1s" }}>
              holt / free / for first-time contributors
            </p>
            <h1 className="display mb-7 text-[clamp(2.05rem,8.6vw,4.25rem)]">
              <span className="headline-line"><span>Find an open-source</span></span>
              <span className="headline-line"><span>project that will</span></span>
              <span className="headline-line"><span className="text-orange">actually merge your first PR.</span></span>
            </h1>
            <p className="prose-sans fade-up mb-8 max-w-[700px] text-[clamp(1.02rem,1.7vw,1.2rem)]" style={{ ["--d" as string]: ".3s" }}>
              Paste any GitHub repo. Holt reads its recent pull requests and tells you, in plain English, whether
              newcomers get replies, get merged, and where your work has a real chance of landing.
            </p>
            <div className="fade-up max-w-[760px]" style={{ ["--d" as string]: ".38s" }}>
              <PasteBox />
            </div>
            <div className="fade-up mt-8 flex flex-wrap items-center gap-x-5 gap-y-3" style={{ ["--d" as string]: ".45s" }}>
              <span className="font-sans text-[0.95rem] text-muted">No repo in mind yet?</span>
              <Link href="/find" className="bracket-link min-h-12 border-orange px-5 text-[0.9rem] text-orange hover:bg-orange">
                [ find my first contribution → ]
              </Link>
            </div>
            <div className="fade-up mt-10 flex flex-wrap items-center gap-x-3 gap-y-2" style={{ ["--d" as string]: ".5s" }}>
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
      <section data-cat-section="startled" className="py-20 md:py-28">
        <Grid>
          <Rail n="02" label="see the answer" />
          <div>
            <h2 className="h2 mb-6 max-w-[770px]" data-reveal>See the answer before you spend the week.</h2>
            <p className="prose-sans mb-12 max-w-[740px] text-[1.05rem]" data-reveal>
              Holt returns a clear verdict, the numbers behind it, the folders where outside work actually gets merged,
              and open issues you could pick up today. Every claim links to the exact GitHub conversation it came from.
            </p>

            <figure className="relative m-0 border border-line-strong bg-panel shadow-card" data-reveal>
              <div className="flex min-h-10 items-center justify-between border-b border-line px-4 text-[0.7rem] text-faint">
                <span>{SAMPLE.repo} / report</span>
                <span className="text-green">● read-only</span>
              </div>
              <div className="grid gap-8 p-5 sm:p-8 lg:grid-cols-[1.1fr_1fr]">
                <div>
                  <div className="flex items-center justify-between">
                    <VerdictPill verdict="viable" />
                    <CatFace mood="celebrating" className="text-[1.3rem]" />
                  </div>
                  <p className="display mt-4 text-[clamp(2rem,5vw,3.2rem)] text-green">
                    Worth your time<span className="text-ink">.</span>
                  </p>
                  <ul className="mt-6 grid gap-px border border-line bg-line sm:grid-cols-3">
                    {SAMPLE.stats.map(([big, label]) => (
                      <li key={label} className="bg-panel p-3">
                        <p className="text-[1.15rem] font-semibold tracking-tight">{big}</p>
                        <p className="font-sans text-[0.78rem] leading-snug text-muted">{label}</p>
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="space-y-6">
                  <div>
                    <p className="mb-3 text-[0.7rem] uppercase tracking-[0.08em] text-faint">where newcomer work lands</p>
                    <ul className="space-y-3">
                      {SAMPLE.lands.map(([path, m, a]) => (
                        <li key={path}>
                          <div className="flex justify-between text-[0.78rem]">
                            <code>{path}</code>
                            <span className="text-muted"><span className="text-green">{m}</span> of {a} merged</span>
                          </div>
                          <div className="relative mt-1.5 h-2 bg-panel-2">
                            <span className="absolute inset-y-0 left-0 bg-line-strong" style={{ width: `${(a / 31) * 100}%` }} />
                            <span className="absolute inset-y-0 left-0 bg-green" style={{ width: `${(m / 31) * 100}%` }} />
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="border border-line p-4">
                    <p className="text-[0.7rem] text-blue">#{SAMPLE.issue.n} · good first issue</p>
                    <p className="mt-1 font-sans text-[0.92rem] font-semibold">{SAMPLE.issue.title}</p>
                    <p className="mt-2 text-[0.75rem] text-green">→ {SAMPLE.issue.step}</p>
                  </div>
                </div>
              </div>
              <figcaption className="flex flex-col justify-between gap-1 border-t border-line px-4 py-3 text-[0.72rem] text-faint sm:flex-row">
                <span><em className="not-italic text-muted">Fig. 01</em> — a real report, trimmed</span>
                <Link href={`/${SAMPLE.repo}`} className="text-green hover:underline">open the full report →</Link>
              </figcaption>
            </figure>
          </div>
        </Grid>
      </section>

      {/* 03 — the URL trick */}
      <section data-cat-section="determined" className="border-t border-line py-20 md:py-28">
        <Grid>
          <Rail n="03" label="the url trick" />
          <div>
            <h2 className="h2 mb-6 max-w-[770px]" data-reveal>Already on GitHub? Change one word.</h2>
            <p className="prose-sans mb-10 max-w-[740px] text-[1.05rem]" data-reveal>
              In any repository URL, replace <code className="font-mono text-ink">github.com</code> with our address and
              press enter. You&apos;ll land on that repo&apos;s Holt report. Works on phones too.
            </p>
            <UrlTrick />
          </div>
        </Grid>
      </section>

      {/* 04 — what it checks */}
      <section data-cat-section="heartbroken" className="border-t border-line py-20 md:py-28">
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
                <article key={t.id} className="relative grid gap-2 border-b border-line py-7 md:grid-cols-[110px_minmax(0,1fr)_200px] md:gap-6" data-reveal>
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
      <section data-cat-section="celebrating" className="border-t border-line py-20 md:py-28">
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
      <section data-cat-section="adoring" className="relative overflow-hidden border-t border-line bg-panel py-20 md:py-28">
        {/* Decorative marquee as generated content, so it isn't read or contrast-checked as text. */}
        <div
          aria-hidden="true"
          data-text="OPEN / SOURCE / OPEN / SOURCE / OPEN / SOURCE / OPEN / SOURCE /"
          className="pointer-events-none absolute left-0 top-5 whitespace-nowrap text-[clamp(2.6rem,7vw,7rem)] font-bold leading-none tracking-[-0.06em] text-blue opacity-[0.09] before:content-[attr(data-text)]"
        />
        <div className="relative">
          <Grid>
            <Rail n="06" label="open source" />
            <div>
              <h2 className="h2 mb-6 max-w-[770px]" data-reveal>Use it, inspect it, improve it.</h2>
              <p className="prose-sans mb-8 max-w-[740px] text-[1.05rem]" data-reveal>
                Holt is an Apache-2.0 project maintained by the holt-oss community. It&apos;s also a great first
                contribution: help with the web app, the rules behind the verdicts, docs, or the terminal app.
              </p>
              <div className="grid max-w-[760px] grid-cols-[auto_1fr_auto] items-center border border-line-strong bg-bg" data-reveal>
                <span aria-hidden="true" className="pl-4 text-amber">$</span>
                <code className="overflow-x-auto whitespace-nowrap px-3 py-4 text-[0.9rem]">uv tool install holt-cli</code>
                <CopyButton text="uv tool install holt-cli" className="self-stretch border-l border-line-strong px-4 text-[0.85rem] text-muted transition-colors hover:bg-green hover:text-on-accent" />
              </div>
              <div className="mt-8 flex flex-wrap items-center gap-x-7 gap-y-4" data-reveal>
                <a className="bracket-link" href={`${GITHUB_REPO_URL}/blob/main/CONTRIBUTING.md`}>[ start contributing → ]</a>
                <a className="text-link text-[0.85rem]" href={GITHUB_REPO_URL}>[ view source ]</a>
                <span className="text-[0.75rem] text-faint">Apache-2.0</span>
              </div>
            </div>
          </Grid>
        </div>
      </section>
    </>
  );
}
