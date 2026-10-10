// A compact repo card while a list loads, at the card's real size.
import { Skeleton } from "../skeleton";

export function RepoCardSkeleton({ verdict = true }: { verdict?: boolean }) {
  return (
    <li aria-hidden="true" className="flex flex-col border border-line-strong bg-panel p-4 shadow-soft">
      <div className="flex items-start gap-3">
        <span className="size-8 shrink-0 rounded-md border border-line-strong bg-panel-2" />
        <div className="min-w-0 flex-1">
          <span className="flex h-5 items-center"><Skeleton className="h-3.5 w-40" /></span>
          <span className="mt-0.5 flex h-5 items-center"><Skeleton className="h-2.5 w-full" /></span>
          <span className="flex h-5 items-center"><Skeleton className="h-2.5 w-3/5" /></span>
          <span className="mt-1.5 flex h-5 items-center"><Skeleton className="h-2.5 w-28" /></span>
        </div>
      </div>
      {verdict ? (
        <Skeleton className="mt-3 h-6 w-32" />
      ) : (
        <div className="mt-3">
          <span className="flex h-5 items-center"><Skeleton className="h-2.5 w-44" /></span>
          <Skeleton className="mt-2 h-5 w-24" />
        </div>
      )}
      <span className="mt-3 flex h-5 items-center"><Skeleton className="h-2.5 w-20" /></span>
      <Skeleton className="h-2 w-full" />
      <div className="mt-2.5">
        <span className="flex h-5 items-center"><Skeleton className="h-2.5 w-28" /></span>
        <span className="flex h-5 items-center"><Skeleton className="h-2.5 w-36" /></span>
      </div>
      <div className="mt-3 border-t border-dashed border-line pt-2.5">
        <Skeleton className="h-2.5 w-16" />
        <Skeleton className="mt-2 h-3 w-11/12" />
      </div>
    </li>
  );
}

export function RepoGridSkeleton({ count = 6, verdict = true }: { count?: number; verdict?: boolean }) {
  return (
    <ol className="card-grid">
      {Array.from({ length: count }, (_, i) => (
        <RepoCardSkeleton key={i} verdict={verdict} />
      ))}
    </ol>
  );
}
