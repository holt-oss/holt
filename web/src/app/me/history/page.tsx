import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { CatFace } from "@/components/cat-face";
import { ErrorPanel } from "@/components/error-panel";
import { VerdictPill } from "@/components/report/verdict-pill";
import { history } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { currentUser } from "@/lib/session";
import { PageHead } from "@/components/page-head";

export const metadata: Metadata = { title: "Your history", robots: { index: false } };

export default async function HistoryPage() {
  const user = await currentUser();
  if (!user) redirect("/signin?callbackUrl=/me/history");
  const r = await history(user.id);

  return (
    <>
    <PageHead narrow>
      <p className="rail mb-4 flex gap-2"><strong className="m-0">history</strong><span>{user.name || user.email}</span></p>
      <h1 className="display text-[clamp(2rem,6vw,3rem)]">Repos you&apos;ve checked</h1>
    </PageHead>
    <div className="wrap max-w-3xl py-10 sm:py-12">
      <div>
        {!r.ok ? (
          <ErrorPanel error={r.error} retryHref="/me/history" />
        ) : r.data.items.length === 0 ? (
          <div className="border border-dashed border-line-strong p-8 text-center">
            <CatFace mood="startled" className="text-[1.6rem]" />
            <p className="mt-4 font-sans text-muted">Nothing yet. Reports you run while signed in show up here.</p>
            <Link href="/" className="bracket-link mt-6">[ check a repo → ]</Link>
          </div>
        ) : (
          <ul className="border border-line-strong bg-panel px-3 shadow-soft sm:px-4">
            {r.data.items.map((h) => (
              <li key={h.job_id} className="border-b border-line last:border-b-0">
                <Link
                  href={`/${h.repo}${h.mode === "ai" ? "?mode=ai" : ""}`}
                  className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-2 px-1 py-4 transition-colors hover:bg-panel-2 sm:grid-cols-[1fr_auto_auto]"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-semibold">{h.repo}</span>
                    <span className="text-[0.75rem] text-faint">
                      {h.mode === "ai" ? "AI report" : "free report"} · <time dateTime={h.created_at}>{timeAgo(h.created_at)}</time>
                    </span>
                  </span>
                  {h.verdict ? (
                    <VerdictPill verdict={h.verdict} className="justify-self-end" />
                  ) : (
                    <span className={`justify-self-end text-[0.75rem] ${h.status === "error" ? "text-orange" : "text-faint"}`}>
                      {h.status === "error" ? "didn't finish" : "still running"}
                    </span>
                  )}
                  <span aria-hidden="true" className="hidden text-faint sm:inline">→</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
    </>
  );
}
