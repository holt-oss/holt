// PageHead's shape while a page loads: the rail, a display headline and a
// lead paragraph, at their real line heights.
import { PageHead } from "./page-head";
import { Skeleton, SkeletonText } from "./skeleton";

export function PageHeadSkeleton({
  narrow = false,
  headline = 2,
  lead = 2,
  children,
}: {
  narrow?: boolean;
  /** Headline lines on wide screens; phones get one more. */
  headline?: number;
  /** Lead paragraph lines (0 for none). */
  lead?: number;
  children?: React.ReactNode;
}) {
  return (
    <PageHead narrow={narrow}>
      <span className="mb-4 flex h-[1.188rem] items-center">
        <Skeleton className="h-2.5 w-40" />
      </span>
      <span className="block max-w-3xl">
        {Array.from({ length: headline + 1 }, (_, i) => (
          <span key={i} className={`flex h-[clamp(2.08rem,6.24vw,3.536rem)] items-center ${i === headline ? "sm:hidden" : ""}`}>
            <Skeleton className="h-[62%]" style={{ width: i === headline ? "40%" : i === headline - 1 ? "70%" : "92%" }} />
          </span>
        ))}
      </span>
      {lead > 0 && <SkeletonText lines={lead} lineHeight="1.785rem" bar="0.9rem" className="mt-5 max-w-2xl" />}
      {children}
    </PageHead>
  );
}
