import Link from "next/link";
import { GITHUB_REPO_URL } from "@/lib/site";
import { CatFace } from "./cat-face";

export function Footer() {
  return (
    <footer className="mt-auto border-t border-line py-10 text-[0.74rem] text-faint">
      <div className="wrap grid grid-cols-1 gap-8 sm:grid-cols-[1fr_auto]">
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-muted">
            <CatFace /> procedure over persuasion.
          </p>
          <p className="max-w-md font-sans text-[0.8rem]">
            Holt only reads public GitHub data. It never posts, comments, or opens pull requests for you.
          </p>
        </div>
        <nav aria-label="Footer" className="grid grid-cols-2 gap-x-8 gap-y-1 sm:text-right">
          <Link href="/find" className="inline-flex min-h-11 items-center hover:text-ink sm:min-h-0 sm:py-1 sm:justify-end">find a project</Link>
          <Link href="/how-it-works" className="inline-flex min-h-11 items-center hover:text-ink sm:min-h-0 sm:py-1 sm:justify-end">how it works</Link>
          <Link href="/pricing" className="inline-flex min-h-11 items-center hover:text-ink sm:min-h-0 sm:py-1 sm:justify-end">pricing</Link>
          <a href={`${GITHUB_REPO_URL}/blob/main/docs/USAGE.md`} className="inline-flex min-h-11 items-center hover:text-ink sm:min-h-0 sm:py-1 sm:justify-end">the CLI</a>
          <a href={GITHUB_REPO_URL} className="inline-flex min-h-11 items-center hover:text-ink sm:min-h-0 sm:py-1 sm:justify-end">holt-oss / 2026</a>
          <span className="inline-flex min-h-11 items-center sm:min-h-0 sm:py-1 sm:justify-end">Apache-2.0</span>
        </nav>
      </div>
    </footer>
  );
}
