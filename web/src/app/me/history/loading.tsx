import { LoadingTransition } from "@/components/motion/page-transition";
import { PageHeadSkeleton } from "@/components/page-head-skeleton";
import { Skeleton, SkeletonRegion } from "@/components/skeleton";

export default function Loading() {
  return (
    <LoadingTransition>
      <SkeletonRegion>
        <PageHeadSkeleton narrow headline={1} lead={0} />
        <div className="wrap max-w-3xl py-10 sm:py-12">
          <ul className="border border-line-strong bg-panel px-3 shadow-soft sm:px-4">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <li key={i} className="flex items-center gap-4 border-b border-line px-1 py-4 last:border-b-0">
                <span className="min-w-0 flex-1">
                  <Skeleton className="h-4 w-44" />
                  <Skeleton className="mt-2 h-2.5 w-32" />
                </span>
                <Skeleton className="h-7 w-32" />
              </li>
            ))}
          </ul>
        </div>
      </SkeletonRegion>
    </LoadingTransition>
  );
}
