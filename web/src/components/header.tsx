import Link from "next/link";
import { signOut } from "@/auth";
import { currentUser } from "@/lib/session";
import { GITHUB_REPO_URL } from "@/lib/site";
import { CatFace } from "./cat-face";
import { ThemeToggle } from "./theme-toggle";

const NAV = [
  { href: "/find", label: "find a project" },
  { href: "/compare", label: "compare" },
  { href: "/how-it-works", label: "how it works" },
  { href: "/pricing", label: "pricing" },
];

async function doSignOut() {
  "use server";
  await signOut({ redirectTo: "/" });
}

export async function Header() {
  const user = await currentUser();
  const initial = (user?.name || user?.email || "?").trim().charAt(0).toUpperCase();
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-header">
      <div className="wrap flex min-h-[60px] items-center gap-4">
        <Link href="/" className="mr-auto inline-flex min-h-11 items-center gap-3">
          <CatFace className="text-[1.05rem]" />
          <span className="text-[0.95rem] font-semibold tracking-tight">holt<span className="sr-only"> home</span></span>
        </Link>

        <nav aria-label="Main" className="hidden items-center gap-6 text-[0.78rem] text-muted lg:flex">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className="py-2 transition-colors hover:text-ink">
              {n.label}
            </Link>
          ))}
          <a href={GITHUB_REPO_URL} className="py-2 text-green">
            github <span aria-hidden="true">↗</span>
          </a>
        </nav>

        <div className="flex items-center gap-1">
          <ThemeToggle />
          {user ? (
            <details className="group relative">
              <summary className="grid size-11 cursor-pointer list-none place-items-center [&::-webkit-details-marker]:hidden" aria-label="Your account">
                {user.image ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={user.image} alt="" width={28} height={28} className="size-7 rounded-full border border-line-strong" />
                ) : (
                  <span className="grid size-7 place-items-center rounded-full bg-blue text-[0.75rem] font-bold text-on-accent">{initial}</span>
                )}
              </summary>
              <div className="absolute right-0 top-12 z-50 w-56 border border-line-strong bg-panel p-1 text-[0.82rem] shadow-card">
                <p className="truncate px-3 py-2 text-faint">{user.name || user.email}</p>
                <Link href="/me/history" className="block px-3 py-2.5 hover:bg-panel-2">your history</Link>
                <Link href="/settings" className="block px-3 py-2.5 hover:bg-panel-2">settings &amp; API key</Link>
                <form action={doSignOut}>
                  <button type="submit" className="block w-full px-3 py-2.5 text-left text-muted hover:bg-panel-2">sign out</button>
                </form>
              </div>
            </details>
          ) : (
            <Link href="/signin" className="hidden min-h-11 items-center px-3 text-[0.8rem] text-ink hover:text-blue sm:inline-flex">
              sign in
            </Link>
          )}
          <details className="group relative lg:hidden">
            <summary className="grid size-11 cursor-pointer list-none place-items-center text-muted [&::-webkit-details-marker]:hidden" aria-label="Menu">
              <svg className="size-5 group-open:hidden" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
                <path d="M4 7h16M4 12h16M4 17h16" />
              </svg>
              <svg className="hidden size-5 group-open:block" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </summary>
            <nav aria-label="Mobile" className="absolute right-0 top-12 z-50 w-60 border border-line-strong bg-panel p-1 text-[0.9rem] shadow-card">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href} className="block px-4 py-3 hover:bg-panel-2">{n.label}</Link>
              ))}
              {!user && <Link href="/signin" className="block px-4 py-3 hover:bg-panel-2">sign in</Link>}
              <a href={GITHUB_REPO_URL} className="block px-4 py-3 text-green hover:bg-panel-2">github ↗</a>
            </nav>
          </details>
        </div>
      </div>
    </header>
  );
}
