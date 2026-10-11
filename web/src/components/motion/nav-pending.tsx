"use client";
// The pending line: a 2px sweep along the top of the window while a click is
// still on its way to its page (lib/nav-pending.ts). It is the report tabs'
// LinkHint (globals.css `.link-hint`), for a page that has no loading screen
// to show at the click: the page you were on stays up, and this says the
// click was heard.
import { usePathname } from "next/navigation";
import { useEffect, useSyncExternalStore } from "react";
import { navigationSettled, pendingPath, subscribe } from "@/lib/nav-pending";

export function NavPending() {
  const pathname = usePathname();
  const to = useSyncExternalStore(subscribe, pendingPath, () => null);
  useEffect(navigationSettled, [pathname]);
  // A redirect back to the page you were on changes no pathname; the history entry still changes.
  useEffect(() => {
    const history = (window as { navigation?: EventTarget }).navigation;
    history?.addEventListener("currententrychange", navigationSettled);
    return () => history?.removeEventListener("currententrychange", navigationSettled);
  }, []);
  if (to === null || to === pathname) return null;
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-x-0 top-0 z-[110] h-0.5 text-blue" data-nav-pending>
      <span className="link-hint is-pending" />
    </div>
  );
}
