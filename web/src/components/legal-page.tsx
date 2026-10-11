import Link from "next/link";
import { CONTACT_EMAIL, LEGAL_PAGES, LEGAL_UPDATED } from "@/lib/site";
import { LegalToc } from "./legal-toc";
import { PageHead } from "./page-head";
import { PageTransition } from "./motion/page-transition";

// The frame every policy page shares: the PageHead band with a rail, the
// "Last updated" line, a prose column (styles: .legal in globals.css) with
// "On this page" beside it on wide screens, and links to the other policies.
// Static: nothing of its own to wait for; each page's loading.tsx is the plain page head.
export function LegalPage({
  rail,
  title,
  lede,
  children,
}: {
  rail: string;
  title: React.ReactNode;
  lede: React.ReactNode;
  children: React.ReactNode;
}) {
  const others = LEGAL_PAGES.filter((p) => p.label !== rail);
  return (
    <PageTransition>
      <>
        <PageHead>
          <p className="rail mb-4 flex gap-2"><strong className="m-0">{rail}</strong><span>Holt · githolt.com</span></p>
          <h1 className="display max-w-3xl text-[clamp(1.8rem,4.2vw,2.6rem)]">{title}</h1>
          <p className="prose-sans mt-4 max-w-2xl text-[0.98rem]">{lede}</p>
          <p className="mt-5 text-[0.8rem] text-faint">Last updated: <time>{LEGAL_UPDATED}</time></p>
        </PageHead>

        <div className="wrap grid gap-12 py-8 sm:py-10 lg:grid-cols-[minmax(0,46rem)_13rem] lg:justify-between">
          <article className="legal min-w-0">{children}</article>
          <aside className="hidden lg:block">
            <LegalToc />
          </aside>
        </div>

        <nav aria-label="Policies" className="wrap border-t border-line py-6 text-[0.84rem] text-faint">
          <p className="flex flex-wrap items-center gap-x-5">
            <span>See also:</span>
            {others.map((p) => (
              <Link key={p.href} href={p.href} className="inline-flex min-h-11 items-center hover:text-ink">{p.label}</Link>
            ))}
          </p>
        </nav>
      </>
    </PageTransition>
  );
}

const escapeHtml = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/**
 * The contact address as a mailto link. Renders the placeholder verbatim until
 * the env is set.
 *
 * Cloudflare's Email Address Obfuscation rewrites every address in the HTML
 * to "[email protected]" plus a JS decoder, so crawlers (Google's OAuth
 * verification included) would see no contact address on the policy pages.
 * Cloudflare skips whatever sits between <!--email_off--> and <!--email_on-->,
 * and JSX can't emit HTML comments, so this one static fragment is written
 * as raw HTML. The address comes from the build env, not from a user.
 */
export function ContactEmail() {
  if (CONTACT_EMAIL === "CONTACT_EMAIL") return <span className="text-ink">{CONTACT_EMAIL}</span>;
  const addr = escapeHtml(CONTACT_EMAIL);
  return <span dangerouslySetInnerHTML={{ __html: `<!--email_off--><a href="mailto:${addr}" class="text-link">${addr}</a><!--email_on-->` }} />;
}
