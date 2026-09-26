// Wraps a page's body so route changes crossfade (globals.css): the old page
// fades out, the new one rises 6px and fades in. Lives
// in each page and loading file, not the layout: layouts persist, so enter and
// exit would never fire there. Browsers without view transitions just swap.
// One wrapper element, so a page is one snapshot rather than one per section.
import { ViewTransition } from "react";

export function PageTransition({ children }: { children: React.ReactNode }) {
  return (
    <ViewTransition enter="page-in" exit="page-out" default="none">
      <div>{children}</div>
    </ViewTransition>
  );
}

/**
 * For loading.tsx: the skeleton comes in like a page but leaves quickly, so
 * the page that replaces it isn't kept waiting. `data-route-loading` hides the
 * footer meanwhile (globals.css), so it appears once under the real page
 * instead of jumping when the skeleton's height gives way to the page's.
 */
export function LoadingTransition({ children }: { children: React.ReactNode }) {
  return (
    <ViewTransition enter="page-in" exit="sk-out" default="none">
      <div data-route-loading>{children}</div>
    </ViewTransition>
  );
}
