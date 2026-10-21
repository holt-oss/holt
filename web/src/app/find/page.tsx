import type { Metadata } from "next";
import { cookies } from "next/headers";
import { FindFrame } from "@/components/find/find-frame";
import { FindView } from "@/components/find/find-view";
import { PageTransition } from "@/components/motion/page-transition";
import { getProfile, savedNames } from "@/lib/api";
import { cachedFind } from "@/lib/find-cached";
import { indexFind } from "@/lib/find-index";
import { defaultPicks, findQuery, PICKS_COOKIE, resolvePicks, searchKey } from "@/lib/find-picks";
import { caller, currentUser } from "@/lib/session";
import { hacktoberfestSwitch } from "@/lib/site";

export const metadata: Metadata = {
  title: "Find a project",
  description: "Projects that reply to and merge outside contributors, with specific issues to start on. Filter by language and how fast maintainers reply.",
  alternates: { canonical: "/find" },
};

// Results come first: the page always searches (the default search is shared
// by every visitor, so it's almost always cached), and the filters refine it
// in place. See components/find/find-view.tsx.
export default async function FindPage({ searchParams }: PageProps<"/find">) {
  const [sp, user, jar] = await Promise.all([searchParams, currentUser(), cookies()]);
  const [profileR, saved] = await Promise.all([user ? getProfile(user.id) : null, savedNames(user?.id)]);
  const profile = profileR?.ok ? profileR.data.profile : null;
  // An explicit choice (URL, last picks) wins; otherwise the switch starts on only in October.
  const hf = hacktoberfestSwitch();
  const { picks, source } = resolvePicks({ params: sp, cookie: jar.get(PICKS_COOKIE)?.value, profile, hfWindow: Boolean(hf), hfOn: hf?.on ?? false });
  // Signed out, the default search is the one every visitor shares (so it's
  // almost always cached); other picks are answered from Holt's index alone.
  const shared = searchKey(picks) === searchKey(defaultPicks(hf?.on ?? false));
  const result = user || shared ? await cachedFind(findQuery(picks), await caller(user)) : await indexFind(picks);

  return (
    <PageTransition>
      <FindFrame tab="find" title="Find a project" signedIn={Boolean(user)}>
        <FindView
          notice={sp.profile === "saved" && (
            <p role="status" className="mt-5 border border-line-strong bg-ink/5 px-4 py-2.5 font-sans text-[0.9rem] text-ink">Profile saved.</p>
          )}
          initialPicks={picks} initial={result} source={source} hf={hf} saved={saved} signedIn={Boolean(user)} profile={profile} />
      </FindFrame>
    </PageTransition>
  );
}
