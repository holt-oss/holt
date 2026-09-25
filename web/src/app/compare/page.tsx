import type { Metadata } from "next";
import { CompareBody, CompareShell } from "@/components/compare/compare-card";
import { CompareLive } from "@/components/compare/compare-live";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getReport } from "@/lib/api";
import { parseRepoInput } from "@/lib/repo";
import { PageHead } from "@/components/page-head";

export const metadata: Metadata = {
  title: "Compare repositories",
  description: "Put a few repositories side by side and see which one will actually review your first pull request.",
};

const MAX = 4;

function parseList(v: string | string[] | undefined): string[] {
  const raw = (Array.isArray(v) ? v.join(",") : v ?? "").split(/[,\s]+/);
  const out: string[] = [];
  for (const r of raw) {
    const ref = parseRepoInput(r);
    const name = ref && `${ref.owner}/${ref.repo}`;
    if (name && !out.some((o) => o.toLowerCase() === name.toLowerCase())) out.push(name);
  }
  return out.slice(0, MAX);
}

export default async function ComparePage({ searchParams }: PageProps<"/compare">) {
  const sp = await searchParams;
  const repos = parseList(sp.repos);
  const extra = parseList(sp.add);
  const all = [...repos, ...extra.filter((e) => !repos.some((r) => r.toLowerCase() === e.toLowerCase()))].slice(0, MAX);
  const href = (list: string[]) => (list.length ? `/compare?repos=${list.join(",")}` : "/compare");
  // Keep the URL shareable: fold ?add= into ?repos=.
  if (sp.add !== undefined) redirect(href(all));
  const reports = await Promise.all(all.map((r) => getReport(r)));

  return (
    <>
    <PageHead>
      <p className="rail mb-4 flex gap-2"><strong className="m-0">compare</strong><span>side by side</span></p>
      <h1 className="display max-w-3xl text-[clamp(2rem,6vw,3.4rem)]">Which one will review your PR?</h1>
      <p className="prose-sans mt-5 max-w-2xl text-[1.05rem]">Add up to {MAX} repositories. Same rules, same numbers, side by side.</p>

      <form action="/compare" method="get" className="mt-8 grid max-w-2xl grid-cols-[1fr_auto] border border-line-strong bg-panel shadow-soft focus-within:border-blue">
        <input type="hidden" name="repos" value={all.join(",")} />
        <label htmlFor="add" className="sr-only">Add a repository</label>
        <input
          id="add"
          name="add"
          placeholder={all.length >= MAX ? "remove one to add another" : "add a repo: owner/name or URL"}
          disabled={all.length >= MAX}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          className="h-14 min-w-0 bg-transparent px-4 text-ink outline-none placeholder:text-faint"
        />
        <button type="submit" disabled={all.length >= MAX} className="btn-primary m-1.5">add</button>
      </form>
    </PageHead>

    <div className="wrap py-10 sm:py-12">
      {all.length === 0 ? (
        <div className="border border-dashed border-line-strong p-8 font-sans text-muted">
          Nothing to compare yet. Try{" "}
          <Link className="text-link font-mono text-[0.9rem]" href="/compare?repos=pallets/flask,pytorch/pytorch,psf/requests">flask vs pytorch vs requests</Link>.
        </div>
      ) : (
        <ul className={`grid gap-4 sm:grid-cols-2 ${all.length >= 3 ? "lg:grid-cols-3" : ""} ${all.length === 4 ? "xl:grid-cols-4" : ""}`}>
          {all.map((repo, i) => {
            const r = reports[i];
            const name = r.ok ? r.data.repo : repo;
            return (
              <CompareShell key={repo} repo={name} removeHref={href(all.filter((x) => x !== repo))}>
                {r.ok ? <CompareBody report={r.data} /> : r.error.code === "not_found" ? <CompareLive repo={repo} /> : (
                  <p className="p-4 font-sans text-[0.88rem] text-orange">{r.error.message}</p>
                )}
              </CompareShell>
            );
          })}
        </ul>
      )}
    </div>
    </>
  );
}
