import Link from "next/link";
import { GITHUB_REPO_URL } from "@/lib/site";
import { CatFace } from "./cat-face";

export function Footer() {
  return (
    <footer className="mt-auto border-t border-line py-10 text-[0.74rem] text-faint">
      <div className="wrap grid gap-8 sm:grid-cols-[1fr_auto]">
        <div className="space-y-2">
          <p className="flex items-center gap-2 text-muted">
            <CatFace /> procedure over persuasion.
          </p>
          <p className="max-w-md font-sans text-[0.8rem]">
            Holt only reads public GitHub data. It never posts, comments, or opens pull requests for you.
          </p>
        </div>
        <nav aria-label="Footer" className="grid grid-cols-2 gap-x-8 gap-y-1 sm:text-right">
          <Link href="/find" className="py-1 hover:text-ink">find a project</Link>
          <Link href="/hacktoberfest" className="py-1 hover:text-ink">hacktoberfest</Link>
          <Link href="/how-it-works" className="py-1 hover:text-ink">how it works</Link>
          <Link href="/pricing" className="py-1 hover:text-ink">pricing</Link>
          <a href={`${GITHUB_REPO_URL}/blob/main/USAGE.md`} className="py-1 hover:text-ink">the CLI</a>
          <a href={GITHUB_REPO_URL} className="py-1 hover:text-ink">holt-oss / 2026</a>
          <span className="py-1">Apache-2.0</span>
        </nav>
      </div>
    </footer>
  );
}
