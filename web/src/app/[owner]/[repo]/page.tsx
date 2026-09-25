import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { notFound, redirect } from "next/navigation";
import { ErrorPanel } from "@/components/error-panel";
import { AnalysisRunner } from "@/components/report/analysis-runner";
import { ReportView } from "@/components/report/report-view";
import { StarterIssues } from "@/components/report/starter-issues";
import { getReport, starterIssues } from "@/lib/api";
import { isValidRepo } from "@/lib/repo";
import { caller, currentUser, type SessionUser } from "@/lib/session";
import { humanHours } from "@/lib/format";
import { SITE_URL } from "@/lib/site";
import type { Mode, Report } from "@/lib/types";

type Props = PageProps<"/[owner]/[repo]">;

function opts(sp: Record<string, string | string[] | undefined>): { mode: Mode; days: number } {
  const mode: Mode = sp.mode === "ai" ? "ai" : "rules";
  const d = Math.round(Number(sp.days));
  return { mode, days: Number.isFinite(d) && d >= 1 && d <= 90 ? d : 7 };
}

function describe(report: Report | null, name: string): string {
  if (!report) return `Holt reads ${name}'s recent pull requests and tells you whether newcomers get replies and get merged.`;
  const s = report.stats;
  const reply = s.median_first_response_hours == null ? "" : `, and the typical first reply takes ${humanHours(s.median_first_response_hours)}`;
  return `${report.headline}. ${s.outsider_merged} of ${s.outsider_attempts} pull requests from outside contributors were merged${reply}. See the evidence and starter issues.`;
}

const titleFor = (name: string) => `${name}: Worth your time? | Holt`;

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

export default async function RepoPage({ params, searchParams }: Props) {
  const { owner, repo } = await params;
  if (!isValidRepo(owner, repo)) notFound();
  const { mode, days } = opts(await searchParams);
  const name = `${owner}/${repo}`;
  const user = await currentUser();
  const signedIn = Boolean(user);
  if (mode === "ai" && !signedIn) redirect(`/signin?callbackUrl=${encodeURIComponent(`/${name}?mode=ai`)}`);

  // Only the report blocks the page; starter issues (a live GitHub call) stream in.
  const report = await getReport(name, mode, days);

  // Normalise to GitHub's casing so shared links and caches agree.
  if (report.ok && report.data.repo !== name && report.data.repo.toLowerCase() === name.toLowerCase()) {
    redirect(`/${report.data.repo}${mode === "ai" ? "?mode=ai" : ""}`);
  }

  const display = report.ok ? report.data.repo : name;
  const [dOwner, dRepo] = display.split("/");

  return (
    <div className="wrap py-8 sm:py-12">
      {mode === "rules" && <JsonLd report={report.ok ? report.data : null} name={display} />}
      <div className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-3">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={`https://github.com/${dOwner}.png?size=80`}
          alt=""
          width={40}
          height={40}
          className="size-10 rounded-md border border-line-strong bg-panel-2"
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[1.05rem] font-semibold tracking-tight sm:text-[1.25rem]">
            <span className="text-muted">{dOwner}/</span>
            {dRepo}
          </p>
          <a href={`https://github.com/${display}`} target="_blank" rel="noopener noreferrer" className="block truncate text-[0.75rem] text-faint hover:text-blue">
            github.com/{display} ↗
          </a>
        </div>
        <nav aria-label="Report type" className="grid w-full grid-cols-2 border border-line-strong text-center text-[0.78rem] sm:flex sm:w-auto">
          <Link
            href={`/${display}`}
            aria-current={mode === "rules" ? "page" : undefined}
            className={`px-3 py-2 ${mode === "rules" ? "bg-ink text-bg" : "text-muted hover:text-ink"}`}
          >
            free report
          </Link>
          <Link
            href={signedIn ? `/${display}?mode=ai` : `/signin?callbackUrl=${encodeURIComponent(`/${display}?mode=ai`)}`}
            aria-current={mode === "ai" ? "page" : undefined}
            className={`px-3 py-2 ${mode === "ai" ? "bg-blue text-on-accent" : "text-muted hover:text-ink"}`}
          >
            AI report ✦
          </Link>
        </nav>
      </div>

      {report.ok ? (
        <ReportView
          report={report.data}
          signedIn={signedIn}
          issues={
            <Suspense fallback={<StarterIssues issues={null} repo={report.data.repo} />}>
              <IssuesSlot repo={report.data.repo} user={user} />
            </Suspense>
          }
        />
      ) : report.error.code === "not_found" ? (
        <AnalysisRunner repo={name} mode={mode} days={days} signedIn={signedIn} />
      ) : (
        <ErrorPanel error={report.error} repo={name} retryHref={`/${name}${mode === "ai" ? "?mode=ai" : ""}`} />
      )}
    </div>
  );
}

async function IssuesSlot({ repo, user }: { repo: string; user: SessionUser | null }) {
  const r = await starterIssues(repo, 6, await caller(user));
  return <StarterIssues issues={r.ok ? r.data.issues : "unavailable"} repo={repo} />;
}
