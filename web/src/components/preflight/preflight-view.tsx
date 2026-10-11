"use client";

// The /preflight page body: the paste box, the check's progress, and the
// results as a checklist. The server decides everything that matters (whether
// a check is allowed, what it costs, every verdict); this only shows it.
import Link from "next/link";
import { startTransition, useCallback, useEffect, useRef, useState } from "react";
import { timeAgo } from "@/lib/format";
import {
  checkOffer, codeSpans, countsLine, isGitHubLink, linkLabel, parsePrLink, preflightHref, sizeLine, VERDICT_ORDER, VERDICT_WORDS,
} from "@/lib/preflight";
import { EXAMPLE_PREFLIGHT } from "@/lib/preflight-example";
import type { ApiError, Preflight, PreflightCheck, PreflightState, PreflightVerdict } from "@/lib/types";

type Query = { pr: string | null; repo: string | null; branch: string | null; base: string | null };

type Run =
  | { phase: "idle" }
  | { phase: "starting" }
  | { phase: "running"; stage: string; progress: number }
  | { phase: "error"; error: ApiError };

const LOST: ApiError = { code: "upstream", message: "We lost the connection mid-check. It may still finish, so reload in a minute." };
const FAILED: ApiError = { code: "upstream", message: "Something broke on our side. Try again in a minute." };

export function PreflightView({ initial, query, signedIn, badQuery }: { initial: PreflightState; query: Query; signedIn: boolean; badQuery: ApiError | null }) {
  const [s, setS] = useState(initial);
  const [mode, setMode] = useState<"pr" | "branch">(query.branch ? "branch" : "pr");
  const [pr, setPr] = useState(query.pr ?? "");
  const [repo, setRepo] = useState(query.repo ?? "");
  const [branch, setBranch] = useState(query.branch ?? "");
  const [base, setBase] = useState(query.base ?? "");
  const [summary, setSummary] = useState(false);
  const [inputError, setInputError] = useState(badQuery?.message ?? "");
  const [result, setResult] = useState<Preflight | null>(initial.result);
  const [run, setRun] = useState<Run>(initial.job ? { phase: "running", stage: initial.job.stage, progress: initial.job.progress } : { phase: "idle" });
  const es = useRef<EventSource | null>(null);

  const target = mode === "pr" ? { pr: pr.trim() } : { repo: repo.trim(), branch: branch.trim(), base: base.trim() };
  const href = preflightHref(target);

  const refresh = useCallback(async (to: string) => {
    const body = await fetch(`/api${to}`)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
    if (body) setS(body);
  }, []);

  const listen = useCallback(
    (jobId: string, to: string) => {
      es.current?.close();
      const src = new EventSource(`/api/preflight-jobs/${encodeURIComponent(jobId)}/events`);
      es.current = src;
      src.addEventListener("stage", (e) => {
        const d = JSON.parse((e as MessageEvent).data);
        setRun({ phase: "running", stage: d.stage, progress: d.progress ?? 0 });
      });
      src.addEventListener("done", (e) => {
        src.close();
        const p = JSON.parse((e as MessageEvent).data).preflight as Preflight;
        startTransition(() => {
          setResult(p);
          setRun({ phase: "idle" });
        });
        void refresh(to); // what the next check costs may have changed
      });
      src.addEventListener("error", (e) => {
        const data = (e as MessageEvent).data;
        src.close();
        let error = LOST;
        if (data) {
          try {
            error = JSON.parse(data).error ?? LOST;
          } catch {}
        }
        setRun({ phase: "error", error });
        void refresh(to);
      });
    },
    [refresh],
  );

  useEffect(() => {
    if (initial.job) listen(initial.job.job_id, preflightHref(query));
    return () => es.current?.close();
    // Only once, for a check still running when the page loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const check = useCallback(async () => {
    if (mode === "pr" && !parsePrLink(pr)) {
      setInputError("That doesn't look like a PR link. Try one like https://github.com/owner/repo/pull/123.");
      return;
    }
    if (mode === "branch" && !(repo.trim() && branch.trim())) {
      setInputError("Fill in the repo and your branch.");
      return;
    }
    setInputError("");
    setRun({ phase: "starting" });
    const body = mode === "pr" ? { pr_url: pr.trim(), summary } : { repo: repo.trim(), branch: branch.trim(), base: base.trim() || undefined, summary };
    let res: Response;
    try {
      res = await fetch("/api/preflight", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch {
      setRun({ phase: "error", error: LOST });
      return;
    }
    const out = await res.json().catch(() => null);
    if (!res.ok) {
      if (out?.error?.code === "invalid_request" || out?.error?.code === "invalid_repo") {
        setInputError(out.error.message);
        setRun({ phase: "idle" });
      } else setRun({ phase: "error", error: out?.error ?? FAILED });
      return;
    }
    // The address now names this check, so a reload or a shared link finds it.
    window.history.replaceState(null, "", href);
    if (result && preflightHref(query) !== href) setResult(null);
    setRun({ phase: "running", stage: "Getting in line", progress: 0.02 });
    listen(out.job_id, href);
  }, [mode, pr, repo, branch, base, summary, href, listen, result, query]);

  const busy = run.phase === "starting" || run.phase === "running";
  const offer = checkOffer(signedIn ? s.access : null, s.on_sale);

  return (
    <div className="space-y-10">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (offer.kind === "can-check" && !busy) void check();
        }}
        className="border border-line-strong bg-panel p-5 shadow-card sm:p-7"
        data-preflight-form
      >
        <div role="tablist" aria-label="What to check" className="flex gap-4 text-[0.87rem]">
          {(["pr", "branch"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={mode === m}
              onClick={() => {
                setMode(m);
                setInputError("");
              }}
              className={`min-h-11 border-b-2 pb-1 sm:min-h-0 ${mode === m ? "border-blue text-ink" : "border-transparent text-faint hover:text-ink"}`}
            >
              {m === "pr" ? "a pull request" : "a branch, before opening one"}
            </button>
          ))}
        </div>

        {mode === "pr" ? (
          <div className="mt-4">
            <label htmlFor="pf-pr" className="text-[0.8rem] uppercase tracking-[0.08em] text-faint">Pull request link</label>
            <input
              id="pf-pr"
              value={pr}
              onChange={(e) => {
                setPr(e.target.value);
                if (inputError) setInputError("");
              }}
              placeholder={query.repo ? `https://github.com/${query.repo}/pull/123` : "https://github.com/owner/repo/pull/123"}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              enterKeyHint="go"
              aria-invalid={Boolean(inputError)}
              aria-describedby={inputError ? "pf-error" : undefined}
              className="mt-1.5 h-12 w-full min-w-0 border border-line-strong bg-transparent px-3 text-ink outline-none placeholder:text-faint focus:border-blue"
            />
          </div>
        ) : (
          <div className="mt-4 grid gap-3 sm:grid-cols-[1.2fr_1fr_0.8fr]">
            <Field id="pf-repo" label="Repository" value={repo} onChange={setRepo} placeholder="owner/repo" onEdit={() => setInputError("")} />
            <Field id="pf-branch" label="Your branch" value={branch} onChange={setBranch} placeholder="you:my-fix" onEdit={() => setInputError("")} />
            <Field id="pf-base" label="Compare with" value={base} onChange={setBase} placeholder="default branch" onEdit={() => setInputError("")} />
            <p className="font-sans text-[0.87rem] text-faint sm:col-span-3">
              A branch in your fork is <code className="bg-panel-2 px-1">your-name:branch</code>. The fork must be public.
            </p>
          </div>
        )}

        {inputError && (
          <p id="pf-error" role="alert" className="mt-3 font-sans text-[0.9rem] text-orange" data-preflight-input-error>
            {inputError}
          </p>
        )}

        <label className="mt-4 flex min-h-11 cursor-pointer items-start gap-2 font-sans text-[0.9rem] text-muted">
          <input type="checkbox" checked={summary} onChange={(e) => setSummary(e.target.checked)} className="mt-1 accent-[var(--color-blue)]" />
          <span>Add a short AI-written summary, checked against the results (same price)</span>
        </label>

        <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2" data-preflight-offer={offer.kind}>
          {offer.kind === "sign-in" ? (
            <>
              <Link href={`/signin?callbackUrl=${encodeURIComponent(href)}`} prefetch={false} className="btn-primary bg-blue">
                sign in to check <span aria-hidden="true">→</span>
              </Link>
              <span className="font-sans text-[0.89rem] text-faint">
                {s.on_sale ? "Pre-flight checks are a paid feature." : "Pre-flight checks are a paid feature and aren't on sale yet."} The example below is free.
              </span>
            </>
          ) : (
            <>
              <button type="submit" disabled={offer.kind !== "can-check" || busy} className="btn-primary bg-blue disabled:cursor-not-allowed disabled:opacity-50" data-preflight-check>
                {busy ? "checking…" : result ? "check again" : "check it"} <span aria-hidden="true">→</span>
              </button>
              <span className={`font-sans text-[0.89rem] ${offer.kind === "can-check" ? "text-muted" : "text-orange"}`}>{offer.note}</span>
              {offer.kind === "blocked" && offer.buy && (
                <Link href="/pricing" className="bracket-link">[ see plans → ]</Link>
              )}
            </>
          )}
        </div>
      </form>

      {busy && <Checking stage={run.phase === "running" ? run.stage : "Starting"} progress={run.phase === "running" ? run.progress : 0.01} />}

      {run.phase === "error" && (
        <div role="alert" className="border border-orange/60 bg-panel p-5 sm:p-6" data-preflight-error>
          <p className="text-[0.8rem] uppercase tracking-[0.08em] text-orange">The check didn&apos;t finish</p>
          <p className="mt-2 font-sans text-ink">{run.error.message}</p>
        </div>
      )}

      {result && !busy ? (
        <ResultView p={result} />
      ) : (
        !busy && <Explainer />
      )}
    </div>
  );
}

function Field({ id, label, value, onChange, placeholder, onEdit }: { id: string; label: string; value: string; onChange: (v: string) => void; placeholder: string; onEdit: () => void }) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="text-[0.8rem] uppercase tracking-[0.08em] text-faint">{label}</label>
      <input
        id={id}
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          onEdit();
        }}
        placeholder={placeholder}
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        className="mt-1.5 h-12 w-full min-w-0 border border-line-strong bg-transparent px-3 text-ink outline-none placeholder:text-faint focus:border-blue"
      />
    </div>
  );
}

function Checking({ stage, progress }: { stage: string; progress: number }) {
  const pct = Math.round(Math.min(1, Math.max(0.03, progress)) * 100);
  return (
    <div aria-live="polite" aria-busy="true" className="border border-line-strong bg-panel p-5 sm:p-6" data-preflight-checking>
      <p className="font-sans text-ink">{stage}…</p>
      <div className="mt-3 h-1.5 bg-panel-2" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Progress">
        <div className="h-full bg-blue transition-[width] duration-500 ease-out" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-3 font-sans text-[0.89rem] text-faint">
        Usually a few seconds. The first check on a repository can take a couple of minutes while Holt reads its history. You can leave this page and come back.
      </p>
    </div>
  );
}

// --- the result --------------------------------------------------------------------------

const MARK: Record<PreflightVerdict, { sym: string; text: string; border: string }> = {
  worth_fixing: { sym: "!", text: "text-orange", border: "border-orange" },
  unknown: { sym: "?", text: "text-amber", border: "border-amber" },
  ok: { sym: "✓", text: "text-green", border: "border-green" },
};

function Text({ text }: { text: string }) {
  return (
    <>
      {codeSpans(text).map(([piece, code], i) =>
        code ? (
          <code key={i} className="bg-panel-2 px-1 text-[0.9em] [overflow-wrap:anywhere]">
            {piece}
          </code>
        ) : (
          <span key={i}>{piece}</span>
        ),
      )}
    </>
  );
}

/** A GitHub link, or plain text in the example (its repository is made up). */
function GH({ url, children, example, className = "text-link" }: { url: string; children: React.ReactNode; example?: boolean; className?: string }) {
  if (example || !isGitHubLink(url)) return <span>{children}</span>;
  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
    </a>
  );
}

export function ResultView({ p, example = false }: { p: Preflight; example?: boolean }) {
  const t = p.target;
  const checks = [...p.checks].sort((a, b) => VERDICT_ORDER.indexOf(a.verdict) - VERDICT_ORDER.indexOf(b.verdict));
  const size = sizeLine(t);
  const span = p.window_days ? (p.window_days === 365 ? "the last 12 months" : `the last ${p.window_days} days`) : "recent months";
  return (
    <section aria-labelledby={example ? "pf-example" : "pf-result"} className="space-y-7" data-preflight-result={example ? "example" : "live"}>
      <div className="border border-line-strong bg-panel p-5 shadow-card sm:p-7">
        <p className="text-[0.8rem] uppercase tracking-[0.08em] text-faint">
          {t.kind === "branch" ? "branch" : "pull request"} · {p.repo}
        </p>
        <h2 id={example ? "pf-example" : "pf-result"} className="mt-2 text-[1.2rem] font-semibold leading-snug tracking-tight [overflow-wrap:anywhere] sm:text-[1.4rem]">
          <GH url={t.url} example={example} className="hover:text-blue">
            {t.number != null && <span className="text-muted">#{t.number} </span>}
            {t.title ? <Text text={t.title} /> : `${t.head ?? "Your branch"} compared with ${t.base ?? "the default branch"}`}
          </GH>
        </h2>
        <p className="mt-2 font-sans text-[0.9rem] text-muted">
          {t.author && <>by {t.author}{t.outside === true ? ", from outside the project" : t.outside === false ? ", who has a role in the project" : ""}</>}
          {t.author && size && " · "}
          {size}
          {t.draft && " · draft"}
        </p>
        {t.state && t.state !== "open" && (
          <p className="mt-2 font-sans text-[0.9rem] text-orange">This pull request is already {t.state}. The checks still show how it compares.</p>
        )}
        <p className="mt-5 text-[1.05rem] font-medium text-ink sm:text-[1.15rem]" data-preflight-counts>
          {p.checks.length ? countsLine(p.counts) : "No checks apply"}
        </p>
        {p.note && <p className="mt-3 border border-dashed border-line-strong px-3 py-2 font-sans text-[0.9rem] text-muted">{p.note}</p>}
        {p.archived && <p className="mt-3 font-sans text-[0.9rem] text-orange">This repo is archived. It doesn&apos;t take PRs any more.</p>}
        {p.free_recheck && <p className="mt-3 font-sans text-[0.89rem] text-muted">Same commit as your last check, so this one was free.</p>}
      </div>

      {p.summary && p.summary.sentences.length > 0 && (
        <div className="border-l-2 border-blue pl-5" data-preflight-summary>
          <p className="text-[0.8rem] uppercase tracking-[0.08em] text-blue">Summary</p>
          {p.summary.sentences.map((x, i) => (
            <p key={i} className="mt-2 font-sans text-[1rem] leading-relaxed text-ink">
              <Text text={x.text} />
            </p>
          ))}
          <p className="mt-2 text-[0.8rem] text-faint">Written by AI from the checks below, and checked against them. It doesn&apos;t predict whether this will be merged.</p>
        </div>
      )}

      {checks.length === 0 ? (
        <p className="border border-dashed border-line-strong p-4 font-sans text-muted" data-preflight-empty>
          None of Holt&apos;s checks apply to this repository&apos;s pull requests, so there&apos;s nothing to compare yet.
        </p>
      ) : (
        <ul className="space-y-3" data-preflight-checks>
          {checks.map((c) => (
            <CheckRow key={c.id} c={c} example={example} />
          ))}
        </ul>
      )}

      {p.similar && (
        <div className="border border-line-strong bg-panel p-5 sm:p-6" data-preflight-similar>
          <p className="text-[0.8rem] uppercase tracking-[0.08em] text-faint">The closest merged PR</p>
          <p className="mt-2 font-sans text-[1rem] font-medium text-ink [overflow-wrap:anywhere]">
            <GH url={p.similar.url} example={example}>
              {p.similar.number != null && <>#{p.similar.number} </>}
              <Text text={p.similar.title} />
            </GH>
          </p>
          <p className="mt-1 font-sans text-[0.89rem] text-muted">
            {p.similar.author && <>by {p.similar.author}{p.similar.outside ? ", from outside the project" : ""}</>}
            {p.similar.lines != null && <> · {p.similar.lines} lines</>}
            {p.similar.files != null && <> · {p.similar.files} {p.similar.files === 1 ? "file" : "files"}</>}
            {p.similar.touched_tests === true && <> · changed tests</>}
          </p>
          {p.similar.why && (
            <p className="mt-2 font-sans text-[0.9rem] text-muted">
              <Text text={p.similar.why} /> Reading it is a good way to see what this project asks for.
            </p>
          )}
        </div>
      )}

      <p className="border-t border-dashed border-line pt-4 text-[0.8rem] leading-relaxed text-faint">
        {example ? "Example, made up to show the layout. " : <>Checked <time dateTime={p.checked_at} suppressHydrationWarning>{timeAgo(p.checked_at)}</time>, </>}
        compared with pull requests merged in {span}. Each verdict comes from fixed rules, not an AI.
      </p>
    </section>
  );
}

function CheckRow({ c, example }: { c: PreflightCheck; example: boolean }) {
  const m = MARK[c.verdict];
  const links = c.links.filter(isGitHubLink).slice(0, 5);
  return (
    <li className={`border-l-2 ${m.border} bg-panel p-4 sm:p-5`} data-check={c.id} data-verdict={c.verdict}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="flex items-baseline gap-2.5 font-medium text-ink">
          <span aria-hidden="true" className={`w-3 text-center font-semibold ${m.text}`}>{m.sym}</span>
          {c.title}
        </p>
        <span className={`text-[0.8rem] uppercase tracking-[0.08em] ${m.text}`}>{VERDICT_WORDS[c.verdict]}</span>
      </div>
      <p className="mt-1.5 pl-[1.4rem] font-sans text-[0.95rem] leading-relaxed text-muted">
        <Text text={c.statement} />
      </p>
      {c.quote && (
        <blockquote className="ml-[1.4rem] mt-2 border-l border-line-strong pl-3 font-sans text-[0.9rem] text-ink">
          &ldquo;<Text text={c.quote.text} />&rdquo;
          <span className="mt-0.5 block text-[0.82rem] text-faint">
            {c.quote.url ? <GH url={c.quote.url} example={example}>{c.quote.path ?? "the contributing guide"}</GH> : (c.quote.path ?? "the contributing guide")}
          </span>
        </blockquote>
      )}
      {links.length > 0 && (
        <p className="mt-2 flex flex-wrap gap-x-2 pl-[1.4rem] text-[0.85rem] text-faint">
          <span>merged examples:</span>
          {links.map((u) => (
            <GH key={u} url={u} example={example}>{linkLabel(u)}</GH>
          ))}
        </p>
      )}
    </li>
  );
}

// --- before any check --------------------------------------------------------------------

const WHAT: [string, string][] = [
  ["Automated checks", "Did CI pass, and did the checks that run on every merge run on yours?"],
  ["Tests", "Does it change tests when merged PRs here usually do?"],
  ["Size", "Is it bigger than most of what gets merged?"],
  ["Template and linked issue", "Did you keep the PR template, and link an issue if that's expected?"],
  ["CLA, sign-off, changelog", "Only when the project asks for them."],
];

function Explainer() {
  return (
    <div className="space-y-6" data-preflight-explainer>
      <div>
        <h2 className="text-[1.1rem] font-semibold tracking-tight">What it checks</h2>
        <ul className="mt-3 space-y-2 font-sans text-[0.95rem]">
          {WHAT.map(([k, v]) => (
            <li key={k} className="flex gap-3">
              <span aria-hidden="true" className="text-blue">→</span>
              <span>
                <span className="text-ink">{k}.</span> <span className="text-muted">{v}</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 font-sans text-[0.9rem] text-faint">
          Each point says looks fine, worth fixing or can&apos;t tell yet, and shows the merged pull requests it compares with. There&apos;s no overall score.
        </p>
      </div>
      <div className="border border-dashed border-line-strong p-4 sm:p-6">
        <p className="mb-4 text-[0.8rem] uppercase tracking-[0.08em] text-blue">Example · a made-up PR</p>
        <ResultView p={EXAMPLE_PREFLIGHT} example />
      </div>
    </div>
  );
}
