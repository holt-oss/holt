"use client";
// The rest of a list behind "[ show N more ]". Open, the toggle moves to the
// end of what it opened ("[ show fewer ]"), so it's where you finish reading;
// closing it brings the toggle back into view instead of leaving you far below.
import { useId, useRef, useState } from "react";

export function ShowMore({ count, children }: { count: number; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const id = useId();

  function flip() {
    setOpen(!open);
    if (open) requestAnimationFrame(() => toggle.current?.scrollIntoView({ block: "nearest" }));
  }

  return (
    <>
      <div id={id} hidden={!open}>{children}</div>
      <button
        ref={toggle}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={flip}
        className="flex min-h-11 cursor-pointer items-center gap-2 py-3 text-[0.88rem] text-ink hover:text-blue"
      >
        {open ? "[ show fewer ]" : `[ show ${count} more ]`}
      </button>
    </>
  );
}
