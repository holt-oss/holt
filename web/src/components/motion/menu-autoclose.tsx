"use client";

import { useEffect } from "react";

/**
 * The header's menus are native popovers and the header persists across client
 * navigations, so a menu would stay open after you pick a link in it. Close it
 * on the click, before the page changes, so the page transition shows the new
 * page and not a menu on top of it.
 */
export function MenuAutoClose() {
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const link = (e.target as Element | null)?.closest?.("a[href]");
      const menu = link?.closest("[popover]") as HTMLElement | null;
      if (menu?.matches(":popover-open")) menu.hidePopover();
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);
  return null;
}
