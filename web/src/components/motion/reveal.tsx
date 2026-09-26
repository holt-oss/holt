// A Suspense boundary whose skeleton hands over to the content: the skeleton
// fades out in 120ms, then the content fades and rises in (globals.css
// `.sk-out` / `.sk-in`). React already keeps a shown fallback for at least
// 300ms, so a skeleton never blinks.
import { Suspense, ViewTransition } from "react";

export function SkeletonReveal({ fallback, children }: { fallback: React.ReactNode; children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <ViewTransition exit="sk-out" default="none">
          {fallback}
        </ViewTransition>
      }
    >
      <ViewTransition enter="sk-in" default="none">
        {children}
      </ViewTransition>
    </Suspense>
  );
}
