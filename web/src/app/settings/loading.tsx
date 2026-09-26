import { LoadingTransition } from "@/components/motion/page-transition";
import { PageHeadSkeleton } from "@/components/page-head-skeleton";
import { Skeleton, SkeletonRegion, SkeletonText } from "@/components/skeleton";

export default function Loading() {
  return (
    <LoadingTransition>
      <SkeletonRegion>
        <PageHeadSkeleton narrow headline={1} lead={0} />
        <div className="wrap max-w-3xl pb-14 pt-2 sm:pb-16">
          <div className="mt-8 grid gap-px border border-line bg-line shadow-soft sm:grid-cols-2">
            {[0, 1].map((i) => (
              <div key={i} className="bg-panel p-5">
                <Skeleton className="h-2.5 w-24" />
                <Skeleton className="mt-3 h-6 w-28" />
                <Skeleton className="mt-3 h-2.5 w-20" />
              </div>
            ))}
          </div>
          <div className="mt-10 border border-line-strong bg-panel p-5 shadow-soft sm:p-8">
            <Skeleton className="h-6 w-56" />
            <SkeletonText lines={3} lineHeight="1.6rem" bar="0.85rem" className="mt-2" />
            <Skeleton className="mb-2 mt-6 h-3 w-20" />
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
            <Skeleton className="mb-2 mt-5 h-3 w-16" />
            <Skeleton className="h-12" />
            <Skeleton className="mb-2 mt-5 h-3 w-24" />
            <Skeleton className="h-12" />
            <Skeleton className="mt-5 h-12 w-32" />
          </div>
        </div>
      </SkeletonRegion>
    </LoadingTransition>
  );
}
