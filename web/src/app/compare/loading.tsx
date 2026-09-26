import { Suspense } from "react";
import { CompareColumns, CompareGridSkeleton } from "@/components/compare/compare-skeleton";
import { LoadingTransition } from "@/components/motion/page-transition";
import { PageHeadSkeleton } from "@/components/page-head-skeleton";
import { Skeleton, SkeletonRegion } from "@/components/skeleton";

export default function Loading() {
  return (
    <LoadingTransition>
      <SkeletonRegion>
        <PageHeadSkeleton headline={1} lead={1}>
          <Skeleton className="mt-8 h-[3.6rem] max-w-2xl" />
        </PageHeadSkeleton>
        <div className="wrap py-10 sm:py-12">
          <Suspense fallback={<CompareColumns n={2} />}>
            <CompareGridSkeleton />
          </Suspense>
        </div>
      </SkeletonRegion>
    </LoadingTransition>
  );
}
