import { FindResultsSkeleton } from "@/components/find/find-skeleton";
import { LoadingTransition } from "@/components/motion/page-transition";
import { Skeleton, SkeletonRegion, SkeletonText } from "@/components/skeleton";

export default function Loading() {
  return (
    <LoadingTransition>
      <SkeletonRegion>
        <section className="relative overflow-hidden border-b border-hf-line bg-hf-bg">
          <div className="wrap relative py-10 sm:py-14">
            <div className="mb-6 flex flex-wrap gap-2">
              <Skeleton className="h-7 w-40 rounded-full" />
              <Skeleton className="h-7 w-64 rounded-full" />
            </div>
            <span className="block max-w-4xl">
              {["92%", "80%", "40%"].map((w, i) => (
                <span key={w} className={`flex h-[clamp(2.08rem,6.76vw,3.744rem)] items-center ${i === 2 ? "sm:hidden" : ""}`}>
                  <Skeleton className="h-[62%]" style={{ width: w }} />
                </span>
              ))}
            </span>
            <SkeletonText lines={2} lineHeight="1.785rem" bar="0.9rem" className="mt-5 max-w-2xl" />
            <Skeleton className="mt-3 h-3 w-96 max-w-full" />
            <div className="mt-6 flex flex-wrap gap-x-5 gap-y-3">
              <Skeleton className="h-11 w-80 max-w-full" />
              <Skeleton className="h-11 w-44" />
            </div>
          </div>
        </section>
        <div className="wrap py-10 sm:py-12">
          <div className="flex flex-wrap gap-2">
            {[14, 6, 7, 2, 4, 4, 7, 4, 3].map((w, i) => (
              <Skeleton key={i} className="h-11" style={{ width: `calc(${w}ch + 34px)` }} />
            ))}
          </div>
          <div className="mt-8">
            <FindResultsSkeleton />
          </div>
        </div>
      </SkeletonRegion>
    </LoadingTransition>
  );
}
