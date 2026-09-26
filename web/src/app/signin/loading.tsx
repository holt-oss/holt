import { LoadingTransition } from "@/components/motion/page-transition";
import { Skeleton, SkeletonRegion, SkeletonText } from "@/components/skeleton";

export default function Loading() {
  return (
    <LoadingTransition>
      <SkeletonRegion className="relative overflow-hidden">
        <div aria-hidden="true" className="hero-backdrop" />
        <div className="wrap relative grid min-h-[70dvh] place-items-center py-12">
          <div className="w-full max-w-md border border-line-strong bg-panel p-6 shadow-card sm:p-8">
            <Skeleton className="h-8 w-28" />
            <Skeleton className="mt-6 h-10 w-4/5" />
            <SkeletonText lines={3} lineHeight="1.7rem" bar="0.85rem" className="mt-3" />
            <Skeleton className="mt-8 h-13" />
            <Skeleton className="mt-3 h-13" />
            <SkeletonText lines={2} lineHeight="1.36rem" bar="0.7rem" className="mt-8" />
          </div>
        </div>
      </SkeletonRegion>
    </LoadingTransition>
  );
}
