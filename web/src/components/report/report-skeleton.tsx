// The report page's shape while it loads: same grid, gaps and line heights as
// the real page (see [owner]/[repo]/page.tsx and report-view.tsx), so the
// swap to content doesn't move anything.
import { Skeleton, SkeletonRegion, SkeletonText } from "../skeleton";
import { StarterIssuesSkeleton } from "./starter-issues";

function SectionSkeleton({ children, title = "14rem" }: { children: React.ReactNode; title?: string }) {
  return (
    <div className="border-t border-line pt-8">
      <div className="mb-5 flex h-[2.0625rem] items-center gap-x-4 sm:h-[2.31rem]">
        <Skeleton className="h-3 w-5" />
        <Skeleton className="h-5 max-w-[70%]" style={{ width: title }} />
      </div>
      {children}
    </div>
  );
}

export function StatsGridSkeleton({ tiles = 6 }: { tiles?: number }) {
  return (
    <ul aria-hidden="true" className="grid gap-px overflow-hidden border border-line bg-line shadow-soft sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: tiles }, (_, i) => (
        <li key={i} className="bg-panel p-5">
          <span className="flex h-[2.0rem] items-center">
            <Skeleton className="h-6 w-24" />
          </span>
          <SkeletonText lines={2} lineHeight="1.2375rem" bar="0.7rem" last="55%" className="mt-1" />
        </li>
      ))}
    </ul>
  );
}

/** The verdict card and the sections under it. */
export function ReportBodySkeleton() {
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-10">
      <div className="min-w-0 space-y-10">
        <div className="relative overflow-hidden border border-line-strong bg-panel shadow-card">
          <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-line-strong" />
          <div className="p-5 pl-6 sm:p-8 sm:pl-10">
            <div className="flex h-[1.5rem] items-center justify-between gap-4">
              <Skeleton className="h-3 w-64 max-w-[70%]" />
              <Skeleton className="h-4 w-14" />
            </div>
            {/* The headline: two lines on phones, one on wide screens. */}
            <span className="mt-4 block">
              <span className="flex h-[2.7rem] items-center sm:h-[4.16rem]">
                <Skeleton className="h-[1.9rem] w-[85%] sm:h-[3rem] sm:w-[60%]" />
              </span>
              <span className="flex h-[2.7rem] items-center sm:hidden">
                <Skeleton className="h-[1.9rem] w-[45%]" />
              </span>
            </span>
            <SkeletonText lines={2} lineHeight="1.706rem" bar="0.95rem" last="70%" className="mt-4 max-w-2xl" />
            <span className="mt-3 flex h-[1.353rem] items-center">
              <Skeleton className="h-3 w-72 max-w-[80%]" />
            </span>
            <span className="mt-4 flex h-[1.221rem] items-center">
              <Skeleton className="h-2.5 w-96 max-w-[90%]" />
            </span>
          </div>
        </div>

        <div className="flex gap-2 lg:hidden">
          <Skeleton className="h-11 w-24" />
          <Skeleton className="h-11 w-11" />
          <Skeleton className="h-11 w-11" />
        </div>

        <SectionSkeleton>
          <StarterIssuesSkeleton />
        </SectionSkeleton>

        <SectionSkeleton title="20rem">
          <StatsGridSkeleton />
        </SectionSkeleton>
      </div>

      <div className="hidden lg:block">
        <div className="space-y-4">
          <div className="panel p-4">
            <Skeleton className="mb-3 h-3 w-36" />
            <div className="flex gap-2">
              <Skeleton className="h-11 w-24" />
              <Skeleton className="h-11 w-11" />
              <Skeleton className="h-11 w-11" />
            </div>
          </div>
          <Skeleton className="h-44 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      </div>
    </div>
  );
}

/** The repo line and the free / AI tabs. */
export function ReportHeaderSkeleton() {
  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-4 gap-y-3">
      <span aria-hidden="true" className="size-10 rounded-md border border-line-strong bg-panel-2" />
      <div className="min-w-0 flex-1">
        <span className="flex h-[1.7325rem] items-center sm:h-[2.0625rem]">
          <Skeleton className="h-4 w-44 sm:h-5" />
        </span>
        <span className="flex h-11 items-center sm:h-[1.2375rem]">
          <Skeleton className="h-2.5 w-52" />
        </span>
      </div>
      <div aria-hidden="true" className="grid w-full grid-cols-2 border border-line-strong text-center text-[0.78rem] text-faint sm:w-auto">
        <span className="inline-flex min-h-11 items-center justify-center px-3">free report</span>
        <span className="inline-flex min-h-11 items-center justify-center px-3">AI report ✦</span>
      </div>
    </div>
  );
}

export function ReportSkeleton() {
  return (
    <div className="relative">
      <div aria-hidden="true" className="hero-backdrop bottom-auto h-[560px] [mask-image:linear-gradient(#000_55%,transparent)]" />
      <SkeletonRegion label="Loading the report…" className="wrap relative py-8 sm:py-12">
        <ReportHeaderSkeleton />
        <ReportBodySkeleton />
      </SkeletonRegion>
    </div>
  );
}
