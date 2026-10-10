// The full report. Shared by the server page (cached report) and the client
// runner (report that just finished streaming), so no server-only imports.
import { ChevronDown, Info } from "lucide-react";
import { shortDate, timeAgo } from "@/lib/format";
import { EXAMPLE_PATH } from "@/lib/example-report";
import { planCta } from "@/lib/merge-plan-offer";
import { SITE_URL } from "@/lib/site";
import type { Report } from "@/lib/types";
import { CatFace } from "../cat-face";
import { Track } from "../track";
import { badgeOffered } from "@/lib/badge";
import { BadgeSnippet } from "./badge-snippet";
import { CompareCard } from "./compare-card";
import { CollapsibleSection } from "../ui/collapsible-section";
import { EvidenceList } from "./evidence-list";
import { FindLine } from "./find-line";
import { HoltUsersLine } from "./holt-users-line";
import { PreflightLink } from "../preflight/preflight-link";
import { LandingMap } from "./landing-map";
import { issuesBehindControl, nextAction } from "./next-action";
import { PlaybookSection } from "./playbook-section";
import { ProjectSection } from "./project-section";
import { ProjectSidebar } from "./project-sidebar";
import { ReadmeSection } from "./readme-section";
import { ReportModeLink } from "./report-tabs";
import { ShareMenu } from "./share-bar";
import { StatsGrid } from "./stats-grid";
import { TONE, TONE_MOOD } from "./tone";
import { UpgradeCard } from "./upgrade-card";
import { VerdictCat } from "./verdict-cat";
import { VerdictFeedback } from "./verdict-feedback";

/** Delay for a part of the report that fades in when an analysis finishes on the page. */
const step = (reveal: boolean | undefined, ms: number) =>
  reveal ? { className: "reveal", style: { ["--d0" as string]: `${ms}ms` } } : { className: "", style: undefined };

export function Section({ n, title, id, children, note, reveal }: { n?: string; title: string; id: string; children: React.ReactNode; note?: React.ReactNode; reveal?: number }) {
  const r = step(reveal != null, reveal ?? 0);
  return (
    // No rule above a section: blocks are set apart by space and their headings,
    // so a section after a boxed block never shows the box's edge and a line.
    <section aria-labelledby={id} className={r.className} style={r.style}>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {n && <span className="text-[0.78rem] text-blue">{n}</span>}
        <h2 id={id} className="text-[1.05rem] font-semibold tracking-tight sm:text-[1.15rem]">{title}</h2>
        {note && <span className="font-sans text-[0.89rem] text-faint">{note}</span>}
      </div>
      {children}
    </section>
  );
}

/**
 * The card is headed by the verdict's name (VerdictTag), then the advice and
 * the reason. `land`: the answer just arrived on this page
 * (the expressive design plan, pattern 4): the cat reacts. A report read again
 * is still. The card is short on purpose: the reason, the numbers and what to
 * do fit in one screen, with the project and its issues starting just below.
 */
export function VerdictHero({ report, reveal, land }: { report: Report; reveal?: boolean; land?: boolean }) {
  // Every sentence here comes from the server, derived there from the verdict,
  // the counts and the rules, so the top of the page can't disagree with them
  // or with itself. The reason, the numbers, how long it takes (when known),
  // and what to do next.
  // A personal project gets no "what to do": the reason under the verdict says it all.
  const advice = report.verdict === "personal" ? [] : report.next_step.split(/(?<=[.!?])\s+/).filter(Boolean);
  return (
    <div data-verdict-hero>
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          {/* The verdict's name heads the card; the line under it says what to do. */}
          <VerdictTag report={report} />
        </div>
        <span className={reveal ? "reveal" : ""}>
          {land ? (
            <VerdictCat mood={TONE_MOOD[report.tone]} className="text-[1rem] normal-case tracking-normal sm:text-[1.2rem]" />
          ) : (
            <CatFace mood={TONE_MOOD[report.tone]} blink className="text-[1rem] normal-case tracking-normal sm:text-[1.2rem]" />
          )}
        </span>
      </div>
      {/* What to do leads: it's the thing the visitor came for. The server's sentence can hold more than one
          piece of advice; the first is the headline, the rest are listed under "Also". */}
      {advice.length > 0 && (
        <p className={`mt-3 max-w-3xl font-sans text-[1.25rem] font-semibold leading-snug tracking-tight text-ink sm:text-[1.5rem] ${reveal ? "reveal-lcp" : ""}`} data-line="next">
          {advice[0]}
        </p>
      )}
      {advice.length > 1 && (
        <ul className="mt-2 max-w-3xl list-disc space-y-0.5 pl-5 font-sans text-[0.95rem] leading-snug text-ink" aria-label="Also">
          {advice.slice(1).map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      )}
      <p className="mt-3 max-w-3xl font-sans text-[1rem] leading-snug text-muted sm:text-[1.05rem]" data-line="reason">
        {report.verdict_line}
      </p>

      {/* The wait is only here: the counts are in the stats card below, and how they were made is under "How this was counted". */}
      {report.how_long.length > 0 && (
        <div className="mt-4 border-t border-line pt-3" data-line="how-long">
          <h2 className="text-[0.85rem] text-faint">How long it usually takes</h2>
          <dl className="mt-1 grid max-w-3xl grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-sans text-[0.93rem] leading-snug text-ink">
            {report.how_long.map((l) => (
              <div key={l.topic} className="contents">
                <dt className="text-muted">{l.topic}</dt>
                <dd>{l.text}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <p className="text-[0.78rem] text-faint">
          {report.evidence_until && <>Data until {shortDate(report.evidence_until)} · </>}checked{" "}
          <time dateTime={report.generated_at} suppressHydrationWarning>{timeAgo(report.generated_at)}</time>
        </p>
        <HowCounted report={report} />
      </div>
    </div>
  );
}

/**
 * The verdict's name, set like the landing page's four answers (Answers): large, in the verdict's colour, with a
 * plain full stop. It heads the verdict card. The page's one h1.
 */
export function VerdictTag({ report }: { report: Pick<Report, "headline" | "tone"> }) {
  return (
    <h1 className={`display text-[1.6rem] leading-none sm:text-[2.25rem] ${TONE[report.tone].text}`} data-verdict-tag>
      {report.headline}
      <span className="text-ink">.</span>
    </h1>
  );
}

/** What was read, in a sentence a newcomer can follow. */
function lookedAt(r: Report): string {
  const smp = r.sample;
  const out = r.stats.outsider_attempts;
  const span = smp?.first_opened && smp.last_opened ? `, opened between ${shortDate(smp.first_opened)} and ${shortDate(smp.last_opened)}` : "";
  const read = smp ? `Holt read the ${smp.pull_requests} most recent pull requests on this repo${span}.` : "Holt read this repo's recent pull requests.";
  const outsiders = out > 0 ? ` ${out} came from people outside the team, like you, and had been open long enough to get an answer. Those are the ones that show how newcomers are treated.` : " None came from people outside the team that had been open long enough to count.";
  return read + outsiders;
}

/** One row of "How this was counted": a small label beside its text, stacked on phones. */
function CountedRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 px-4 py-3.5 sm:grid-cols-[10.5rem_minmax(0,1fr)] sm:gap-x-6 sm:px-5">
      <dt className="text-[0.74rem] uppercase leading-[1.9] tracking-[0.08em] text-faint">{label}</dt>
      <dd className="space-y-1.5 font-sans text-[0.92rem] leading-relaxed text-muted">{children}</dd>
    </div>
  );
}

/** "How this was counted": closed by default, for anyone who wants to check the working. Opens to a full-width panel. */
function HowCounted({ report }: { report: Report }) {
  return (
    <details className="group open:basis-full" data-how-counted>
      <summary className="inline-flex min-h-9 cursor-pointer list-none items-center gap-2 border border-line-strong px-3 text-[0.84rem] text-muted transition-colors hover:border-blue hover:text-ink focus-visible:border-blue focus-visible:text-ink group-open:border-blue group-open:text-ink [&::-webkit-details-marker]:hidden">
        <Info aria-hidden="true" strokeWidth={1.6} className="size-3.5 shrink-0 text-blue" />
        How this was counted
        <ChevronDown aria-hidden="true" strokeWidth={1.75} className="size-3.5 shrink-0 text-faint transition-transform duration-200 group-open:rotate-180" />
      </summary>
      <dl className="mb-2 mt-3 divide-y divide-dashed divide-line border border-line-strong bg-panel">
        <CountedRow label="What Holt read">{lookedAt(report)}</CountedRow>
        <CountedRow label="Words used here">
          A pull request (PR) is a change you propose to a project. Merged means the maintainers accepted it. An outsider is anyone who isn&apos;t on the project&apos;s team, like you.
        </CountedRow>
        {report.counted.map((c) => (
          <CountedRow key={c.topic} label={c.topic}>{c.text}</CountedRow>
        ))}
        {report.unknowns.length > 0 && (
          <CountedRow label="What Holt couldn't check">
            {report.unknowns.map((u) => (
              <p key={u}>{u}</p>
            ))}
          </CountedRow>
        )}
        {report.asks.length > 0 && (
          <CountedRow label="Where the advice comes from">
            {report.asks.map((a) => (
              <p key={a.code}>
                <a className="text-link" href={a.url} target="_blank" rel="noopener noreferrer">
                  {ASK_SOURCE[a.code]} <span aria-hidden="true">↗</span>
                </a>
              </p>
            ))}
          </CountedRow>
        )}
      </dl>
    </details>
  );
}

const ASK_SOURCE: Record<Report["asks"][number]["code"], string> = {
  ticket_first: "The bot closing pull requests with no accepted ticket",
  no_ai_prs: "Where the project turns down AI-written pull requests",
  ok_to_test: "A pull request waiting for a maintainer to approve tests",
  sig_team: "A pull request labelled with its team",
  cla: "A CLA bot asking an outsider to sign",
  dco: "CONTRIBUTING, on signing off commits",
  issue_first: "CONTRIBUTING, on opening an issue first",
  ai_disclosure: "Where the project asks you to say whether you used AI",
  duplicates: "A pull request closed as a duplicate",
  stale_bot: "Where a bot closes quiet pull requests",
};

export function ReportView({
  report,
  issues,
  alternatives,
  signedIn,
  mergePlans,
  reveal,
  land,
  example,
}: {
  report: Report;
  /** The starter-issues block: streamed by the server page, fetched by the runner. */
  issues: React.ReactNode;
  /** Under a Long shot or Not worth your time: other repos to try (alternatives.tsx), from the server page. Without it, one link to Find. */
  alternatives?: React.ReactNode;
  signedIn: boolean;
  /** Merge plans can be made on this server; when not, the card says "coming soon" and starts nothing. */
  mergePlans: boolean;
  /** The report just arrived on this page: step its parts in. A server-rendered report doesn't wait. */
  reveal?: boolean;
  /** The check ran while the visitor watched: the answer lands (VerdictHero) and the numbers count up. */
  land?: boolean;
  /** A recorded example: shares its own link, and takes no votes, badge or view count. */
  example?: boolean;
}) {
  const repo = report.repo;
  const plan = planCta(repo, { available: mergePlans, signedIn });
  const url = example ? `${SITE_URL}${EXAMPLE_PATH}` : `${SITE_URL}/${repo}`;
  const shareText = example ? `An example report on Holt, for ${repo}.` : `${repo} on Holt: ${report.headline}.`;
  // What comes right under the verdict: this repo's issues, other repos, or one link to Find.
  const action = nextAction(report.verdict);
  const language = report.about?.languages[0]?.name;
  // Not worth your time / Not enough evidence / Personal project: nothing here to start on, so
  // where work lands, how to contribute, the evidence, the merge plan,
  // top contributors and the compare card stay out.
  const brief = report.verdict === "not_viable" || report.verdict === "insufficient_evidence" || report.verdict === "personal";
  // Worth your time / Long shot: worth starting, so the sidebar gathers the docs and links to start with.
  const starting = report.verdict === "viable" || report.verdict === "long_shot";

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px] lg:gap-8">
      {!example && <Track event="report-view" data={{ verdict: report.verdict, mode: report.mode, repo }} />}
      <div className="min-w-0 space-y-8">
        {/* A bar in the verdict's colour runs from the verdict down to the next action, as on the landing page's answers. */}
        <div className={`space-y-8 border-l-4 ${TONE[report.tone].border} pl-4 sm:pl-6`} data-verdict-block>
        <VerdictHero report={report} reveal={reveal} land={land} />

        {/* The next action, straight after the verdict and under its colour. */}
        {action === "start" ? (
          <Section id="issues" title="Your first contribution" note="open and unclaimed, best first" reveal={reveal ? 180 : undefined}>
            {issues}
          </Section>
        ) : action === "alternatives" && alternatives ? (
          alternatives
        ) : (
          <FindLine verdict={report.verdict} language={language} />
        )}
        </div>

        {/* Under the decision and what to do about it, never over them. On phones the way to the merge plan
            is here too, so the header above the verdict stays one row. */}
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1" data-after-verdict>
          <span className="sm:hidden">{!example && report.mode === "rules" && <ReportModeLink mode="rules" rulesHref={`/${repo}`} plan={plan} />}</span>
          <ShareMenu url={url} text={shareText} />
        </div>

        {issuesBehindControl(report.verdict) && (
          <details className="group border-y border-line" data-still-here>
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 text-[0.88rem] text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
              <span>I still want to contribute here</span>
              <span aria-hidden="true" className="text-faint group-open:rotate-180">⌄</span>
            </summary>
            <section aria-labelledby="issues" className="pb-4 pt-1">
              <h2 id="issues" className="mb-3 text-[1.05rem] font-semibold tracking-tight sm:text-[1.15rem]">Starter issues</h2>
              {issues}
            </section>
          </details>
        )}

        {/* What happened to outside pull requests, as a bar and its figures: the verdict's evidence at a glance. */}
        <StatsGrid stats={report.stats} reveal={reveal} land={land} />

        {/* The project's own words, right after the numbers: what the software is, before how work lands here. */}
        {report.about?.readme && <ReadmeSection markdown={report.about.readme} repo={repo} contributing={report.about.links?.find((l) => l.kind === "contributing")?.url} />}

        {!brief && (
          <Section id="landing" title="Where newcomer work lands" reveal={reveal ? 230 : undefined}>
            <LandingMap landing={report.landing} neverLanded={report.never_landed} repo={repo} />
          </Section>
        )}

        <HoltUsersLine stats={report.holt_users} />

        {!brief && report.about && <ProjectSection about={report.about} asks={report.asks} />}

        {/* Wide screens have these in the sidebar. */}
        {/* Phones: the merge plan where wide screens have it (under the
            project's numbers), and the sidebar's cards closed by default, so
            the page isn't twice as long as it is on a laptop. */}
        {!brief && report.mode === "rules" && (
          <div className="lg:hidden">
            <UpgradeCard plan={plan} />
          </div>
        )}
        {report.about && (
          <details className="group border-y border-line lg:hidden" data-more-about>
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 text-[0.88rem] text-muted hover:text-ink [&::-webkit-details-marker]:hidden">
              <span>More about this project <span className="text-faint">· numbers, languages, contributors</span></span>
              <span aria-hidden="true" className="text-faint group-open:rotate-180">⌄</span>
            </summary>
            <div className="pb-4 pt-1">
              <ProjectSidebar about={report.about} repo={repo} noPeople={brief} links={starting} />
            </div>
          </details>
        )}

        <PlaybookSection repo={repo} signedIn={signedIn} />

        {/* Pre-flight is for signed-in people (lib/gate.ts), and so is asking whether it is on. */}
        {!example && signedIn && <PreflightLink repo={repo} />}

        {!brief && report.evidence.length > 0 && (
          <CollapsibleSection id="evidence" title="The evidence" count={report.evidence.length} defaultOpen note="every claim links to GitHub">
            <EvidenceList evidence={report.evidence} />
          </CollapsibleSection>
        )}

        {/* Wide screens have this in the sidebar; here it follows the evidence it asks about. */}
        {!example && (
          <div className="lg:hidden">
            <VerdictFeedback report={report} />
          </div>
        )}

        {!example && !brief && (
          <div className="lg:hidden">
            <CompareCard repo={repo} />
          </div>
        )}

        {/* The report's footer: for the maintainer who reads it to the end. */}
        {!example && <BadgeSnippet repo={repo} offered={badgeOffered(report)} />}

      </div>

      <aside className="hidden space-y-4 lg:block" aria-label="About the project and more">
        {/* The merge plan sits right under Statistics, where it's seen, not under six cards. */}
        {report.about ? (
          <ProjectSidebar about={report.about} repo={repo} noPeople={brief} links={starting} afterStats={!brief && report.mode === "rules" ? <UpgradeCard plan={plan} /> : undefined} />
        ) : (
          !brief && report.mode === "rules" && <UpgradeCard plan={plan} />
        )}
        {!example && <VerdictFeedback report={report} />}
        {!example && !brief && <CompareCard repo={repo} />}
      </aside>
    </div>
  );
}
