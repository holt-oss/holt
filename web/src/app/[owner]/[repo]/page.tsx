import type { Metadata } from "next";
import Link from "next/link";
import { Suspense, ViewTransition } from "react";
import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { after } from "next/server";
import { ErrorPanel } from "@/components/error-panel";
import { Alternatives, AlternativesSkeleton } from "@/components/report/alternatives";
import { AnalysisRunner } from "@/components/report/analysis-runner";
import { nextAction } from "@/components/report/next-action";
import { MergePlanPanel } from "@/components/report/merge-plan-panel";
import { PartialReport } from "@/components/report/partial-report";
import { ReportLoading } from "@/components/report/report-skeleton";
import { ReportTeaser } from "@/components/report/report-teaser";
import { ReportView } from "@/components/report/report-view";
import { RepoAbout } from "@/components/report/repo-about";
import { StarterIssues, StarterIssuesSkeleton } from "@/components/report/starter-issues";
import { SkeletonReveal } from "@/components/motion/reveal";
import { isBot, mintTicket } from "@/lib/anon-check";
import { getReport, mergePlansAvailable, recordView, savedState, starterIssues } from "@/lib/api";
import { authSecret } from "@/lib/auth-secret";
import { budgetFrom, reportHref } from "@/lib/budget";
import { EXAMPLES_PATH } from "@/lib/examples";
import { reportAccess, reportShows, signInHref } from "@/lib/gate";
import { planCta } from "@/lib/merge-plan-offer";
import { isValidRepo } from "@/lib/repo";
import { caller, currentUser, type SessionUser } from "@/lib/session";
import { humanHours } from "@/lib/format";
import { SITE_URL } from "@/lib/site";
import type { Mode, Report } from "@/lib/types";
import { PageTransition } from "@/components/motion/page-transition";
import { BackLink } from "@/components/your-repos/back-link";
import { SaveButton } from "@/components/save-button";
import { ReportStickyBar, StickySentinel } from "@/components/report/report-sticky-bar";
import { BackButton } from "@/components/report/back-button";
import { HOME } from "@/lib/home";
import { ReportBackLink, ReportModeLink } from "@/components/report/report-tabs";

type Props = PageProps<"/[owner]/[repo]">;

/** Signed out, a report nobody has made yet: a ticket to run the free check here, for people only (lib/anon-check.ts). */
async function anonTicket(repo: string, days: number): Promise<string | null> {
  const secret = authSecret(process.env);
  if (!secret || isBot((await headers()).get("user-agent"))) return null;
  return mintTicket(secret, repo, days);
}

function opts(sp: Record<string, string | string[] | undefined>): { mode: Mode; days: number } {
  const mode: Mode = sp.mode === "ai" ? "ai" : "rules";
  return { mode, days: budgetFrom(sp.days) };
}

function describe(report: Report | null, name: string): string {
  if (!report) return `Do outsiders get replies and get merged at ${name}? Holt checks its recent PRs and tells you.`;
  const s = report.stats;
  const reply = s.median_first_response_hours == null ? "" : `, and the typical first reply takes ${humanHours(s.median_first_response_hours)}`;
  // No outside PR to count (pull requests off, say): the verdict's own reason, not "0 of 0".
  if (!s.outsider_attempts) return `${report.headline}. ${report.verdict_line}`;
  return `${report.headline}. ${s.outsider_merged} of ${s.outsider_attempts} outside PRs got merged${reply}. See the evidence and starter issues.`;
}

const titleFor = (name: string) => `${name}: Worth your time? · Holt`;

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { owner, repo } = await params;
  if (!isValidRepo(owner, repo)) return {};
  const r = await getReport(`${owner}/${repo}`);
  const name = r.ok ? r.data.repo : `${owner}/${repo}`;
  const title = titleFor(name);
  const description = describe(r.ok ? r.data : null, name);
  return {
    title: { absolute: title },
    description,
    alternates: { canonical: `/${name}` },
    openGraph: { title, description, url: `/${name}`, type: "article" },
    twitter: { card: "summary_large_image", title, description },
  };
}

/** schema.org description of the page, for search engines. */
function JsonLd({ report, name }: { report: Report | null; name: string }) {
  const data = {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: titleFor(name),
    url: `${SITE_URL}/${name}`,
    description: describe(report, name),
    ...(report ? { dateModified: report.generated_at } : {}),
    isPartOf: { "@type": "WebSite", name: "Holt", url: SITE_URL },
    about: { "@type": "SoftwareSourceCode", name, codeRepository: `https://github.com/${name}` },
  };
  // Escape "<" so repo-controlled text can never close the script tag.
  const json = JSON.stringify(data).replace(/</g, "\\u003c");
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: json }} />;
}

/** How long the page waits for its data before it sends the loading screen instead. */
const LOADING_AFTER_MS = 120;
const SLOW = Symbol("slow");

/** What `work` resolves to (or throws), or SLOW if it takes longer than `ms`. */
function within<T>(work: Promise<T>, ms: number): Promise<T | typeof SLOW> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const slow = new Promise<typeof SLOW>((resolve) => {
    timer = setTimeout(resolve, ms, SLOW);
  });
  return Promise.race([work, slow]).finally(() => clearTimeout(timer));
}

// This route has no loading.tsx, on purpose. With one, every visit commits the
// loading screen first, and React keeps a shown one up for 300ms (then waits
// for the pictures of the page replacing it), so a report Holt already has
// painted its verdict half a second after the server had it. Here the page
// waits a moment for its data: an answer in time goes out as the page itself,
// verdict in the first paint; a slow one gets the loading screen, already
// visible, and streams in behind it as before. On a click the page you were on
// stays up until one of the two arrives (the pending line says so, nav-pending.tsx).
export default async function RepoPage(props: Props) {
  const page = Report(props);
  // A not-found or a redirect thrown in time leaves from here, with its real status.
  const first = await within(page, LOADING_AFTER_MS);
  if (first !== SLOW) return first;
  return (
    <Suspense fallback={<ReportLoading immediate />}>
      <Late page={page} />
    </Suspense>
  );
}

async function Late({ page }: { page: Promise<React.ReactNode> }) {
  return page;
}

async function Report({ params, searchParams }: Props): Promise<React.ReactNode> {
  const { owner, repo } = await params;
  if (!isValidRepo(owner, repo)) notFound();
  const sp = await searchParams;
  const { mode, days } = opts(sp);
  const name = `${owner}/${repo}`;
  // Whether merge plans can be made here at all: while they can't, nothing on the page offers one.
  const [user, mergePlans] = await Promise.all([currentUser(), mergePlansAvailable()]);
  const signedIn = Boolean(user);
  // Signed out, the plan is behind sign-in; while none can be made, the page says "coming soon" to anyone.
  if (mode === "ai" && !signedIn && mergePlans) redirect(signInHref(`/${name}?mode=ai`));

  // Only the report (and, signed in, whether it's saved: one database read)
  // blocks the page; starter issues (a live GitHub call) stream in.
  // ?mode=ai is the merge plan, made from the free report: its header reads that.
  const [report, saved] = await Promise.all([
    getReport(name, "rules", days),
    user ? savedState(user.id, name) : null,
  ]);

  // Normalise to GitHub's casing so shared links and caches agree.
  if (report.ok && report.data.repo !== name && report.data.repo.toLowerCase() === name.toLowerCase()) {
    redirect(reportHref(report.data.repo, days, mode));
  }

  const display = report.ok ? report.data.repo : name;
  // For Connect GitHub users' "opened a PR after checking it on Holt" (the server ignores the rest).
  if (user && report.ok) after(() => recordView(user.id, report.data.repo));
  const [dOwner, dRepo] = display.split("/");
  // Signed out: the examples in full, every other repo as a teaser. A repo with
  // no report yet runs the free check and ends on the teaser; bots, and anyone
  // over the per-IP limit, get the teaser that offers sign-in instead.
  const access = reportAccess(display, signedIn);
  const found = report.ok ? "report" : report.error.code === "not_found" ? "missing" : "error";
  const ticket = !signedIn && found === "missing" ? await anonTicket(name, days) : null;
  const shows = reportShows({ repo: display, signedIn, found, anonymousCheck: ticket !== null });
  const teaser = shows === "teaser" || shows === "sign-in";

  return (
    <PageTransition>
      <div className="relative">
      <div className="report-wide relative py-5 sm:py-12">
        {mode === "rules" && <JsonLd report={report.ok ? report.data : null} name={display} />}
        <BackLink repo={display} />
        {/* On a phone this is one row (back, name, save), so the verdict starts high. */}
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-3 sm:mb-6 sm:gap-x-4">
          {/* The plan goes back to its report; the report, to wherever you came from. */}
          {mode === "ai" ? <ReportBackLink href={reportHref(display, days)} /> : <BackButton fallback={user ? HOME : "/"} />}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`https://github.com/${dOwner}.png?size=80`}
            alt=""
            width={40}
            height={40}
            // Decorative and small: don't compete with the CSS and fonts the verdict needs,
            // and (lazy) don't hold the page back: React waits for a new page's other pictures before showing it.
            fetchPriority="low"
            loading="lazy"
            decoding="async"
            // Level with the name, not the middle of a tall details block.
            className="hidden size-10 self-start rounded-md border border-line-strong bg-panel-2 sm:block"
          />
          {report.ok && report.data.about ? (
            <div className="min-w-0 flex-1">
              <RepoAbout about={report.data.about} repo={display} />
            </div>
          ) : (
          <div className="min-w-0 flex-1">
            <p className="text-[1.05rem] font-semibold tracking-tight [overflow-wrap:anywhere] sm:text-[1.25rem]">
              <span className="text-muted">{dOwner}/</span>
              {dRepo}
            </p>
            <a href={`https://github.com/${display}`} target="_blank" rel="noopener noreferrer" className="flex min-h-11 items-center truncate text-[0.82rem] text-faint hover:text-blue sm:block sm:min-h-0">
              github.com/{display} ↗
            </a>
          </div>
          )}
          {/* A failed lookup shows "save"; saving again is harmless. Keyed so
              moving to another repo's report starts from that repo's state. */}
          {/* Sharing is under the verdict (ReportView, PartialReport). On a phone the report offers
              the merge plan there too; the plan's own page keeps its way back up here. */}
          <div className={`flex shrink-0 items-center gap-3 self-start ${mode === "ai" ? "w-full justify-between sm:w-auto" : ""}`}>
            <span className={mode === "ai" ? "contents" : "hidden sm:contents"}>
              <ReportModeLink
                mode={mode}
                rulesHref={reportHref(display, days)}
                plan={planCta(display, { available: mergePlans, signedIn })}
                hint
              />
            </span>
            <SaveButton small compact key={display} repo={display} saved={user ? Boolean(saved?.ok && saved.data.saved) : null} />
          </div>
        </div>
        <StickySentinel />
        {report.ok && mode === "rules" && !teaser && (
          <ReportStickyBar repo={display}>
            <SaveButton small compact key={`bar-${display}`} repo={display} saved={user ? Boolean(saved?.ok && saved.data.saved) : null} />
          </ReportStickyBar>
        )}

        {!signedIn && access === "full" && report.ok && <ExampleNote />}

        {/* Switching between the report and the merge plan crossfades the body, not the page. */}
        <ViewTransition key={mode} name="report-body" share="swap" enter="swap" exit="swap" default="none">
          <div>
            {mode === "ai" ? (
              report.ok ? (
                <MergePlanPanel repo={report.data.repo} />
              ) : report.error.code === "not_found" ? (
                <p className="border border-line-strong bg-panel p-5 font-sans sm:p-8" data-merge-plan-no-report>
                  <Link href={reportHref(name, days)} className="text-link">check this repo first →</Link>
                </p>
              ) : (
                <ErrorPanel error={report.error} repo={name} retryHref={reportHref(name, days, mode)} />
              )
            ) : teaser ? (
              report.ok ? (
                <PartialReport report={report.data} back={reportHref(display, days)} />
              ) : (
                <ReportTeaser repo={display} report={null} back={reportHref(display, days)} />
              )
            ) : report.ok && report.data.outdated && mode === "rules" && signedIn ? (
              // Made by an older version of the rules: check again, with the
              // normal progress, and fall back to it only if that fails. (Signed
              // out, an example shows as it is: a re-check needs an account.)
              <AnalysisRunner repo={report.data.repo} mode={mode} days={days} signedIn={signedIn} mergePlans={mergePlans} fallback={report.data} />
            ) : report.ok ? (
              <ReportView
                report={report.data}
                signedIn={signedIn}
                mergePlans={mergePlans}
                alternatives={
                  nextAction(report.data.verdict) === "alternatives" && (
                    <SkeletonReveal fallback={<AlternativesSkeleton />}>
                      <Alternatives repo={report.data.repo} language={report.data.about?.languages[0]?.name ?? null} verdict={report.data.verdict} />
                    </SkeletonReveal>
                  )
                }
                issues={
                  <SkeletonReveal fallback={<StarterIssuesSkeleton />}>
                    <IssuesSlot repo={report.data.repo} user={user} />
                  </SkeletonReveal>
                }
              />
            ) : report.error.code === "not_found" ? (
              <AnalysisRunner repo={name} mode={mode} days={days} signedIn={signedIn} mergePlans={mergePlans} ticket={ticket ?? undefined} />
            ) : (
              <ErrorPanel error={report.error} repo={name} retryHref={reportHref(name, days, mode)} />
            )}
          </div>
        </ViewTransition>
      </div>
      </div>
    </PageTransition>
  );
}

/** Above an example report, for signed-out visitors: what this is, and the way to their own. */
function ExampleNote() {
  return (
    // One line on a phone: the tag and the two links.
    <p className="mb-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border border-line-strong bg-panel-2 px-3 py-1 font-sans text-[0.9rem] text-muted sm:mb-6 sm:px-4 sm:py-3" data-example-note>
      <span className="border border-blue px-2 py-0.5 font-mono text-[0.78rem] text-blue sm:text-[0.85rem]">Example report</span>
      <span className="hidden min-w-0 flex-1 sm:inline">Sign in to check any repo you like.</span>
      <span className="flex flex-wrap gap-x-4 gap-y-5">
        <Link href="/signin" prefetch={false} className="text-link tap">sign in</Link>
        <Link href={EXAMPLES_PATH} className="text-link tap"><span className="hidden sm:inline">more </span>examples</Link>
      </span>
    </p>
  );
}

async function IssuesSlot({ repo, user }: { repo: string; user: SessionUser | null }) {
  const r = await starterIssues(repo, 6, await caller(user));
  return <StarterIssues issues={r.ok ? r.data.issues : "unavailable"} repo={repo} />;
}
