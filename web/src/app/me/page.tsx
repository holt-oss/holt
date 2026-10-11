// The signed-in home (the dashboard plan): your next move in open
// source, and why. The headline is the one thing to do now, over the loop
// (find a repo → pick an issue → open a PR → get it merged), worked out from
// the account by lib/home.ts. Below it, each hidden when empty: also for you,
// in flight, next repos for you, your repos.
//
// A new account (nothing saved, checked or opened) has none of those, so its
// home is what Holt has without knowing the person: the repo box in the head,
// repos to start in (the picks, from popular languages until there's a profile
// or a merged pull request), issues to start with from those picks, and what
// connecting GitHub adds.
import type { Metadata } from "next";
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { MoveHead } from "@/components/home/move-head";
import { WaitBar } from "@/components/home/wait-bar";
import { PageTransition } from "@/components/motion/page-transition";
import { ProfileFlow } from "@/components/profile-flow";
import { RepoGrid } from "@/components/repo-card/repo-grid";
import { SaveButton } from "@/components/save-button";
import { SectionHead } from "@/components/shell/app-page";
import { Icon } from "@/components/shell/icons";
import { FocusOnHash } from "@/components/shell/check-focus";
import { QuickCheck } from "@/components/shell/quick-check";
import { RepoRows } from "@/components/your-repos/repo-rows";
import { contributions, getProfile, history, preflightState, recommendations, savedRepos, starterIssues } from "@/lib/api";
import type { CatMood } from "@/lib/cat";
import { timeAgo } from "@/lib/format";
import { alsoForYou, clock, dismissedNudges, homeFacts, homeNudge, moveLead, moveTitle, needsYou, nextMove, NUDGE_COOKIE, othersInFlight, outsidePulls, type NextMove, type Nudge } from "@/lib/home";
import { showPreflight } from "@/lib/preflight";
import { SKIP_COOKIE } from "@/lib/profile";
import { allPicksLabel, basisLine, emptyReason, HOME_PICKS, starterRows } from "@/lib/recommendations";
import { fromPick } from "@/lib/repo-card";
import { caller, currentUser } from "@/lib/session";
import { CONNECT_GITHUB, PROFILE_SETTINGS } from "@/lib/settings";
import { yourRepos } from "@/lib/your-repos";
import { dismissNudge } from "./actions";

export const metadata: Metadata = { title: "Your home", robots: { index: false } };

const NOTICES: Record<string, { tone: string; text: string }> = {
  saved: { tone: "text-ink border-line-strong bg-ink/5", text: "Profile saved. Your picks are below." },
  adult: { tone: "text-orange border-orange/50 bg-orange/10", text: "Please confirm you're 18 or older to save a profile." },
  error: { tone: "text-orange border-orange/50 bg-orange/10", text: "We couldn't save your profile just now. Try again in a minute." },
};

const NUDGES: Record<Nudge, { text: string; href: string; cta: string }> = {
  profile: { text: "Tell Holt your languages and it picks repos for you.", href: PROFILE_SETTINGS, cta: "add your languages" },
  github: { text: "Connect GitHub to see your pull requests here.", href: CONNECT_GITHUB, cta: "connect GitHub" },
};

/** What connecting GitHub adds to the home, for someone who hasn't. */
const CONNECTED = [
  "Your open pull requests, with how long each repo usually takes to reply.",
  "Picks in the languages you've already been merged in.",
];

function mood(m: NextMove): CatMood {
  if (m.kind === "merged") return "celebrating";
  if (m.kind === "waiting") return needsYou(m.wait) ? "thinking" : "ready";
  if (m.kind === "issue") return "determined";
  return "ready";
}

export default async function HomePage({ searchParams }: PageProps<"/me">) {
  const user = await currentUser();
  if (!user) redirect("/signin?callbackUrl=/me");
  const [sp, jar, who] = await Promise.all([searchParams, cookies(), caller(user)]);
  const [checks, saved, picks, prs, profile, pre] = await Promise.all([
    history(user.id, 50),
    savedRepos(user.id),
    recommendations(user.id, HOME_PICKS),
    contributions(user.id),
    getProfile(user.id),
    preflightState({}, who),
  ]);

  const now = clock();
  const savedItems = saved.ok ? saved.data.saved : [];
  const savedNames = savedItems.map((i) => i.repo);
  const repos = yourRepos(savedItems, checks.ok ? checks.data.items : [], checks.ok ? checks.data.cards : [], now);
  // Pull requests to other people's projects that count (not left out of your numbers).
  const pulls = prs.ok ? outsidePulls(prs.data.pull_requests, prs.data.login).filter((p) => p.counted) : [];
  const move = nextMove({ pulls, repos, now });
  const also = alsoForYou(move, { pulls, repos, now });
  const flying = othersInFlight(move, pulls, now);
  const issues = move.kind === "issue" ? await starterIssues(move.repo, 3, who) : null;

  const pickCards = picks.ok ? picks.data.picks.map(fromPick) : [];
  const hasProfile = profile.ok ? profile.data.profile !== null : null;
  const askingProfile = move.kind === "first" && hasProfile === false && !jar.get(SKIP_COOKIE) && pickCards.length === 0;
  // Not connected is a 404; any other error means connected but GitHub was slow.
  const connected = prs.ok || prs.error.code !== "not_found";
  // Picks already come from somewhere (a profile or GitHub): no asking for languages over them.
  const dismissed = dismissedNudges(jar.get(NUDGE_COOKIE)?.value);
  const starting = move.kind === "first" && !askingProfile;
  // While you're starting, connecting gets a panel that says what it adds, not the one-line nudge.
  const connectPanel = starting && !connected && !dismissed.includes("github");
  const nudge = homeNudge({ askingProfile, hasProfile: pickCards.length ? true : hasProfile, connected: connected || connectPanel, dismissed });
  // Nothing saved, checked or opened yet: the repo box is the head's action.
  const fresh = move.kind === "first" && !move.again && repos.length === 0;
  // Picks matched on nothing about the person (popular languages).
  const generic = picks.ok && emptyReason(picks.data.basis) === "nothing-to-match";
  const starters = starting && picks.ok ? starterRows(picks.data.picks, 4) : [];
  const notice = typeof sp.profile === "string" ? NOTICES[sp.profile] : undefined;
  const preflight = pre.ok && showPreflight(pre.data);
  const firstPicks = move.kind === "first" && pickCards.length > 0;
  const allPicks = picks.ok ? allPicksLabel(picks.data.total) : null;
  const facts = homeFacts({ repos, pulls });

  let primary: React.ReactNode = null;
  if (move.kind === "waiting") {
    const url = move.wait.pr.url;
    primary = preflight ? (
      <>
        <Link href={`/preflight?pr=${encodeURIComponent(url)}`} className="btn-primary">check it with pre-flight →</Link>
        <a href={url} className="text-link tap text-[0.9rem]">open it on GitHub ↗</a>
      </>
    ) : (
      <a href={url} className="btn-primary">open it on GitHub ↗</a>
    );
  } else if (move.kind === "merged") {
    primary = (
      <>
        <Link href={`/${move.pr.repo}`} className="btn-primary">find your next issue there →</Link>
        <Link href="/find" className="text-link text-[0.9rem]">or a new repo</Link>
      </>
    );
  } else if (fresh) {
    primary = (
      <>
        <div id="check" className="w-full scroll-mt-24">
          <QuickCheck variant="inline" className="max-w-xl!" />
        </div>
        <Link href="/find" className="text-link tap text-[0.9rem]">or find a project</Link>
      </>
    );
  } else if (starting) {
    primary = (
      <Link href="/find" className="find-cta">
        <span aria-hidden="true" className="find-cta-icon"><Icon name="find" className="size-5" /></span>
        <span className="min-w-0">
          <span className="find-cta-title">Find a project</span>
          <span className="find-cta-sub">Repos where outside PRs get merged</span>
        </span>
        <span aria-hidden="true" className="find-cta-arrow">→</span>
      </Link>
    );
  }

  return (
    <PageTransition>
      <div className="app-page">
        <FocusOnHash />
        {!fresh && (
          <div id="check" className="mb-4 scroll-mt-24 md:hidden">
            <QuickCheck variant="inline" />
          </div>
        )}
        <MoveHead title={moveTitle(move)} lead={moveLead(move, repos)} mood={mood(move)} step={move.step} loop={repos.length > 0 || pulls.length > 0}>
          {facts.length > 0 && (
            <p className="mt-3 flex flex-wrap gap-x-2 text-[0.8rem] text-faint">
              {facts.map((f, i) => <span key={f}>{i > 0 && <span aria-hidden="true">· </span>}{f}</span>)}
            </p>
          )}
          {primary && <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3">{primary}</div>}
        </MoveHead>
        {notice && <p role="status" className={`mb-6 border px-4 py-3 font-sans text-[0.9rem] ${notice.tone}`}>{notice.text}</p>}

        {askingProfile && (
          <div className="mt-8">
            <ProfileFlow adultConfirmed={profile.ok && profile.data.adult_confirmed} />
          </div>
        )}

        {move.kind === "issue" && (
          <section aria-labelledby="issues-h" className="home-section mt-9">
            <SectionHead id="issues-h" title="Good first issues" more={{ href: `/${move.repo}`, label: "See the report" }} />
            {issues?.ok && issues.data.issues.length > 0 ? (
              <ul className="home-list" data-stack>
                {issues.data.issues.map((iss, i) => (
                  <li key={iss.number} className="app-row grid-cols-[minmax(0,1fr)_auto]">
                    <div className="min-w-0">
                      <p className="font-sans text-[0.86rem] leading-snug">
                        <span className="mr-2 font-mono text-[0.76rem] text-faint">#{iss.number}</span>
                        {iss.title}
                      </p>
                      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.72rem] text-faint">
                        {iss.labels.slice(0, 3).map((l) => (
                          <span key={l} className="border border-line-strong px-1.5 py-px text-muted">{l}</span>
                        ))}
                        {iss.created_at && <span>opened {timeAgo(iss.created_at)}</span>}
                      </p>
                    </div>
                    <a href={iss.url} className={i === 0 ? "home-btn" : "text-link tap text-[0.8rem]"}>
                      {i === 0 ? "Start here" : "Open"}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <Link href={`/${move.repo}`} className="home-btn mt-2">See what to work on</Link>
            )}
          </section>
        )}

        {nudge && (
          <form action={dismissNudge} className="mt-6 flex flex-wrap items-center gap-x-3 gap-y-1 border-l-2 border-blue py-1 pl-3 font-sans text-[0.9rem] text-muted">
            <input type="hidden" name="nudge" value={nudge} />
            <span>{NUDGES[nudge].text}</span>
            <Link href={NUDGES[nudge].href} className="inline-flex min-h-11 items-center font-mono text-[0.86rem] text-blue hover:underline sm:min-h-0">{NUDGES[nudge].cta}</Link>
            <button type="submit" aria-label="Dismiss" className="ml-auto grid size-11 place-items-center text-faint hover:text-ink sm:size-8">×</button>
          </form>
        )}

        <div className="mt-10 space-y-10">
          {also.length > 0 && (
            <section aria-labelledby="also-h" className="home-section">
              <SectionHead id="also-h" title="Updates" />
              <ul className="home-list" data-stack>
                {also.map((a) =>
                  a.kind === "checking" || a.kind === "ready" ? (
                    <li key={a.repo.repo} className="app-row grid-cols-[minmax(0,1fr)_auto]">
                      <p className="min-w-0 font-sans text-[0.86rem] [overflow-wrap:anywhere]">
                        <span className="font-mono font-semibold">{a.repo.repo}</span>
                        <span className="text-muted">
                          {a.repo.ai
                            ? a.kind === "checking" ? ": the merge plan is still being written." : ": the merge plan is ready."
                            : a.kind === "checking" ? ": the check is still running." : ": the report is ready."}
                        </span>
                      </p>
                      <Link href={`/${a.repo.repo}${a.repo.ai ? "?mode=ai" : ""}`} className="text-link text-[0.8rem]">{a.kind === "checking" ? "Watch" : "Open"}</Link>
                    </li>
                  ) : a.kind === "pr" ? (
                    <li key={a.wait.pr.url} className="app-row grid-cols-[minmax(0,1fr)_auto]">
                      <p className="min-w-0 font-sans text-[0.86rem] [overflow-wrap:anywhere]">
                        <span className="font-mono font-semibold">{a.wait.pr.repo}</span> <span className="font-mono text-[0.76rem] text-faint">#{a.wait.pr.number}</span>
                        <span className="block text-muted">{a.wait.line}</span>
                      </p>
                      <a href={a.wait.pr.url} className="text-link text-[0.8rem]">Open</a>
                    </li>
                  ) : (
                    <li key={a.repo.repo} className="app-row grid-cols-[minmax(0,1fr)_auto]">
                      <p className="min-w-0 font-sans text-[0.86rem] [overflow-wrap:anywhere]">
                        <Link href={`/${a.repo.repo}`} className="font-mono font-semibold hover:text-blue">{a.repo.repo}</Link>
                        <span className="text-muted">: the report changed since you saved it.</span>
                      </p>
                      <SaveButton repo={a.repo.repo} saved compact icon />
                    </li>
                  ),
                )}
              </ul>
            </section>
          )}

          {flying.length > 0 && (
            <section aria-labelledby="flight-h">
              <SectionHead id="flight-h" title="In flight" more={{ href: "/me/contributions", label: "all your pull requests" }} />
              <ul className="home-list">
                {flying.map((w) => (
                  <li key={w.pr.url} className="app-row grid-cols-[minmax(0,1fr)]">
                    <div className="min-w-0">
                      <p className="text-[0.82rem]"><span className="font-semibold">{w.pr.repo}</span> <span className="text-faint">#{w.pr.number}</span></p>
                      <a href={w.pr.url} className="block truncate font-sans text-[0.86rem] after:absolute after:inset-0 hover:underline">{w.pr.title}</a>
                      <WaitBar w={w} />
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {pickCards.length > 0 && picks.ok && (
            <section id="picks" aria-labelledby="picks-h" className="scroll-mt-24">
              <SectionHead
                id="picks-h"
                title={generic ? "Good places to start" : firstPicks ? "Picked for you" : "Next repos for you"}
                more={{ href: PROFILE_SETTINGS, label: generic ? "add your languages" : "edit your profile" }}
              />
              {basisLine(picks.data.basis) && <p className="-mt-1 mb-4 font-sans text-[0.9rem] text-muted">{basisLine(picks.data.basis)}</p>}
              <RepoGrid repos={pickCards} cols={3} saved={savedNames} topicBase="/discover" />
              {allPicks && (
                <p className="mt-3 text-[0.82rem]">
                  <Link href="/me/picks" className="inline-flex min-h-11 items-center text-blue hover:underline sm:min-h-0">{allPicks} →</Link>
                </p>
              )}
            </section>
          )}

          {(starters.length > 0 || connectPanel) && (
            <div className={starters.length > 0 && connectPanel ? "grid items-start gap-10 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]" : undefined}>
              {starters.length > 0 && (
                <section aria-labelledby="starters-h" className="home-section min-w-0">
                  <SectionHead id="starters-h" title="Issues to start with" />
                  <ul className="home-list">
                    {starters.map(({ repo, issue }) => (
                      <li key={issue.url} className="app-row grid-cols-[minmax(0,1fr)]">
                        <div className="min-w-0">
                          <a href={issue.url} className="block font-sans text-[0.86rem] leading-snug [overflow-wrap:anywhere] after:absolute after:inset-0 hover:underline">
                            {issue.title}
                          </a>
                          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.72rem] text-faint">
                            <span className="font-mono text-muted">{repo} #{issue.number}</span>
                            {issue.labels.slice(0, 2).map((l) => (
                              <span key={l} className="border border-line-strong px-1.5 py-px text-muted">{l}</span>
                            ))}
                            {issue.created_at && <span>opened {timeAgo(issue.created_at)}</span>}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              {connectPanel && (
                <section aria-labelledby="connect-h" className="home-section min-w-0">
                  <SectionHead id="connect-h" title="Connect GitHub" />
                  <div className="border border-line-strong bg-panel px-4 py-4">
                    <ul className="space-y-2 font-sans text-[0.86rem] leading-snug text-muted">
                      {CONNECTED.map((line) => (
                        <li key={line} className="flex gap-2">
                          <span aria-hidden="true" className="text-blue">+</span>
                          <span>{line}</span>
                        </li>
                      ))}
                    </ul>
                    <form action={dismissNudge} className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
                      <input type="hidden" name="nudge" value="github" />
                      <Link href={CONNECT_GITHUB} className="home-btn gap-2">
                        <Icon name="github" className="size-4" />
                        connect GitHub
                      </Link>
                      <button type="submit" className="tap text-[0.8rem] text-faint hover:text-ink">not now</button>
                    </form>
                  </div>
                </section>
              )}
            </div>
          )}

          {repos.length > 0 && (
            <section aria-labelledby="mine-h" className="home-section">
              <SectionHead id="mine-h" title="Your repos" more={{ href: "/me/repos", label: `all ${repos.length}` }} />
              <RepoRows rows={repos.slice(0, 4)} saved={savedNames} compact />
            </section>
          )}
        </div>
      </div>
    </PageTransition>
  );
}
