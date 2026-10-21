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
// route in the address bar (the same one its loading.tsx would show; a report
// has none and sends its own, see the report page) and drops it as soon as the
// page arrives. React applies both updates only once the
// router's view transition is ready, 10-30ms after the DOM changed; CSS covers
// the gap (route-fallback.css: the footer stays hidden under an empty <main>;
// globals.css: the fallback is display:none as soon as it has a sibling), so
// nothing shifts.
import { usePathname } from "next/navigation";
import { useSyncExternalStore } from "react";
import CompareLoading from "@/app/compare/loading";
import FindLoading from "@/app/find/loading";
import HacktoberfestLoading from "@/app/hacktoberfest/loading";
import HowItWorksLoading from "@/app/how-it-works/loading";
import ContributionsLoading from "@/app/me/contributions/loading";
import HomeLoading from "@/app/me/loading";
import ReposLoading from "@/app/me/repos/loading";
import PricingLoading from "@/app/pricing/loading";
import SettingsLoading from "@/app/settings/loading";
import SigninLoading from "@/app/signin/loading";
import LandingLoading from "@/app/(home)/loading";
import { PageLoading } from "../page-head-skeleton";
import { ReportLoading } from "../report/report-skeleton";
import { Skeleton } from "../skeleton";
import "./route-fallback.css";

const MAIN_ID = "content";

/** Static routes with a loading.tsx. Anything else two segments deep is a report. */
const ROUTES: Record<string, React.ReactElement> = {
  "/": <LandingLoading />,
  "/compare": <CompareLoading />,
  "/find": <FindLoading />,
  "/hacktoberfest": <HacktoberfestLoading />,
  "/how-it-works": <HowItWorksLoading />,
  "/me": <HomeLoading />,
  "/me/contributions": <ContributionsLoading />,
  "/me/repos": <ReposLoading />,
  "/pricing": <PricingLoading />,
  "/signin": <SigninLoading />,
};

/** Settings pages share a layout, and its loading.tsx only covers the section. */
const SETTINGS = (
  <div className="app-page">
    <div className="app-head sentence-head">
      <span className="flex h-[clamp(1.61rem,2.53vw,2.13rem)] items-center">
        <Skeleton className="h-[62%] w-40" />
      </span>
    </div>
    <div className="app-tabs">
      {[0, 1, 2, 3, 4].map((i) => (
        <span key={i} className="flex min-h-11 items-center px-3">
          <Skeleton className="h-3 w-16" />
        </span>
      ))}
    </div>
    <div className="max-w-3xl pt-8">
      <SettingsLoading />
    </div>
  </div>
);

function loadingFor(pathname: string): React.ReactElement {
  const known = ROUTES[pathname];
  if (known) return known;
  if (pathname === "/settings" || pathname.startsWith("/settings/")) return SETTINGS;
  return pathname.split("/").filter(Boolean).length === 2 ? <ReportLoading /> : <PageLoading />;
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
