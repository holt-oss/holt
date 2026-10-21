// GitHub in settings. Accounts shows the connection: the connect form (the
// notice and the 18+ box) until it's connected, then who and disconnect; and
// the offer to merge, when the GitHub account turned out to be another Holt
// account's sign-in. Privacy shows the statistics switch.
import Link from "next/link";
import { connect, disconnect, merge, setStats } from "@/app/settings/accounts/actions";
import { ConnectSubmit, MergeSubmit } from "@/components/connect-github-submit";
import { shortDate } from "@/lib/format";
import type { ConnectError } from "@/lib/settings";
import type { GitHubConnection } from "@/lib/types";

/** The one plain line people agree to by connecting. Shown on the connect form and in Privacy. */
export const STATS_NOTICE =
  "Connecting lets Holt track your public contributions and include them anonymously in repo statistics (shown only when 5+ people contribute).";

const CONNECT_ERRORS: Record<ConnectError, string> = {
  adult: "Connecting GitHub is for people 18 or older. Tick the box to go on. Reports stay open to everyone.",
  taken: "That GitHub account is already connected to another Holt account. Sign in with that one instead.",
  link: "GitHub didn't confirm your account. Try again.",
  unavailable: "Connecting GitHub isn't set up on this server.",
  save: "That didn't connect. Try again in a minute.",
};

type Account = GitHubConnection["account"];

/**
 * Not connected: the consent and the two choices. `viaGitHub` when this
 * person signs in some other way, so GitHub has to confirm the account
 * first; `canLink` when this server can ask it to. When it can't, the form
 * says so in place of the choices and the button.
 */
export function ConnectGitHubForm({ viaGitHub, canLink, error }: { viaGitHub: boolean; canLink: boolean; error?: string }) {
  const unavailable = viaGitHub && !canLink;
  const message = unavailable ? CONNECT_ERRORS.unavailable : error && Object.hasOwn(CONNECT_ERRORS, error) ? CONNECT_ERRORS[error as ConnectError] : null;
  return (
    <form action={connect} className="py-4 sm:px-3">
      {message && <p role="alert" className="mb-5 border border-orange/50 bg-orange/10 px-4 py-3 font-sans text-[0.9rem] text-orange">{message}</p>}
      <p className="font-sans text-[0.95rem]">See your public PRs here, and get picks from where they got merged.</p>
      <ul className="prose-sans mt-4 list-disc space-y-1.5 pl-5 text-[0.92rem] text-muted">
        <li>Holt reads only <strong>public</strong> data about your account, with its own access. It can&apos;t touch your repos and never posts, comments or opens anything as you.</li>
        {viaGitHub && <li>GitHub asks you once to confirm which account is yours. Holt gets what GitHub sign-in gets: your public profile and email.</li>}
        <li>Disconnect any time here. That deletes the connection and the list of repos you viewed.</li>
      </ul>

      <p className="mt-5 border-l-2 border-blue pl-4 text-[0.95rem] font-semibold">{STATS_NOTICE}</p>

      {!unavailable && <fieldset className="mt-5 space-y-3">
        <legend className="sr-only">Your choices</legend>
        <label className="flex min-h-11 cursor-pointer items-start gap-3 text-[0.95rem]">
          <input type="checkbox" name="stats_opt_out" className="mt-1 size-4 accent-blue" />
          <span>
            <strong>Don&apos;t include me in statistics</strong>
            <span className="block text-[0.89rem] text-muted">Your contributions stay out of every repo&apos;s numbers. Change it later in Privacy.</span>
          </span>
        </label>
        <label className="flex min-h-11 cursor-pointer items-start gap-3 text-[0.95rem]">
          <input type="checkbox" name="adult" required className="mt-1 size-4 accent-blue" />
          <span><strong>I&apos;m 18 or older</strong></span>
        </label>
      </fieldset>}

      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2">
        {!unavailable && <ConnectSubmit viaGitHub={viaGitHub} />}
        <Link href="/privacy#connect-github" className="inline-flex min-h-11 items-center text-[0.87rem] text-muted hover:text-ink">what Holt keeps</Link>
      </div>
    </form>
  );
}

/**
 * The GitHub account they just confirmed signs in to another Holt account of
 * theirs. Shown only while the page holds the proof of that (page.tsx).
 */
export function MergeAccountsForm() {
  return (
    <form action={merge} className="py-4 sm:px-3">
      <p className="font-sans text-[0.95rem] font-semibold">That GitHub account signs in to another Holt account.</p>
      <p className="prose-sans mt-2 text-[0.92rem] text-muted">Merge it into this one: everything in it moves here, and GitHub signs in to this account from now on.</p>
      <div className="mt-5">
        <MergeSubmit />
      </div>
    </form>
  );
}

/** Connected: who, since when, and disconnect. */
export function GitHubConnectionRow({ acct }: { acct: NonNullable<Account> }) {
  return (
    <>
      <div className="app-row flex flex-wrap justify-between" data-rule style={{ "--rule": "var(--ink)" } as React.CSSProperties}>
        <div className="min-w-0 pl-2 text-[0.9rem]">
          <p>
            <span className="text-muted">connected as </span>
            <a href={`https://github.com/${acct.login}`} target="_blank" rel="noopener noreferrer" className="font-semibold [overflow-wrap:anywhere] hover:underline">
              @{acct.login}
            </a>
            <span className="text-muted"> · since {shortDate(acct.connected_at)}</span>
          </p>
          <Link href="/me/contributions" className="mt-1 inline-flex min-h-11 items-center text-link sm:min-h-0">your pull requests →</Link>
        </div>
        <form action={disconnect}>
          <button type="submit" className="btn-ghost text-orange">disconnect</button>
        </form>
      </div>
      <p className="mt-3 font-sans text-[0.87rem] text-faint">
        Disconnecting deletes the connection, the list of repos you viewed on Holt and your saved pull requests.
      </p>
    </>
  );
}

/** "Don't include me in statistics". Only means something once GitHub is connected. */
export function StatsSwitch({ acct }: { acct: NonNullable<Account> }) {
  return (
    <form action={setStats} className="flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0 flex-1 basis-64">
        <p className="text-[0.95rem] font-semibold" id="stats-label">Don&apos;t include me in statistics</p>
        <p className="prose-sans mt-1 text-[0.89rem] text-muted">{STATS_NOTICE}</p>
      </div>
      {/* One click flips it: the button sends the opposite of what's saved. */}
      {!acct.stats_opt_out && <input type="hidden" name="stats_opt_out" value="on" />}
      <button
        type="submit"
        role="switch"
        aria-checked={acct.stats_opt_out}
        aria-labelledby="stats-label"
        className={`inline-flex min-h-11 items-center gap-2 border px-3 text-[0.87rem] transition-colors ${acct.stats_opt_out ? "picked" : "border-line-strong text-muted hover:text-ink"}`}
      >
        <span aria-hidden="true" className={`relative h-4 w-7 rounded-full transition-colors ${acct.stats_opt_out ? "bg-sel" : "bg-line-strong"}`}>
          <span className={`absolute top-0.5 size-3 rounded-full bg-bg transition-[left] ${acct.stats_opt_out ? "left-3.5" : "left-0.5"}`} />
        </span>
        {acct.stats_opt_out ? "on" : "off"}
      </button>
    </form>
  );
}
