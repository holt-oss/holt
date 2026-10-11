import type { Metadata } from "next";
import Link from "next/link";
import { CopyButton } from "@/components/copy-button";
import { HacktoberfestPill } from "@/components/hacktoberfest-pill";
import { CatCompanion } from "@/components/motion/cat-companion";
import { SwapHost } from "@/components/motion/swap-host";
import { ScrollMarquee } from "@/components/motion/scroll-marquee";
import { FocusOnHash } from "@/components/shell/check-focus";
import { PasteBox } from "@/components/paste-box";
import { EXAMPLES_PATH } from "@/lib/examples";
import { humanHours } from "@/lib/format";
import { buildReplay } from "@/lib/landing-replay";
import { landingReport } from "@/lib/landing-report";
import { Answers } from "@/components/landing/answers";
import { CheckReplay } from "@/components/landing/check-replay";
import { People, type Person } from "@/components/landing/people";
import { Receipts } from "@/components/landing/receipts";
import { Words } from "@/components/landing/words";
import { currentUser } from "@/lib/session";
import type { Report } from "@/lib/types";
import { GITHUB_REPO_URL, hacktoberfest } from "@/lib/site";
import { PageTransition } from "@/components/motion/page-transition";
import { ProfileOnboarding } from "@/components/profile-onboarding";
import { Suspense } from "react";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

// "02 see the answer": the section's number and name, above its headline (the
// side rail it replaces left the left third of every pane empty).
function Kicker({ n, label, className = "" }: { n: string; label: string; className?: string }) {
  return (
    <p className={`ls-kicker ${className}`} data-reveal>
      <span className="text-blue">{n}</span> {label}
    </p>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  // landing-wide: the measure and type grow with the screen (globals.css).
  return <div className="wrap landing-wide">{children}</div>;
}

// Section 03's people. Their examples are the same report's real numbers.
function people(r: Report): Person[] {
  const s = r.stats;
  const top = r.landing[0];
  return [
    {
      key: "first",
      who: "a student with a free weekend",
      title: "Your first PR",
      body: "Skip the repos where outside PRs sit in silence. Start where someone answers.",
      mood: "startled",
      example: { repo: r.repo, fact: `${s.first_time_merged_authors} people got their first PR merged` },
    },
    {
      key: "next",
      who: "a regular, looking for a new home",
      title: "Your next project",
      body: "Spend your evenings where outside work gets merged, and see which folders it lands in.",
      mood: "determined",
      example: { repo: r.repo, fact: top ? `${top.merged} of ${top.attempted} merged in ${top.path}` : `${s.outsider_merged} of ${s.outsider_attempts} outside PRs merged` },
    },
    {
      key: "upstream",
      who: "a developer with a bug at work",
      title: "A fix you need upstream",
      body: "Find out if they take outside patches before you tell your team it'll land by Friday.",
      mood: "thinking",
      example: { repo: r.repo, fact: `a first reply typically took ${humanHours(s.median_first_response_hours)}` },
    },
  ];
}

// Section 06's call to action. Signed-in people get their history instead of
// a sign-in button.
async function ReportsCta() {
  if (await currentUser()) {
    return (
      <Link href="/me/repos?show=checked" className="bracket-link">[ your reports → ]</Link>
    );
  }
  return (
    <>
      <Link href="/signin" className="bracket-link">[ check a repo → ]</Link>
      <Link href={EXAMPLES_PATH} className="text-link inline-flex min-h-11 items-center text-[0.89rem]">[ read an example first ]</Link>
    </>
  );
}

export default async function Home() {
  const hf = hacktoberfest();
  // Signed out, the paste boxes open the report page like signed in (pasteHref, lib/gate.ts).
  const [user, report] = await Promise.all([currentUser(), landingReport()]);
  const signedIn = Boolean(user);
  const replay = buildReplay(report);
  return (
    <PageTransition>
      <>
        <FocusOnHash />
        {/* 01 — start here */}
        <section data-hero data-cat-section="ready" className="pane relative overflow-hidden border-b border-line low:pt-5 short:pt-3">
          <div aria-hidden="true" className="hero-backdrop" />
          <CatCompanion />
          <Grid>
            <div className="relative z-10 min-w-0">
              {/* Desktop: room on the right for the companion cat, which starts there. */}
              <div className="fade-up mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 low:mb-3 short:mb-2 lg:pr-[clamp(12rem,15.5vw,17rem)]" style={{ ["--d" as string]: ".1s" }}>
                <p className="ls-kicker text-muted">
                  <span className="text-blue">01</span> start here
                </p>
                {hf && <HacktoberfestPill year={hf.year} short={hf.short} />}
              </div>
              {/* One block: from 1280px the bar and its foot line span the headline plus the sub-line. */}
              <div className="hero-stack">
                {/* Sized by the screen; the sub-line moves beside the headline where both fit. */}
                <div className="hero-lede">
                  <h1 className="display hero-h1">
                    <span className="headline-line"><span>Will this repo</span></span>
                    <span className="headline-line"><span className="text-orange"><span className="marker">actually merge</span></span></span>
                    <span className="headline-line"><span className="text-orange">your PR?</span></span>
                  </h1>
                  <p className="prose-sans fade-up hero-sub" style={{ ["--d" as string]: ".3s" }}>
                    Holt checks what happened to the outsiders who tried before you: did anyone reply, and
                    did anything get merged?
                  </p>
                </div>
                <div id="check" data-check-target="page" className="fade-up hero-act scroll-mt-24" style={{ ["--d" as string]: ".38s" }}>
                  <PasteBox signedIn={signedIn} />
                </div>
                <div className="fade-up hero-foot" style={{ ["--d" as string]: ".42s" }}>
                  <p className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <Link href="/find" className="bracket-link bracket-link--orange min-h-11 px-3 text-center sm:min-h-12 sm:px-5">
                      [ find a project&nbsp;→&nbsp;]
                    </Link>
                  </p>
                  <p className="font-sans text-faint">
                    swap <strong className="text-muted">hub</strong> for <strong className="text-muted">holt</strong>:{" "}
                    <SwapHost />
                  </p>
                </div>
              </div>
              <div className="fade-up mt-6 flex flex-wrap items-center gap-x-3 gap-y-2 low:mt-4" style={{ ["--d" as string]: ".5s" }}>
                <span className="award-badge">
                  <span>micro1 winner</span>
                  <span>Most useful real-world workflow</span>
                </span>
                <span className="text-[0.75rem] text-faint">Frontier Engineering Challenge</span>
              </div>
            </div>
          </Grid>
        </section>

        {/* After sign-in: the profile card, for people who haven't saved or skipped it. */}
        <Suspense fallback={null}>
          <ProfileOnboarding back="/" className="wrap py-8" />
        </Suspense>

        {/* 02 — see the answer: a check replayed, then the real thing */}
        <section id="answer" data-cat-section="startled" className="pane scroll-mt-[61px]">
          <Grid>
            <Kicker n="02" label="see the answer" />
            <div className="ls-split">
              <h2 className="h2">
                <Words text="Watch Holt check a repo." />
              </h2>
              <div className="min-w-0" data-reveal>
                <CheckReplay replay={replay} />
                {/* An example report: open to everyone, signed in or not. */}
                <Link href={`/${replay.repo}`} className="bracket-link mt-5">
                  [ read the full report → ]
                </Link>
              </div>
            </div>
          </Grid>
        </section>

        {/* 03 — who it's for */}
        <section data-cat-section="thinking" className="pane border-t border-line bg-section-alt">
          <Grid>
            <Kicker n="03" label="who it's for" />
            <h2 className="h2 ls-h2-wide ls-h2-sm mb-[clamp(2.5rem,8svh,5.5rem)]">
              <Words text="Don't write your PR into the void." quiet={["void"]} />
            </h2>
            <People people={people(report)} />
          </Grid>
        </section>

        {/* 04 — the URL trick */}
        <section data-cat-section="determined" className="pane pane--compact border-t border-line">
          <Grid>
            <Kicker n="04" label="the url trick" />
            <h2 className="h2 ls-h2-sm mb-[clamp(2.5rem,8svh,5.5rem)]">
              <Words text="Already on GitHub? Swap hub for holt." />
            </h2>
            <div className="min-w-0" data-reveal>
              <SwapHost path="/pallets/flask" big />
            </div>
          </Grid>
        </section>

        {/* 05 — what it checks */}
        <section id="what-it-checks" data-cat-section="heartbroken" className="pane scroll-mt-[61px] border-t border-line bg-section-alt">
          <Grid>
            <Kicker n="05" label="what it checks" />
            <h2 className="h2 ls-h2-sm mb-12">
              <Words text="Stars won't tell you who gets merged." />
            </h2>
            <Receipts />
            <div className="mt-10 flex flex-wrap items-center gap-x-4 gap-y-2" data-reveal>
              <Link href="/discover" className="bracket-link">[ discover repos → ]</Link>
            </div>
          </Grid>
        </section>

        {/* 06 — four answers */}
        <section id="verdicts" data-cat-section="celebrating" className="pane scroll-mt-[61px] border-t border-line">
          <Grid>
            <Kicker n="06" label="four answers" />
            <h2 className="h2 ls-h2-sm mb-4">
              <Words text="Four possible answers. No hedging." />
            </h2>
            <Answers />
            <div className="mt-10 flex flex-wrap items-center gap-x-6 gap-y-3" data-reveal>
              <Link href="/how-it-works" className="text-link inline-flex min-h-11 items-center font-mono text-[0.89rem]">[ how it decides ]</Link>
              <Suspense fallback={null}>
                <ReportsCta />
              </Suspense>
            </div>
          </Grid>
        </section>

        {/* 07 — open source */}
        <section id="open-source" data-cat-section="adoring" className="pane scroll-mt-[61px] relative overflow-clip border-t border-line bg-panel">
          <ScrollMarquee text="OPEN / SOURCE / OPEN / SOURCE / OPEN / SOURCE / OPEN / SOURCE / OPEN / SOURCE /" />
          <div className="relative">
            <Grid>
              <Kicker n="07" label="open source" />
              <h2 className="h2 ls-h2-sm mb-8">
                <Words text="Open source. We merge outsiders too." />
              </h2>
              <div className="ls-install grid max-w-[760px] grid-cols-[auto_1fr_auto] items-center border border-line-strong bg-bg" data-reveal>
                <span aria-hidden="true" className="pl-4 text-amber">$</span>
                <code className="min-w-0 overflow-x-auto whitespace-nowrap px-2 py-4 text-[0.8rem] sm:px-3 sm:text-[0.95rem]">
                  uv tool install holt-cli<span aria-hidden="true" className="ls-caret" />
                </code>
                <CopyButton text="uv tool install holt-cli" className="self-stretch border-l border-line-strong px-3 text-[0.89rem] text-muted sm:px-4 transition-colors hover:bg-ink hover:text-on-accent" />
              </div>
              <div className="mt-8 flex flex-wrap items-center gap-x-7 gap-y-4" data-reveal>
                <a className="bracket-link" href={`${GITHUB_REPO_URL}/blob/main/CONTRIBUTING.md`}>[ start contributing → ]</a>
                <a className="text-link inline-flex min-h-11 items-center text-[0.89rem]" href={GITHUB_REPO_URL}>[ star it on GitHub ]</a>
                <span className="text-[0.82rem] text-faint">Apache-2.0</span>
              </div>
            </Grid>
          </div>
        </section>
      </>
    </PageTransition>
  );
}
