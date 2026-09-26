import Link from "next/link";
import { CONTACT_EMAIL, LEGAL_PAGES, LEGAL_UPDATED } from "@/lib/site";
import { PageHead } from "./page-head";
import { PageTransition } from "./motion/page-transition";

// The frame every policy page shares: the PageHead band with a rail, the
// "Last updated" line, a narrow prose column (styles: .legal in globals.css),
// and links to the other policies. Static: no loading.tsx, no skeleton.
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
        <PageHead narrow>
          <p className="rail mb-4 flex gap-2"><strong className="m-0">{rail}</strong><span>Holt · githolt.com</span></p>
          <h1 className="display max-w-3xl text-[clamp(1.9rem,6vw,3.2rem)]">{title}</h1>
          <p className="prose-sans mt-5 max-w-2xl text-[1.05rem]">{lede}</p>
          <p className="mt-6 text-[0.78rem] text-faint">Last updated: <time>{LEGAL_UPDATED}</time></p>
        </PageHead>

        <article className="wrap legal max-w-3xl py-10 sm:py-14">{children}</article>

        <nav aria-label="Policies" className="wrap max-w-3xl border-t border-line py-8 text-[0.8rem] text-faint">
          <p className="flex flex-wrap gap-x-5 gap-y-2">
            <span>See also:</span>
            {others.map((p) => (
              <Link key={p.href} href={p.href} className="hover:text-ink">{p.label}</Link>
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
