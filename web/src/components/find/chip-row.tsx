"use client";
// Hacktoberfest's language chips: on a phone they are one scrolling row
// (globals.css), and the chosen chip can start past its right edge. This
// brings it into view by moving the row only, never the page.
import { useEffect, useRef } from "react";

export function ChipRow({ current, className, children }: { current: string; className?: string; children: React.ReactNode }) {
  const row = useRef<HTMLUListElement>(null);
  useEffect(() => {
    const ul = row.current;
    const on = ul?.querySelector<HTMLElement>("[aria-current=page]");
    if (!ul || !on || ul.scrollWidth <= ul.clientWidth) return;
    const box = ul.getBoundingClientRect();
    const chip = on.getBoundingClientRect();
    // 24px on the right is the row's fade. A chip already in full view (one just tapped) stays put.
    if (chip.left < box.left || chip.right > box.right - 24) ul.scrollLeft += chip.left - box.left - 12;
  }, [current]);
  return <ul ref={row} className={className}>{children}</ul>;
}
