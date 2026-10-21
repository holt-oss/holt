import Link from "next/link";
import type { Verdict } from "@/lib/types";
import { findHref, findLabel } from "./next-action";

/** The next action in one line: Find, searching this repo's language. */
export function FindLine({ verdict, language }: { verdict: Verdict; language: string | null | undefined }) {
  return (
    <p data-find-line>
      <Link href={findHref(language)} className="text-link tap font-sans text-[1rem]">
        {findLabel(verdict, language)} <span aria-hidden="true">→</span>
      </Link>
    </p>
  );
}
