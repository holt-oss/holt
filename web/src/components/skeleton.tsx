// Loading placeholders. One flat block and one CSS sweep (globals.css `.sk`),
// no JavaScript. Per-page skeletons are built from these and live next to the
// component they stand in for, so the two change together.

/** A block. Give it the real element's size: `<Skeleton className="h-4 w-40" />`. */
export function Skeleton({ className = "", style }: { className?: string; style?: React.CSSProperties }) {
  return <span aria-hidden="true" className={`sk block ${className}`} style={style} />;
}

/**
 * Text lines at a real line height: each line is a box `lineHeight` tall with a
 * bar inside, so the block is exactly as tall as the text it replaces.
 */
export function SkeletonText({
  lines = 3,
  lineHeight = "1.65em",
  bar = "0.8em",
  last = "60%",
  className = "",
}: {
  lines?: number;
  lineHeight?: string;
  bar?: string;
  /** Width of the last line. */
  last?: string;
  className?: string;
}) {
  return (
    <span aria-hidden="true" className={`block ${className}`}>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="flex items-center" style={{ height: lineHeight }}>
          <Skeleton className="w-full" style={{ height: bar, width: i === lines - 1 && lines > 1 ? last : undefined }} />
        </span>
      ))}
    </span>
  );
}

/** A starter-issue card: meta line, title, two reasons, next step. */
export function SkeletonCard({ compact = false, className = "" }: { compact?: boolean; className?: string }) {
  return (
    <li aria-hidden="true" className={`border border-line bg-panel p-4 shadow-soft sm:p-5 ${className}`}>
      <span className="flex h-[26px] items-center justify-between gap-3">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-3 w-28" />
      </span>
      <SkeletonText lines={2} lineHeight="1.375rem" bar="0.8rem" last="55%" className="mt-2" />
      {!compact && <SkeletonText lines={2} lineHeight="1.35rem" bar="0.65rem" last="70%" className="mt-2" />}
      <span className="mt-3 flex h-[1.95rem] items-end border-t border-dashed border-line">
        <Skeleton className="h-3 w-3/4" />
      </span>
    </li>
  );
}

/**
 * The wrapper every skeleton sits in: busy for assistive tech, and invisible
 * for its first 300ms (--sk-delay) so fast loads never flash.
 */
export function SkeletonRegion({
  label = "Loading…",
  className = "",
  children,
  as: Tag = "div",
}: {
  label?: string;
  className?: string;
  children: React.ReactNode;
  as?: "div" | "section" | "ul";
}) {
  return (
    <Tag aria-busy="true" className={`sk-region ${className}`} data-skeleton>
      {Tag === "ul" ? <li className="sr-only">{label}</li> : <span className="sr-only">{label}</span>}
      {children}
    </Tag>
  );
}
