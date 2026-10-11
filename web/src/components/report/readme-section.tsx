"use client";

// The repository's README on its report, with the contributing guide in a
// second tab when there is one: the top of each as a document card (tabs, then the text), shown as a preview that
// fades out and opens in full with one click, so a newcomer can get the feel of
// the project without leaving. The text is untrusted: lib/readme-md.ts turns it
// into plain blocks (no raw HTML, only http(s) links, images only from GitHub's
// hosts) and this draws them in the page's own style.
import { BookOpen, Check, ChevronDown, Copy, ExternalLink, Users } from "lucide-react";
import { Fragment, useEffect, useId, useMemo, useState } from "react";
import { contributingFileUrl } from "@/lib/contributing";
import { badgeRow, parseReadme, type Block, type Inline } from "@/lib/readme-md";

/** Shorter than this, the whole README fits the preview: nothing to open. */
const SHORT = 700;

/** A README image: loaded lazily, with no referrer, and gone (leaving its alt text) if it can't load. */
function Img({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return alt ? <span className="text-faint">{alt}</span> : null;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- README images are arbitrary files from GitHub; the optimiser has no use for them
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className="inline-block h-auto max-h-80 max-w-full align-middle"
    />
  );
}

function Inlines({ nodes }: { nodes: Inline[] }) {
  return (
    <>
      {nodes.map((n, i) => {
        switch (n.t) {
          case "text":
            return <Fragment key={i}>{n.v}</Fragment>;
          case "code":
            return <code key={i} className="rounded-sm bg-panel-2 px-1.5 py-0.5 font-mono text-[0.85em] text-ink">{n.v}</code>;
          case "strong":
            return <strong key={i} className="font-semibold text-ink"><Inlines nodes={n.c} /></strong>;
          case "em":
            return <em key={i}><Inlines nodes={n.c} /></em>;
          case "image":
            return <Img key={i} src={n.src} alt={n.alt} />;
          case "link":
            return (
              <a key={i} href={n.href} target="_blank" rel="noopener noreferrer nofollow" className="text-blue underline decoration-blue/40 underline-offset-[3px] transition-colors hover:decoration-blue">
                <Inlines nodes={n.c} />
              </a>
            );
        }
      })}
    </>
  );
}

const HEADING = {
  1: "mb-1 mt-7 border-b border-line pb-2 text-[1.12rem] font-semibold tracking-tight text-ink first:mt-0",
  2: "mb-1 mt-7 border-b border-line pb-2 text-[1.05rem] font-semibold tracking-tight text-ink first:mt-0",
  3: "mt-5 text-[0.98rem] font-semibold text-ink first:mt-0",
  4: "mt-4 text-[0.92rem] font-semibold text-ink first:mt-0",
} as const;

/** A code block with its language (when the README names one) and a copy button: install commands are the first thing a newcomer tries. */
function CodeBlock({ lang, v }: { lang: string | null; v: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(v);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // No clipboard (an insecure page, a blocked permission): the text is still there to select.
    }
  }
  return (
    <div className="mt-3 border border-line bg-panel-2" data-readme-code>
      <div className="flex items-center justify-between gap-3 border-b border-line px-3">
        <span className="font-mono text-[0.72rem] text-faint">{lang ?? ""}</span>
        <button type="button" onClick={copy} className="-mr-1.5 inline-flex min-h-8 items-center gap-1.5 px-1.5 font-sans text-[0.75rem] text-faint transition-colors hover:text-ink">
          {copied ? <Check aria-hidden="true" strokeWidth={1.75} className="size-3.5 text-blue" /> : <Copy aria-hidden="true" strokeWidth={1.5} className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
          <span className="sr-only"> this code</span>
        </button>
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-[0.8rem] leading-relaxed text-ink">
        <code>{v}</code>
      </pre>
    </div>
  );
}

function BlockView({ b }: { b: Block }) {
  switch (b.t) {
    case "heading": {
      const Tag = b.level <= 2 ? "h3" : "h4"; // under the section's own h2
      return <Tag className={HEADING[b.level]}><Inlines nodes={b.c} /></Tag>;
    }
    case "p":
      return (
        <p className={`mt-3 first:mt-0 ${b.media ? "flex flex-wrap items-center gap-x-1.5 gap-y-1.5" : ""}`}>
          <Inlines nodes={b.c} />
        </p>
      );
    case "quote":
      return (
        <blockquote className="mt-3 border-l-2 border-blue/50 bg-blue/5 py-2 pl-3.5 pr-3 text-muted">
          <Inlines nodes={b.c} />
        </blockquote>
      );
    case "code":
      return <CodeBlock lang={b.lang} v={b.v} />;
    case "hr":
      return <hr className="my-5 border-line" />;
    case "list": {
      const List = b.ordered ? "ol" : "ul";
      return (
        <List className={`mt-3 space-y-1.5 pl-6 ${b.ordered ? "list-decimal" : "list-disc"} marker:text-faint`}>
          {b.items.map((it, i) => (
            <li key={i} className={it.depth ? "ml-5 list-[circle]" : undefined}>
              <Inlines nodes={it.c} />
            </li>
          ))}
        </List>
      );
    }
  }
}

type Tab = "readme" | "contributing";

/** The tab's text as blocks, a preview that opens in full. */
function Doc({ markdown, repo, name }: { markdown: string; repo: string; name: Tab }) {
  // Rows of status badges are left out: nothing a newcomer can act on, and they washed out in the preview's fade.
  const blocks = useMemo(() => parseReadme(markdown, repo).filter((b) => !badgeRow(b)), [markdown, repo]);
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  if (!blocks.length) return <p className="px-4 py-5 font-sans text-[0.92rem] text-muted sm:px-6">This file is empty.</p>;
  const long = markdown.length > SHORT;

  return (
    <>
      <div id={bodyId} className={`relative px-4 pb-5 pt-4 font-sans text-[0.92rem] leading-7 text-ink sm:px-6 ${long && !open ? "max-h-[22rem] overflow-hidden" : ""}`}>
        {blocks.map((b, i) => (
          <BlockView key={i} b={b} />
        ))}
        {long && !open && (
          <span aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 h-28" style={{ background: "linear-gradient(to bottom, transparent, var(--panel) 85%)" }} />
        )}
      </div>

      {long && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={bodyId}
          data-umami-event={open ? `${name}-collapse` : `${name}-expand`}
          className="group flex min-h-11 w-full items-center justify-center gap-1.5 border-t border-line font-sans text-[0.82rem] font-medium text-muted transition-colors hover:bg-panel-2/60 hover:text-ink"
        >
          {open ? "Show less" : name === "readme" ? "Show full README" : "Show full guide"}
          <ChevronDown aria-hidden="true" strokeWidth={1.75} className={`size-4 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
        </button>
      )}
    </>
  );
}

/** The contributing guide, read when its tab is first opened (/api/contributing). */
function Contributing({ repo, link }: { repo: string; link: string }) {
  const [text, setText] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    fetch(`/api/contributing?repo=${encodeURIComponent(repo)}`)
      .then((r) => (r.ok ? r.text() : null))
      .catch(() => null)
      .then((t) => {
        if (live) setText(t);
      });
    return () => {
      live = false;
    };
  }, [repo]);
  if (text === undefined)
    return (
      <p role="status" className="px-4 py-5 font-sans text-[0.92rem] text-faint sm:px-6">
        Loading the contributing guide…
      </p>
    );
  if (text === null)
    return (
      <p className="px-4 py-5 font-sans text-[0.92rem] text-muted sm:px-6">
        Holt couldn&apos;t load the guide here.{" "}
        <a href={link} target="_blank" rel="noopener noreferrer" className="text-link">Read it on GitHub</a>.
      </p>
    );
  return <Doc markdown={text} repo={repo} name="contributing" />;
}

/**
 * The README and, beside it, the contributing guide when the project has one
 * that GitHub serves as a file (`contributing`, its GitHub link): two tabs, as
 * on GitHub. With no guide, only the README tab shows.
 */
export function ReadmeSection({ markdown, repo, contributing }: { markdown: string; repo: string; contributing?: string | null }) {
  const guide = contributing && contributingFileUrl(contributing, repo) ? contributing : null;
  const [tab, setTab] = useState<Tab>("readme");
  const baseId = useId();
  const tabs: { id: Tab; label: string; Icon: typeof BookOpen; href: string }[] = [
    { id: "readme", label: "README", Icon: BookOpen, href: `https://github.com/${repo}#readme` },
    ...(guide ? [{ id: "contributing" as const, label: "Contributing", Icon: Users, href: guide }] : []),
  ];
  const active = tabs.find((t) => t.id === tab) ?? tabs[0];

  function onKey(e: React.KeyboardEvent) {
    if (tabs.length < 2 || (e.key !== "ArrowRight" && e.key !== "ArrowLeft")) return;
    e.preventDefault();
    const next = tabs[(tabs.indexOf(active) + 1) % tabs.length];
    setTab(next.id);
    document.getElementById(`${baseId}-${next.id}-tab`)?.focus();
  }

  return (
    <section aria-labelledby={`${baseId}-title`} className="border border-line-strong bg-panel" data-readme>
      <h2 id={`${baseId}-title`} className="sr-only">{guide ? "README and contributing guide" : "README"}</h2>
      {/* The tabs, as on GitHub, and the way to the real file. */}
      <div className="flex items-stretch gap-2 border-b border-line px-2 sm:px-3">
        <div role="tablist" aria-label="Project files" className="flex min-w-0 items-stretch" onKeyDown={onKey}>
          {tabs.map((t) => {
            const on = t.id === active.id;
            return (
              <button
                key={t.id}
                type="button"
                role="tab"
                id={`${baseId}-${t.id}-tab`}
                aria-selected={on}
                aria-controls={`${baseId}-panel`}
                tabIndex={on ? 0 : -1}
                onClick={() => setTab(t.id)}
                data-umami-event={`readme-tab-${t.id}`}
                className={`-mb-px inline-flex min-h-11 items-center gap-2 border-b-2 px-3 font-sans text-[0.88rem] transition-colors ${
                  on ? "border-sel font-semibold text-ink" : "border-transparent text-muted hover:text-ink"
                }`}
              >
                <t.Icon aria-hidden="true" strokeWidth={1.5} className="size-4 shrink-0 text-faint" />
                {t.label}
              </button>
            );
          })}
        </div>
        <a href={active.href} target="_blank" rel="noopener noreferrer" className="ml-auto inline-flex min-h-11 shrink-0 items-center gap-1 font-sans text-[0.78rem] text-muted transition-colors hover:text-blue">
          View on GitHub
          <ExternalLink aria-hidden="true" strokeWidth={1.5} className="size-3.5" />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </div>

      <div role="tabpanel" id={`${baseId}-panel`} aria-labelledby={`${baseId}-${active.id}-tab`}>
        {active.id === "contributing" && guide ? <Contributing key="contributing" repo={repo} link={guide} /> : <Doc key="readme" markdown={markdown} repo={repo} name="readme" />}
      </div>
    </section>
  );
}
