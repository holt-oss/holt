import type { Metadata } from "next";
import { ErrorPanel } from "@/components/error-panel";
import { FindResults } from "@/components/find/find-results";
import { FindRunner } from "@/components/find/find-runner";
import { find } from "@/lib/api";
import { hacktoberfest } from "@/lib/site";
import { caller } from "@/lib/session";

export const metadata: Metadata = {
  title: "Find your first contribution",
  description: "Pick your languages and how much time you have. Holt finds welcoming projects and specific issues to start with.",
};

const LANGS = ["Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "C++", "Ruby", "PHP", "Nix"];
const TIME = [
  { days: 1, label: "an evening" },
  { days: 3, label: "a weekend" },
  { days: 7, label: "a week" },
  { days: 30, label: "a month" },
];

const list = (v: string | string[] | undefined) => (Array.isArray(v) ? v : v ? v.split(",") : []).map((s) => s.trim()).filter(Boolean);

export default async function FindPage({ searchParams }: PageProps<"/find">) {
  const sp = await searchParams;
  const langs = list(sp.lang).map((l) => l.toLowerCase());
  const days = TIME.some((t) => String(t.days) === sp.days) ? Number(sp.days) : 7;
  const searched = sp.go === "1" || langs.length > 0;
  const hfDefault = Boolean(hacktoberfest());
  const hf = sp.hacktoberfest != null ? sp.hacktoberfest === "1" : searched ? false : hfDefault;

  const result = searched
    ? await find({ languages: langs, topics: [], days, hacktoberfest: hf, limit: 12 }, await caller())
    : null;

  return (
    <div className="wrap py-10 sm:py-14">
      <p className="rail mb-4 flex gap-2"><strong className="m-0">find</strong><span>your first contribution</span></p>
      <h1 className="display max-w-3xl text-[clamp(2rem,6vw,3.4rem)]">
        Tell us what you know. <span className="text-orange">We&apos;ll find where you&apos;re welcome.</span>
      </h1>
      <p className="prose-sans mt-5 max-w-2xl text-[1.05rem]">
        Every project below replies to newcomers and merges their work. Each comes with open issues you could take today.
      </p>

      <form action="/find" method="get" className="mt-10 space-y-8 border border-line-strong bg-panel p-5 sm:p-8">
        <input type="hidden" name="go" value="1" />
        <fieldset>
          <legend className="mb-3 text-[0.78rem] uppercase tracking-[0.08em] text-faint">Languages you can read</legend>
          <div className="flex flex-wrap gap-2">
            {LANGS.map((l) => (
              <label key={l} className="chip min-h-11 cursor-pointer select-none px-4 text-[0.85rem] transition-colors hover:border-blue has-[:checked]:border-blue has-[:checked]:bg-blue has-[:checked]:text-on-accent has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-blue">
                <input type="checkbox" name="lang" value={l.toLowerCase()} defaultChecked={langs.includes(l.toLowerCase())} className="sr-only" />
                {l}
              </label>
            ))}
          </div>
          <p className="mt-2 font-sans text-[0.82rem] text-faint">Pick none to see everything.</p>
        </fieldset>

        <fieldset>
          <legend className="mb-3 text-[0.78rem] uppercase tracking-[0.08em] text-faint">Time you have</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {TIME.map((t) => (
              <label key={t.days} className="flex min-h-12 cursor-pointer items-center justify-center border border-line-strong px-3 text-[0.88rem] transition-colors hover:border-blue has-[:checked]:border-green has-[:checked]:bg-green/10 has-[:checked]:text-green has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-blue">
                <input type="radio" name="days" value={t.days} defaultChecked={days === t.days} className="sr-only" />
                {t.label}
              </label>
            ))}
          </div>
        </fieldset>

        <label className="flex cursor-pointer items-center gap-3 text-[0.9rem]">
          <input type="checkbox" name="hacktoberfest" value="1" defaultChecked={hf} className="peer sr-only" />
          <span aria-hidden="true" className="relative h-6 w-11 shrink-0 rounded-full border border-line-strong bg-panel-2 transition-colors after:absolute after:left-0.5 after:top-0.5 after:size-4.5 after:rounded-full after:bg-faint after:transition-transform peer-checked:border-orange peer-checked:bg-orange/20 peer-checked:after:translate-x-5 peer-checked:after:bg-orange peer-focus-visible:outline-2 peer-focus-visible:outline-blue" />
          <span>
            Only Hacktoberfest projects
            <span className="block font-sans text-[0.8rem] text-faint">Repos taking part, so your pull requests count.</span>
          </span>
        </label>

        <button type="submit" className="btn-primary w-full sm:w-auto">
          find my first contribution <span aria-hidden="true">→</span>
        </button>
      </form>

      {result && (
        <section aria-label="Results" className="mt-12">
          {!result.ok ? (
            <ErrorPanel error={result.error} retryHref="/find" />
          ) : result.data.status === "queued" ? (
            <FindRunner jobId={result.data.job_id} days={days} />
          ) : (
            <>
              <p className="mb-5 text-[0.8rem] text-faint">
                {result.data.results.length} welcoming project{result.data.results.length === 1 ? "" : "s"}, best starter issues first
              </p>
              <FindResults results={result.data.results} days={days} />
            </>
          )}
        </section>
      )}
    </div>
  );
}
