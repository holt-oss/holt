// Your pull requests (the dashboard plan): is each one going anywhere?
// Grouped by next move: your turn (the project replied), needs you (waiting
// longer than the repo usually takes), waiting, merged, closed. Each open row
// carries its one line (home.ts `waiting`). Any repo can be left out of your numbers
// (a friend's project, your team's repo, a hackathon); those collect, undoable,
// in a folded "Not counted" group. With PR watch (API.md), a watched row has a
// bell to mute it and a "new" tag for an alert not opened yet, and the first
// visit offers to turn alerts on.
import type { Metadata } from "next";
import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";
import { FirstTime } from "@/components/alerts/first-time";
import { WatchToggle } from "@/components/alerts/watch-toggle";
import { ContributionHistorySlot } from "@/components/contributions/history-slot";
import { RefreshButton } from "@/components/contributions/refresh-button";
import { ErrorPanel } from "@/components/error-panel";
import { MarkedTitle } from "@/components/home/move-head";
import { WaitBar } from "@/components/home/wait-bar";
import { NewCount } from "@/components/motion/count-up";
import { PageTransition } from "@/components/motion/page-transition";
import { AppPageHeader, SectionHead } from "@/components/shell/app-page";
import { sampleAlerts, showFirstTime } from "@/lib/alerts";
import { alertList, contributions, preflightState } from "@/lib/api";
import { landedLine, prGroups, prsTitle, STATE_LABEL, type PrGroups } from "@/lib/contributions";
import { timeAgo } from "@/lib/format";
import { clock, dismissedNudges, NUDGE_COOKIE, outsidePulls, type Waiting } from "@/lib/home";
import { showPreflight } from "@/lib/preflight";
import { caller, currentUser } from "@/lib/session";
import { CONNECT_GITHUB } from "@/lib/settings";
import type { ContributionPR } from "@/lib/types";
import { dismissAlertsCard, refresh, setCounted } from "./actions";

export const metadata: Metadata = { title: "Your pull requests", robots: { index: false } };

const NOTICES: Record<string, { tone: string; text: string }> = {
  done: { tone: "text-ink border-line-strong bg-ink/5", text: "Updated from GitHub." },
  wait: { tone: "text-muted border-line-strong", text: "Already up to date: we checked GitHub a few minutes ago." },
  limited: { tone: "text-orange border-orange/50 bg-orange/10", text: "GitHub is asking us to slow down. Your list below is from the last check; try again in a few minutes." },
  error: { tone: "text-orange border-orange/50 bg-orange/10", text: "We couldn't reach GitHub just now. Your list below is from the last check; try again in a minute." },
};

const RULE = { yours: "var(--orange)", needs: "var(--orange)", waiting: "var(--blue)", merged: "var(--green)", closed: "var(--line-strong)" };

function CountForm({ repo, counted, label, className }: { repo: string; counted: "yes" | "no" | "reset"; label: string; className: string }) {
  return (
    <form action={setCounted}>
      <input type="hidden" name="repo" value={repo} />
      <input type="hidden" name="counted" value={counted} />
      <button type="submit" className={className} title={counted === "no" ? `Leave ${repo} out of your numbers` : undefined}>{label}</button>
    </form>
  );
}

function PrRow({ p, w, rule, action }: { p: ContributionPR; w?: Waiting; rule: string; action?: React.ReactNode }) {
  const [owner, name] = p.repo.split("/");
  return (
    <li data-rule data-stack className="app-row grid-cols-[minmax(0,1fr)_auto]" style={{ "--rule": rule } as React.CSSProperties}>
      <div className="min-w-0 pl-2">
        <p className="flex flex-wrap items-baseline gap-x-2 text-[0.9rem]">
          <Link href={`/${p.repo}`} className="tap z-10 font-semibold tracking-tight hover:text-blue"><span className="font-normal text-muted">{owner}/</span>{name}</Link>
          <span className="text-[0.8rem] text-faint">#{p.number}</span>
          {p.found_via_holt && <span className="border border-blue/40 px-1.5 text-[0.72rem] text-blue">found via Holt</span>}
          {p.unread_alert && <span className="border border-orange/50 px-1.5 text-[0.72rem] text-orange">new</span>}
        </p>
        <a href={p.url} className="mt-0.5 block truncate font-sans text-[0.95rem] after:absolute after:inset-0 hover:underline">{p.title}</a>
        {w ? (
          <WaitBar w={w} />
        ) : (
          <p className="mt-1 text-[0.78rem] text-faint">
            {STATE_LABEL[p.state]} {timeAgo(p.merged_at ?? p.closed_at ?? p.created_at)}
            {p.verdict && <> · Holt: {p.verdict.headline.toLowerCase()}</>}
          </p>
        )}
      </div>
      <div className="relative z-10 flex flex-wrap items-center gap-x-5 gap-y-2 sm:flex-nowrap sm:gap-4">
        {p.watch && <WatchToggle repo={p.repo} number={p.number} initial={p.watch} />}
        {action}
        <CountForm repo={p.repo} counted="no" label="don't count" className="min-h-11 text-[0.8rem] text-faint transition-colors hover:text-ink sm:min-h-9" />
      </div>
    </li>
  );
}

function Groups({ g, preflight }: { g: PrGroups; preflight: boolean }) {
  const lateAction = (w: Waiting) =>
    preflight ? (
      <Link href={`/preflight?pr=${encodeURIComponent(w.pr.url)}`} className="btn-primary min-h-11 px-4 text-[0.84rem] sm:min-h-10">pre-flight →</Link>
    ) : (
      <a href={w.pr.url} className="text-link tap text-[0.84rem]">open it ↗</a>
    );
  const sections = [
    { id: "yours", title: "Your turn", n: g.yours.length, rows: g.yours.map((w) => <PrRow key={w.pr.url} p={w.pr} w={w} rule={RULE.yours} action={<a href={w.pr.url} className="text-link tap text-[0.84rem]">open it ↗</a>} />) },
    { id: "needs", title: "Needs you", n: g.needs.length, rows: g.needs.map((w) => <PrRow key={w.pr.url} p={w.pr} w={w} rule={RULE.needs} action={lateAction(w)} />) },
    { id: "waiting", title: "Waiting", n: g.waiting.length, rows: g.waiting.map((w) => <PrRow key={w.pr.url} p={w.pr} w={w} rule={RULE.waiting} />) },
    { id: "merged", title: "Merged", n: g.merged.length, rows: g.merged.map((p) => <PrRow key={p.url} p={p} rule={RULE.merged} />) },
    { id: "closed", title: "Closed", n: g.closed.length, rows: g.closed.map((p) => <PrRow key={p.url} p={p} rule={RULE.closed} />) },
  ];
  return (
    <>
      {sections.map((s) =>
        s.n ? (
          <section key={s.id} aria-labelledby={`${s.id}-h`}>
            <SectionHead id={`${s.id}-h`} title={s.title} note={String(s.n)} />
            <ul>{s.rows}</ul>
          </section>
        ) : null,
      )}
      {g.notCounted.length > 0 && (
        <details className="group">
          <summary className="section-head cursor-pointer list-none">
            <h2 className="flex items-center gap-2">
              Not counted <span className="font-normal text-faint">{g.notCounted.reduce((n, r) => n + r.pulls.length, 0)}</span>
            </h2>
            <span aria-hidden="true" className="text-faint transition-transform group-open:rotate-180">▾</span>
          </summary>
          <ul>
            {g.notCounted.map((r) => (
              <li key={r.repo} data-stack className="app-row grid-cols-[minmax(0,1fr)_auto]">
                <div className="min-w-0">
                  <Link href={`/${r.repo}`} className="tap font-semibold tracking-tight hover:text-blue">{r.repo}</Link>
                  <p className="mt-0.5 text-[0.78rem] text-faint">
                    {r.pulls.length} pull request{r.pulls.length === 1 ? "" : "s"} · {r.because === "own_project" ? "Holt: your own or your team's project" : "left out by you"}
                  </p>
                </div>
                <CountForm repo={r.repo} counted={r.because === "own_project" ? "yes" : "reset"} label="count it" className="text-link tap text-[0.84rem]" />
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

export default async function ContributionsPage({ searchParams }: PageProps<"/me/contributions">) {
  const user = await currentUser();
  if (!user) redirect("/signin?callbackUrl=/me/contributions");
  const [sp, who, jar] = await Promise.all([searchParams, caller(user), cookies()]);
  const [r, pre, alerts] = await Promise.all([contributions(user.id), preflightState({}, who), alertList(user.id)]);
  const notConnected = !r.ok && r.error.code === "not_found";
  const notice = sp.count === "error"
    ? { tone: NOTICES.error.tone, text: "We couldn't save that just now. Try again in a minute." }
    : typeof sp.refresh === "string" ? NOTICES[sp.refresh] : undefined;
  const d = r.ok ? r.data : null;
  const now = clock();
  const pulls = d ? outsidePulls(d.pull_requests, d.login) : [];
  const g = d ? prGroups(pulls, now) : null;
  const offerAlerts = alerts.ok && showFirstTime({ access: alerts.data.access, pulls, dismissed: dismissedNudges(jar.get(NUDGE_COOKIE)?.value) });
  const s = d?.summary;
  // Nothing to group yet: the head says so, and its one action is finding a repo.
  const none = !!g && !g.yours.length && !g.needs.length && !g.waiting.length && !g.merged.length && !g.closed.length;

  return (
    <PageTransition>
      <div className="app-page">
        {notConnected ? (
          <>
            <AppPageHeader sentence title="Your pull requests" mood="thinking">
              <div className="mt-7">
                <Link href={CONNECT_GITHUB} className="btn-primary">connect GitHub →</Link>
              </div>
            </AppPageHeader>
          </>
        ) : !r.ok ? (
          <>
            <AppPageHeader sentence title="Your pull requests" />
            <ErrorPanel error={r.error} retryHref="/me/contributions" />
          </>
        ) : d && g && s && (
          <>
            <AppPageHeader sentence title={<MarkedTitle title={prsTitle(g)} />} mood={g.yours.length || g.needs.length ? "thinking" : g.waiting.length ? "ready" : g.merged.length ? "celebrating" : "ready"}>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 text-[0.84rem] text-muted">
                <p className="flex flex-wrap gap-x-5 gap-y-1">
                  <span><b className="text-ink"><NewCount id={`prs:${d.login}:opened`} value={s.opened} /></b> opened {d.truncated ? "(your latest 200)" : "this year"}</span>
                  <span><b className="text-green"><NewCount id={`prs:${d.login}:merged`} value={s.merged} /></b> merged</span>
                  {s.closed > 0 && <span><b className="text-ink"><NewCount id={`prs:${d.login}:closed`} value={s.closed} /></b> closed</span>}
                  {landedLine(s) && <span>{landedLine(s)}</span>}
                  {s.found_via_holt > 0 && <span><b className="text-blue"><NewCount id={`prs:${d.login}:holt`} value={s.found_via_holt} /></b> found via Holt</span>}
                  <span className="text-faint">as @{d.login} · updated <time dateTime={d.fetched_at}>{timeAgo(d.fetched_at)}</time></span>
                </p>
                <RefreshButton action={refresh} nextRefreshAt={d.next_refresh_at} />
              </div>
              {none && (
                <div className="mt-7">
                  <Link href="/find" className="btn-primary">find a project →</Link>
                </div>
              )}
            </AppPageHeader>
            {notice && <p role="status" className={`mb-6 border px-4 py-3 font-sans text-[0.9rem] ${notice.tone}`}>{notice.text}</p>}
            {offerAlerts && <FirstTime samples={sampleAlerts(pulls, now)} dismiss={dismissAlertsCard} />}
            <ContributionHistorySlot data={d} />
            <div className="mt-6 space-y-12">
              <Groups g={g} preflight={pre.ok && showPreflight(pre.data)} />
            </div>
            {none ? null : (
              <p className="mt-12 font-sans text-[0.92rem] text-muted">
                Next one? <Link href="/find" className="text-link font-mono text-[0.88rem]">find a project</Link>
              </p>
            )}
          </>
        )}
      </div>
    </PageTransition>
  );
}
