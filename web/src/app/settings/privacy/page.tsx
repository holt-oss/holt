import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { remove } from "@/app/profile/actions";
import { getProfile, githubConnection } from "@/lib/api";
import { currentUser } from "@/lib/session";
import { CONNECT_GITHUB, PRIVACY_SETTINGS, PROFILE_SETTINGS } from "@/lib/settings";
import { StatsSwitch } from "@/components/connect-github-card";
import { ContactEmail } from "@/components/legal-page";
import { Block, Notice, SectionHead } from "@/components/settings/section-head";

export const metadata: Metadata = { title: "Privacy and data · Settings", robots: { index: false } };

export default async function PrivacySettings({ searchParams }: PageProps<"/settings/privacy">) {
  const user = await currentUser();
  if (!user) redirect(`/signin?callbackUrl=${PRIVACY_SETTINGS}`);
  const sp = await searchParams;
  const [gh, profile] = await Promise.all([githubConnection(user.id), getProfile(user.id)]);
  const acct = gh.ok ? gh.data.account : null;
  const p = profile.ok ? profile.data.profile : null;

  return (
    <section aria-labelledby="privacy-h">
      <SectionHead id="privacy">
        <p>
          Holt keeps little: your sign-in details, the reports you ran, and what you chose to save here. The{" "}
          <Link href="/privacy" className="text-link">privacy policy</Link> has the full list.
        </p>
      </SectionHead>

      {sp.github === "saved" && <Notice tone="good">Saved.</Notice>}
      {sp.profile === "deleted" && <Notice tone="plain">Profile deleted.</Notice>}
      {(sp.github === "error" || sp.profile === "error") && <Notice tone="bad">That didn&apos;t work. Try again in a minute.</Notice>}

      <Block id="stats" title="Statistics">
        <div className="py-4 sm:px-3">
          {acct ? (
            <StatsSwitch acct={acct} />
          ) : (
            <p className="font-sans text-[0.9rem] text-muted">
              Only counts once you <Link href={CONNECT_GITHUB} className="text-link">connect GitHub</Link>. Nothing of yours is in any statistics now.
            </p>
          )}
        </div>
      </Block>

      <Block title="Your profile" className="mt-8">
        <div className="app-row flex flex-wrap justify-between">
          <p className="min-w-0 flex-1 basis-56 font-sans text-[0.9rem] text-muted">
            {p ? "Your languages, time, experience and topics. Deleting it doesn't touch your history." : <>No profile saved. <Link href={PROFILE_SETTINGS} className="text-link">Set one up</Link> for picks.</>}
          </p>
          {p && (
            <form action={remove}>
              <button type="submit" className="btn-ghost text-orange">delete my profile</button>
            </form>
          )}
        </div>
      </Block>

      <Block title="Your account" className="mt-8">
        <p className="prose-sans py-4 text-[0.92rem] sm:px-3">
          To delete your account and everything tied to it, or to get a copy of what we hold, email <ContactEmail /> from the address you sign in with.
        </p>
      </Block>
    </section>
  );
}
