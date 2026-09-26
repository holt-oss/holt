"use client";
// A safety net under Next's client router. When a link is clicked while its
// prefetch is still being applied, the router can commit the new page's
// segment as nothing: its prefetched data resolves to null, the route's
// loading boundary is in "content" state, and the page only fills in when
// the real response lands. Seen on production through the Cloudflare tunnel:
// <main> stayed empty for over a second, so no skeleton showed and the footer
// jumped up under the header, then back down (CLS 0.19 on desktop, 0.38 on
// phones). Mock and local runs never hit it because the prefetch lands before
// anyone can click.
//
// While <main> has no element in it, this renders the loading skeleton of the
// route in the address bar (the same one its loading.tsx would show) and drops
// it as soon as the page arrives. React applies both updates only once the
// router's view transition is ready, 10-30ms after the DOM changed; globals.css
// covers the gap (the footer stays hidden under an empty <main>, and the
// fallback is display:none as soon as it has a sibling), so nothing shifts.
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import CompareLoading from "@/app/compare/loading";
import FindLoading from "@/app/find/loading";
import HacktoberfestLoading from "@/app/hacktoberfest/loading";
import HowItWorksLoading from "@/app/how-it-works/loading";
import HistoryLoading from "@/app/me/history/loading";
import PricingLoading from "@/app/pricing/loading";
import SettingsLoading from "@/app/settings/loading";
import SigninLoading from "@/app/signin/loading";
import ReportLoading from "@/app/[owner]/[repo]/loading";
import RootLoading from "@/app/loading";
import { PageHeadSkeleton } from "../page-head-skeleton";
import { SkeletonRegion } from "../skeleton";
import { LoadingTransition } from "./page-transition";

const MAIN_ID = "content";

/** Static routes with a loading.tsx. Anything else two segments deep is a report. */
const ROUTES: Record<string, React.ReactElement> = {
  "/": <RootLoading />,
  "/compare": <CompareLoading />,
  "/find": <FindLoading />,
  "/hacktoberfest": <HacktoberfestLoading />,
  "/how-it-works": <HowItWorksLoading />,
  "/me/history": <HistoryLoading />,
  "/pricing": <PricingLoading />,
  "/settings": <SettingsLoading />,
  "/signin": <SigninLoading />,
};

const GENERIC = (
  <LoadingTransition>
    <SkeletonRegion>
      <PageHeadSkeleton />
    </SkeletonRegion>
  </LoadingTransition>
);

function loadingFor(pathname: string): React.ReactElement {
  const known = ROUTES[pathname];
  if (known) return known;
  return pathname.split("/").filter(Boolean).length === 2 ? <ReportLoading /> : GENERIC;
}

function subscribe(onChange: () => void) {
  const main = document.getElementById(MAIN_ID);
  if (!main) return () => {};
  const observer = new MutationObserver(onChange);
  observer.observe(main, { childList: true });
  return () => observer.disconnect();
}

/** True while <main> holds nothing but this fallback (Suspense comment nodes don't count). */
function isMainEmpty() {
  const main = document.getElementById(MAIN_ID);
  if (!main) return false;
  for (const el of main.children) if (!el.hasAttribute("data-route-fallback")) return false;
  return true;
}

export function RouteFallback() {
  const empty = useSyncExternalStore(subscribe, isMainEmpty, () => false);
  const pathname = usePathname();
  if (!empty) return null;
  return <div data-route-fallback>{loadingFor(pathname)}</div>;
}
