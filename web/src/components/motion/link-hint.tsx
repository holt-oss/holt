"use client";

import { useLinkStatus } from "next/link";

/**
 * A 2px line that sweeps under a clicked link while its page loads. Always
 * rendered at a fixed size, so it never shifts the layout. For links that
 * don't prefetch (the report tabs). Must sit inside the <Link>.
 */
export function LinkHint() {
  const { pending } = useLinkStatus();
  return <span aria-hidden="true" className={`link-hint ${pending ? "is-pending" : ""}`} />;
}
