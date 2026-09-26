// /find while it loads: the form at its real size, then result cards.
import { Skeleton, SkeletonCard, SkeletonText } from "../skeleton";

export function FindFormSkeleton() {
  return (
    <div aria-hidden="true" className="mt-10 space-y-8 border border-line-strong bg-panel p-5 shadow-soft sm:p-8">
      <div>
        <Skeleton className="mb-3 h-3 w-48" />
        <div className="flex flex-wrap gap-2">
          {[6, 10, 10, 2, 4, 4, 3, 4, 3, 3].map((w, i) => (
            <Skeleton key={i} className="h-11" style={{ width: `calc(${w}ch + 34px)` }} />
          ))}
        </div>
        <Skeleton className="mt-2 h-3 w-40" />
      </div>
      <div>
        <Skeleton className="mb-3 h-3 w-32" />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <Skeleton className="h-6 w-11 shrink-0 rounded-full" />
        <SkeletonText lines={2} lineHeight="1.4rem" bar="0.7rem" last="80%" className="w-72 max-w-full" />
      </div>
      <Skeleton className="h-12 w-full sm:w-72" />
    </div>
  );
}

/** One result: repo line, verdict, stats, and two starter issues. */
export function FindResultSkeleton() {
  return (
    <li aria-hidden="true" className="border border-line-strong bg-panel shadow-soft">
      <div className="flex flex-wrap items-start gap-4 border-b border-line p-5 sm:p-6">
        <span className="size-10 rounded-md border border-line-strong bg-panel-2" />
        <div className="min-w-0 flex-1">
          <span className="flex h-[1.9rem] items-center">
            <Skeleton className="h-4 w-48" />
          </span>
          <SkeletonText lines={1} lineHeight="1.56rem" bar="0.75rem" className="mt-1 w-4/5" />
          <span className="mt-2 flex h-[1.24rem] items-center gap-4">
            <Skeleton className="h-2.5 w-16" />
            <Skeleton className="h-2.5 w-12" />
            <Skeleton className="h-2.5 w-32" />
          </span>
        </div>
        <Skeleton className="hidden h-7 w-36 sm:block" />
      </div>
      <div className="p-5 sm:p-6">
        <Skeleton className="mb-3 h-3 w-28" />
        <ul className="grid gap-3 md:grid-cols-2">
          <SkeletonCard compact />
          <SkeletonCard compact className="hidden md:block" />
        </ul>
        <Skeleton className="mt-4 h-3 w-52" />
      </div>
    </li>
  );
}

export function FindResultsSkeleton({ count = 3 }: { count?: number }) {
  return (
    <ol className="space-y-6">
      {Array.from({ length: count }, (_, i) => (
        <FindResultSkeleton key={i} />
      ))}
    </ol>
  );
}
