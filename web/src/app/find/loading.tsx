import { FindFormSkeleton, FindResultsSkeleton } from "@/components/find/find-skeleton";
import { LoadingTransition } from "@/components/motion/page-transition";
import { PageHeadSkeleton } from "@/components/page-head-skeleton";
import { SkeletonRegion } from "@/components/skeleton";

export default function Loading() {
  return (
    <LoadingTransition>
      <SkeletonRegion>
        <PageHeadSkeleton>
          <FindFormSkeleton />
        </PageHeadSkeleton>
        <div className="wrap py-10 sm:py-12">
          <FindResultsSkeleton />
        </div>
      </SkeletonRegion>
    </LoadingTransition>
  );
}
