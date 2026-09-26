import { LoadingTransition } from "@/components/motion/page-transition";
import { Skeleton, SkeletonRegion, SkeletonText } from "@/components/skeleton";

// The landing hero's shape. Rarely seen: the page has nothing to wait for but
// the session, and skeletons stay invisible for their first 100ms.
export default function Loading() {
  return (
    <LoadingTransition>
      <SkeletonRegion as="section" className="relative overflow-hidden border-b border-line pb-12 pt-5 md:pb-16 md:pt-7">
        <div aria-hidden="true" className="hero-backdrop" />
        <div className="wrap grid grid-cols-1 gap-6 md:grid-cols-[148px_minmax(0,1fr)] md:gap-10">
          <div className="hidden pt-2 md:block">
            <Skeleton className="h-2.5 w-6" />
            <Skeleton className="mt-2 h-2.5 w-20" />
          </div>
          <div className="relative max-w-[860px]">
            <span className="mb-4 flex h-[2rem] items-center gap-4">
              <Skeleton className="h-7 w-44" />
              <Skeleton className="h-3 w-56" />
            </span>
            <span className="mb-5 block">
              {["70%", "58%", "96%"].map((w) => (
                <span key={w} className="flex h-[clamp(2.08rem,9.26vw,3.276rem)] items-center">
                  <Skeleton className="h-[62%]" style={{ width: w }} />
                </span>
              ))}
            </span>
            <SkeletonText lines={3} lineHeight="1.8rem" bar="0.9rem" className="mb-6 max-w-[680px]" />
            <Skeleton className="h-16 max-w-[760px]" />
            <span className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-12 w-72" />
            </span>
          </div>
        </div>
      </SkeletonRegion>
    </LoadingTransition>
  );
}
