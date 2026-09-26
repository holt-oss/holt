import { LoadingTransition } from "@/components/motion/page-transition";
import { PageHeadSkeleton } from "@/components/page-head-skeleton";
import { Skeleton, SkeletonRegion, SkeletonText } from "@/components/skeleton";

export default function Loading() {
  return (
    <LoadingTransition>
      <SkeletonRegion>
        <PageHeadSkeleton />
        <div className="wrap py-10 sm:py-14">
          <ul className="grid gap-4 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <li key={i} className="flex flex-col border border-line-strong bg-panel p-6 shadow-soft">
                <Skeleton className="h-3 w-24" />
                <span className="mt-3 flex h-[2.4rem] items-center gap-3">
                  <Skeleton className="h-full w-16" />
                  <Skeleton className="h-3 w-32" />
                </span>
                <SkeletonText lines={2} lineHeight="1.65rem" bar="0.85rem" className="mt-3" />
                <span className="mt-5 block flex-1 space-y-2">
                  <SkeletonText lines={3} lineHeight="1.5rem" bar="0.75rem" last="75%" />
                </span>
                <Skeleton className="mt-6 h-11 w-full" />
              </li>
            ))}
          </ul>
        </div>
      </SkeletonRegion>
    </LoadingTransition>
  );
}
