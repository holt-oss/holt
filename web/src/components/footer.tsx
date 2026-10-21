"use client";

// The site footer: a sign-off, one last action, the links, and the repos Holt
// checked most recently (the expressive design plan, pattern 7).
// - One cat carries it, top right: its eyes follow the pointer across the footer, it
//   reads along as you type a repo, cheers when it looks right, puzzles when
//   it can't be one, and goes soft over the open-source links. Tap to pet.
// - The sign-off is a terminal line, `$ git commit --to-the-right-repo`. It
//   waves once as the footer comes into view (letters bob, none is ever
//   hidden) and again on hover; the cursor after it blinks.
// - On the landing page only, the last action: the URL trick as a form
//   (githolt.com/owner/repo) and find a project. Other pages have their own.
// - "Recently checked" loads only when the footer is near, from a cached
//   route, and sits last so it never pushes anything down when it arrives.
// Everything is in the server HTML, links included; motion is CSS
// (globals.css, .ft-*) and never runs under reduced motion.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { track } from "@/lib/analytics";
import { inputMood, type CatMood } from "@/lib/cat";
import { deviceReduces, prefersReducedMotion, setMotion, toggledMotion } from "@/lib/motion";
import { NOT_A_REPO, pasteHref } from "@/lib/gate";
import { timeAgo } from "@/lib/format";
import { checkedLabel, type RecentChecks } from "@/lib/recent-checks";
import { parseRepoInput } from "@/lib/repo";
import { GITHUB_REPO_URL, LEGAL_PAGES, SITE_HOST } from "@/lib/site";
import { useReducedMotion } from "./motion/use-seen";
import { useOpen } from "./paste-box";
import { ReactiveCat } from "./reactive-cat";

const SIGN_OFF = "git commit --to-the-right-repo";

/** "terms" → "Terms": the policy labels are lowercase where the policy pages use them as their rail. */
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** First path segments that are the site's own pages, not a repository owner. */
const SITE_ROUTES = new Set(["api", "badge", "compare", "contact", "discover", "example-ai-report", "example-merge-plan", "examples", "find", "hacktoberfest", "how-it-works", "me", "preflight", "pricing", "privacy", "profile", "refunds", "settings", "signin", "terms"]);

/** /owner/repo, and not one of the site's own two-part pages such as /me/repos. */
function isReportPath(path: string | null): boolean {
  const parts = (path ?? "").split("/").filter(Boolean);
  return parts.length === 2 && !SITE_ROUTES.has(parts[0].toLowerCase());
}

/** Find a project's tabs: pages used every day, where the list is the point. */
const WORKING_ROUTES = new Set(["find", "discover", "hacktoberfest"]);

/** Reports and the working pages get the slim footer. */
function isSlimPath(path: string | null): boolean {
  return isReportPath(path) || WORKING_ROUTES.has((path ?? "").split("/").filter(Boolean)[0]?.toLowerCase() ?? "");
}

/** The footer under a report or a working page: one line of what Holt does and doesn't do, then the links. */
function ReportFooter({ signedIn }: { signedIn: boolean }) {
  return (
    <footer className="site-footer mt-auto border-t border-line bg-panel">
      <div className="wrap flex flex-col gap-5 py-8 text-[0.85rem] md:flex-row md:items-start md:justify-between">
        <div className="max-w-sm">
          <p className="font-semibold text-ink">Holt</p>
          <p className="mt-1 font-sans leading-snug text-muted">Reads a project&apos;s public pull request history on GitHub. It never posts, comments or contacts anyone.</p>
          <p className="mt-2 text-faint">Open source, Apache-2.0</p>
        </div>
        <nav aria-label="Footer" className="grid grid-cols-2 gap-x-10 gap-y-1 sm:grid-cols-3">
          <ul>
            <FLink href="/find">Find a project</FLink>
            <FLink href="/discover">Browse projects</FLink>
            <FLink href="/how-it-works">How it works</FLink>
          </ul>
          <ul>
            <FLink href="/badge">Badge for maintainers</FLink>
            <FLink href="/pricing">Pricing</FLink>
            <FLink href={GITHUB_REPO_URL}>Source on GitHub</FLink>
          </ul>
          <ul>
            {LEGAL_PAGES.map((p) => (
              <FLink key={p.href} href={p.href}>{cap(p.label)}</FLink>
            ))}
            <FLink href="/contact#team">Team</FLink>
            {!signedIn && <MotionSwitch />}
          </ul>
        </nav>
      </div>
    </footer>
  );
}

export function Footer({ signedIn = false }: { signedIn?: boolean }) {
  // The landing page is "/"; every other page
  // already has its own action, so only the landing ends on the form.
  const path = usePathname();
  const onLanding = path === "/";
  // A report (/owner/repo) and the working pages get a slim footer: the page is long, and the big sign-off is for the landing.
  const slim = isSlimPath(path);
  const root = useRef<HTMLElement>(null);
  const cat = useRef<HTMLButtonElement>(null);
  const frame = useRef(0);
  const [look, setLook] = useState(0);
  const [hover, setHover] = useState<CatMood | null>(null);
  const [pet, setPet] = useState(false);
  const [value, setValue] = useState("");
  const [focused, setFocused] = useState(false);
  const [error, setError] = useState("");
  const [busy, open] = useOpen();
  const [seen, setSeen] = useState(false);
  const [waves, setWaves] = useState(0);
  const [recent, setRecent] = useState<RecentChecks | null>(null);

  // Near the viewport: fetch the strip. In view: wave once.
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    let fetched = false;
    const near = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting || fetched) return;
        fetched = true;
        near.disconnect();
        fetch("/api/recent-checks")
          .then((r) => (r.ok ? r.json() : null))
          .then((d: RecentChecks | null) => {
            if (d?.recent?.length) setRecent(d);
          })
          .catch(() => {});
      },
      { rootMargin: "600px 0px" },
    );
    const inView = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting) return;
        setSeen(true);
        inView.disconnect();
      },
      { rootMargin: "0px 0px -20% 0px" },
    );
    near.observe(el);
    inView.observe(el);
    return () => {
      near.disconnect();
      inView.disconnect();
      cancelAnimationFrame(frame.current);
    };
  }, []);

  const ref = parseRepoInput(value);
  const mood: CatMood = pet ? "adoring" : busy ? "determined" : error ? "thinking" : (inputMood(value, Boolean(ref)) ?? hover ?? "ready");
  // In the field, the eyes follow the caret along it; elsewhere, the pointer.
  const gaze = focused ? (value ? Math.min(1, value.length / 28) * 2 - 1 : 0.6) : look;

  const onMove = (e: React.PointerEvent) => {
    if (e.pointerType !== "mouse" || frame.current) return;
    const x = e.clientX;
    frame.current = requestAnimationFrame(() => {
      frame.current = 0;
      const r = cat.current?.getBoundingClientRect();
      if (!r || prefersReducedMotion()) return;
      setLook(Math.max(-1, Math.min(1, (x - (r.left + r.width / 2)) / (innerWidth * 0.35))));
    });
  };

  const go = () => {
    if (!ref) {
      setError(NOT_A_REPO);
      return;
    }
    setError("");
    const repo = `${ref.owner}/${ref.repo}`;
    track("paste-submit", { repo, signedIn: signedIn ? "yes" : "no", from: "footer" });
    open(pasteHref(repo));
  };

  const react = (m: CatMood) => ({
    onPointerEnter: () => setHover(m),
    onPointerLeave: () => setHover(null),
    onFocus: () => setHover(m),
    onBlur: () => setHover(null),
  });

  if (slim) return <ReportFooter signedIn={signedIn} />;

  return (
    <footer ref={root} onPointerMove={onMove} className="site-footer mt-auto overflow-clip border-t border-line bg-panel">
      <div className="wrap relative pb-10 pt-16 md:pt-24">
        {/* Top right, in the padding above the sign-off. On the landing, the
            scroll companion fades out as the footer arrives and this cat
            lands (motion/cat-companion.tsx; data-footer-cat). */}
        <button
          ref={cat}
          type="button"
          aria-label="Pet the cat"
          data-footer-cat
          onClick={() => {
            setPet(true);
            window.setTimeout(() => setPet(false), 900);
          }}
          className="absolute right-0 top-2 px-1 py-2 text-[clamp(1.9rem,4.4vw,3.2rem)] leading-none [touch-action:manipulation] md:top-3"
        >
          <ReactiveCat mood={mood} look={gaze} />
        </button>
        <p
          className="ft-signoff font-semibold tracking-[-0.03em] text-ink"
          data-waving={seen || waves > 0}
          onPointerEnter={() => setWaves((n) => n + 1)}
        >
          <span className="sr-only">{SIGN_OFF}</span>
          <span key={`${seen}-${waves}`} aria-hidden="true">
            <span className="text-amber">$ </span>
            {/* Words stay whole, so a line only breaks between them. */}
            {SIGN_OFF.split(" ").map((word, w, all) => {
              const start = all.slice(0, w).join(" ").length + (w ? 1 : 0);
              return (
                <span key={w} className="whitespace-nowrap">
                  {[...word].map((ch, i) => (
                    <span key={i} className="ft-wave" style={{ ["--i" as string]: start + i }}>
                      {ch}
                    </span>
                  ))}
                  {w < all.length - 1 ? " " : <span className="ft-caret" />}
                </span>
              );
            })}
          </span>
        </p>
        {onLanding && (
          <p className="mt-4 max-w-[560px] font-sans text-[1.05rem] text-muted">
            Paste a repo. You&apos;ll know before you write a line of code.
          </p>
        )}

        {onLanding && (
          <>
            {/* The URL trick as a form. */}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                go();
              }}
              className="mt-10 grid max-w-[820px] grid-cols-[auto_minmax(0,1fr)_auto] items-stretch border border-line-strong bg-bg transition-colors focus-within:border-blue"
            >
              <label htmlFor="footer-repo" className="flex items-center pl-4 text-[0.95rem] text-faint sm:text-[1.05rem]">
                <span className="sr-only">Repo to check: </span>
                <span aria-hidden="true">{SITE_HOST}/</span>
              </label>
              <input
                id="footer-repo"
                value={value}
                onChange={(e) => {
                  setValue(e.target.value);
                  if (error) setError("");
                }}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                autoComplete="off"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                enterKeyHint="go"
                placeholder="owner/repo"
                aria-invalid={Boolean(error)}
                aria-describedby={error ? "footer-repo-error" : undefined}
                className="h-14 min-w-0 bg-transparent px-0.5 text-[0.95rem] text-ink outline-none placeholder:text-faint sm:text-[1.05rem]"
              />
              <button
                type="submit"
                disabled={busy}
                {...react("celebrating")}
                className="border-l border-line-strong px-4 font-semibold text-blue transition-colors hover:bg-blue hover:text-on-accent sm:px-6"
              >
                {busy ? "opening…" : "check →"}
              </button>
            </form>
            <p id="footer-repo-error" role={error ? "alert" : undefined} className="mt-2 min-h-6 font-sans text-[0.9rem] text-orange">
              {error}
            </p>
            <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-2">
              <Link href="/find" {...react("celebrating")} className="bracket-link bracket-link--orange">
                [ find a project → ]
              </Link>
            </p>
          </>
        )}

        {/* Three columns side by side from the sign-off's left edge, each as
            wide as its words, then one line of fine print under a rule. */}
        <nav aria-label="Footer" className="mt-14 grid grid-cols-2 gap-x-10 gap-y-8 text-[0.86rem] sm:flex sm:flex-wrap sm:gap-x-20">
          <Group title="Product">
            <FLink href="/find">Find a project</FLink>
            <FLink href="/discover">Browse projects</FLink>
            <FLink href="/how-it-works">How it works</FLink>
            <FLink href="/badge">Badge for maintainers</FLink>
            <FLink href="/pricing">Pricing</FLink>
          </Group>
          <Group title="Open source">
            <FLink href={GITHUB_REPO_URL} {...react("adoring")}>holt-oss/holt</FLink>
            <FLink href={`${GITHUB_REPO_URL}/blob/main/CONTRIBUTING.md`} {...react("adoring")}>Contributing</FLink>
            <FLink href={`${GITHUB_REPO_URL}/blob/main/docs/USAGE.md`} {...react("adoring")}>The CLI</FLink>
          </Group>
          <Group title="Legal">
            {LEGAL_PAGES.map((p) => (
              <FLink key={p.href} href={p.href}>{cap(p.label)}</FLink>
            ))}
            <FLink href="/contact#team">Team</FLink>
            {/* Signed in, it's under Settings → Display. */}
            {!signedIn && <MotionSwitch />}
          </Group>
        </nav>
        <p className="mt-10 border-t border-line pt-5 text-[0.78rem] text-faint">
          Holt · open source, Apache-2.0 · read-only toward GitHub: it never posts, comments or contacts anyone.
        </p>
      </div>

      {/* Last, so it can arrive without moving anything. */}
      {recent && (
        <div className="ft-ticker border-t border-line pb-1.5 pt-4 text-[0.85rem]">
          <p className="wrap text-faint">recently checked · {checkedLabel(recent)}</p>
          <div className="ft-ticker-mask">
            <ul className="ft-ticker-track">
              {[0, 1].map((copy) =>
                recent.recent.map((r) => (
                  <li key={`${copy}-${r.repo}`} aria-hidden={copy === 1 || undefined} className="ft-ticker-item">
                    <Link href={`/${r.repo}`} prefetch={false} tabIndex={copy === 1 ? -1 : undefined} className="inline-flex min-h-11 items-center hover:text-blue">
                      {r.repo}
                    </Link>
                    <span className="text-faint"> {timeAgo(r.generated_at)}</span>
                  </li>
                )),
              )}
            </ul>
          </div>
        </div>
      )}
    </footer>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2.5 text-[0.72rem] uppercase tracking-[0.08em] text-faint">{title}</p>
      <ul>{children}</ul>
    </div>
  );
}

function MotionSwitch() {
  const reduced = useReducedMotion();
  return (
    <li>
      <button
        type="button"
        aria-pressed={reduced}
        onClick={() => setMotion(toggledMotion(reduced, deviceReduces()))}
        className="inline-flex min-h-11 items-center text-left text-muted hover:text-ink sm:min-h-0 sm:py-1"
      >
        Reduce motion<span aria-hidden="true" className={reduced ? "ml-1.5 text-blue" : "hidden"}>· on</span>
      </button>
    </li>
  );
}

function FLink({ href, children, ...rest }: { href: string; children: React.ReactNode } & React.HTMLAttributes<HTMLAnchorElement>) {
  const cls = "inline-flex min-h-11 items-center text-muted hover:text-ink sm:min-h-0 sm:py-1";
  return (
    <li>
      {href.startsWith("/") ? (
        <Link href={href} className={cls} {...rest}>{children}</Link>
      ) : (
        <a href={href} className={cls} {...rest}>{children}</a>
      )}
    </li>
  );
}
