// Landing "Fig. 01" while the live sample loads: the figure's frame with its
// verdict, three stats, the landing bars and one issue, at their real sizes.
import { Skeleton, SkeletonRegion, SkeletonText } from "./skeleton";

export function SampleReportSkeleton() {
  return (
    <SkeletonRegion label="Loading the example report…">
      <div aria-hidden="true" className="relative m-0 border border-line-strong bg-panel shadow-card">
        <div className="flex min-h-10 items-center justify-between border-b border-line px-4">
          <Skeleton className="h-2.5 w-36" />
          <Skeleton className="h-2.5 w-20" />
        </div>
        <div className="grid gap-8 p-5 sm:p-8 lg:grid-cols-[1.1fr_1fr]">
          <div>
            <div className="flex h-[1.95rem] items-center justify-between">
              <Skeleton className="h-7 w-40" />
              <Skeleton className="h-5 w-16" />
            </div>
            <span className="mt-4 flex h-[clamp(2.08rem,5.2vw,3.33rem)] items-center">
              <Skeleton className="h-[62%] w-4/5" />
            </span>
            <span className="flex h-[clamp(2.08rem,5.2vw,3.33rem)] items-center sm:hidden">
              <Skeleton className="h-[62%] w-2/5" />
            </span>
            <ul className="mt-6 grid gap-px border border-line bg-line sm:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <li key={i} className="bg-panel p-3">
                  <span className="flex h-[1.9rem] items-center">
                    <Skeleton className="h-4 w-16" />
                  </span>
                  <SkeletonText lines={2} lineHeight="1.07rem" bar="0.6rem" last="60%" />
                </li>
              ))}
            </ul>
          </div>
          <div className="space-y-6">
            <div>
              <Skeleton className="mb-3 h-2.5 w-44" />
              <ul className="space-y-3">
                {[0, 1, 2].map((i) => (
                  <li key={i}>
                    <div className="flex h-[1.287rem] items-center justify-between">
                      <Skeleton className="h-2.5 w-20" />
                      <Skeleton className="h-2.5 w-24" />
                    </div>
                    <Skeleton className="mt-1.5 h-2" />
                  </li>
                ))}
              </ul>
            </div>
            <div className="border border-line p-4">
              <Skeleton className="h-2.5 w-40" />
              <SkeletonText lines={1} lineHeight="1.52rem" bar="0.8rem" className="mt-1 w-4/5" />
              <Skeleton className="mt-3 h-2.5 w-3/4" />
            </div>
          </div>
        </div>
        <div className="flex min-h-[3.2rem] items-center justify-between gap-1 border-t border-line px-4">
          <Skeleton className="h-2.5 w-40" />
          <Skeleton className="hidden h-2.5 w-36 sm:block" />
        </div>
      </div>
    </SkeletonRegion>
  );
}
