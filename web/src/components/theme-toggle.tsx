"use client";

import { useEffect } from "react";

const KEY = "holt-theme";
/** Set when the visitor closes the Hacktoberfest pill (per year). */
export const HF_KEY = `holt-hf-${new Date().getUTCFullYear()}-dismissed`;

/** Runs in <head> before paint so there is never a flash of the wrong theme. */
export const themeScript = `(function(){try{var d=document.documentElement,t=localStorage.getItem('${KEY}');if(t!=='light'&&t!=='dark'){t=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}d.dataset.theme=t;if(localStorage.getItem('${HF_KEY}'))d.dataset.hfDismissed='1'}catch(e){}})()`;

export function ThemeToggle() {
  // Follow the system until the person picks a theme themselves.
  useEffect(() => {
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      try {
        if (localStorage.getItem(KEY)) return;
      } catch {}
      document.documentElement.dataset.theme = mq.matches ? "dark" : "light";
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  function toggle() {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(KEY, next);
    } catch {}
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="grid size-11 place-items-center border border-transparent text-muted transition-colors hover:border-line-strong hover:text-ink"
      title="Switch light / dark theme"
    >
      <span className="sr-only">Switch between light and dark theme</span>
      {/* Both icons render; CSS shows the right one, so server HTML never mismatches. */}
      <svg className="hidden size-[18px] dark:block" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
      <svg className="block size-[18px] dark:hidden" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11Z" />
      </svg>
    </button>
  );
}
