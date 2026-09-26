import { LoadingTransition } from "@/components/motion/page-transition";
import { PageHeadSkeleton } from "@/components/page-head-skeleton";
import { SkeletonRegion, SkeletonText } from "@/components/skeleton";

export default function Loading() {
  return (
    <LoadingTransition>
      <SkeletonRegion>
        <PageHeadSkeleton />
        <div className="wrap py-16">
          <SkeletonText lines={6} lineHeight="1.8rem" bar="0.9rem" className="max-w-[740px]" />
        </div>
      </SkeletonRegion>
    </LoadingTransition>
  );
}
