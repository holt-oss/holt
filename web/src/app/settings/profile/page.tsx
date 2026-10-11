import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getProfile } from "@/lib/api";
import { shortDate } from "@/lib/format";
import { findHref } from "@/lib/profile";
import { currentUser } from "@/lib/session";
import { PRIVACY_SETTINGS, PROFILE_SETTINGS } from "@/lib/settings";
import { ProfileForm } from "@/components/profile-form";
import { Notice, SectionHead } from "@/components/settings/section-head";

export const metadata: Metadata = { title: "Your profile · Settings", robots: { index: false } };

export default async function ProfileSettings({ searchParams }: PageProps<"/settings/profile">) {
  const user = await currentUser();
  if (!user) redirect(`/signin?callbackUrl=${PROFILE_SETTINGS}`);
  const { profile: notice } = await searchParams;
  const r = await getProfile(user.id);
  const p = r.ok ? r.data.profile : null;

  return (
    <section aria-labelledby="profile-h">
      <SectionHead id="profile" />

      {notice === "saved" && p && (
        <Notice tone="good">
          Saved. Your picks now start from this.{" "}
          <Link href={findHref(p)} className="font-semibold underline underline-offset-2">see your picks →</Link>
        </Notice>
      )}
      {notice === "adult" && <Notice tone="bad">Tick the 18+ box to save a profile.</Notice>}
      {notice === "error" && <Notice tone="bad">That didn&apos;t save. Try again in a minute.</Notice>}
      {!r.ok && <p role="alert" className="mb-6 border border-orange/50 px-4 py-3 font-sans text-[0.9rem] text-orange">{r.error.message}</p>}

      {r.ok && (
        <ProfileForm prefs={p} adultConfirmed={r.data.adult_confirmed} back={PROFILE_SETTINGS} submitLabel={p ? "save changes" : "save my profile"} />
      )}

      {p && (
        <p className="mt-8 border-t border-line pt-5 font-sans text-[0.87rem] text-faint">
          {p.updated_at && <>Last saved {shortDate(p.updated_at)}. </>}
          To delete it, go to <Link href={PRIVACY_SETTINGS} className="text-link">Privacy and data</Link>.
        </p>
      )}
    </section>
  );
}
