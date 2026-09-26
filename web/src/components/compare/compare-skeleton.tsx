"use client";
// /compare while it loads: one column per repo in the URL, at the final widths.
import { useSearchParams } from "next/navigation";
import { Skeleton } from "../skeleton";

export function CompareColumnSkeleton() {
  return (
    <li aria-hidden="true" className="flex min-w-0 flex-col border border-line-strong bg-panel shadow-soft">
      <div className="flex items-center gap-3 border-b border-line p-4">
        <span className="size-7 rounded border border-line-strong bg-panel-2" />
        <span className="flex min-h-11 flex-1 items-center">
          <Skeleton className="h-3.5 w-32" />
        </span>
        <span className="size-11" />
      </div>
      <div className="p-4">
        <Skeleton className="h-4 w-12" />
        <Skeleton className="mt-3 h-6 w-4/5" />
      </div>
      <div className="divide-y divide-line">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex h-[3.1rem] items-center justify-between gap-3 px-4">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="h-3 w-14" />
          </div>
        ))}
      </div>
    </li>
  );
}

/** Reads ?repos= so the skeleton has as many columns as the page will. */
export function CompareGridSkeleton({ fallback = 2 }: { fallback?: number }) {
  const sp = useSearchParams();
  const n = Math.min(4, (sp.get("repos") ?? "").split(",").filter(Boolean).length + (sp.get("add") ? 1 : 0)) || fallback;
  return <CompareColumns n={n} />;
}

export function CompareColumns({ n }: { n: number }) {
  return (
    <ul className={`grid gap-4 sm:grid-cols-2 ${n >= 3 ? "lg:grid-cols-3" : ""} ${n === 4 ? "xl:grid-cols-4" : ""}`}>
      {Array.from({ length: n }, (_, i) => (
        <CompareColumnSkeleton key={i} />
      ))}
    </ul>
  );
}
