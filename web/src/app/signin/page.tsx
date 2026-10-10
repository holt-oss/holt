import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { devSignInEnabled, oauthProviders, signIn } from "@/auth";
import { CatFace } from "@/components/cat-face";
import { PageTransition } from "@/components/motion/page-transition";
import { EXAMPLES_PATH } from "@/lib/examples";
import { afterSignIn } from "@/lib/home";
import { currentUser } from "@/lib/session";
import { SIGN_IN_HEADING, signInHeading, signInNotice } from "@/lib/signin";
import { ProviderButtons, type Provider } from "./provider-buttons";

export const metadata: Metadata = { title: "Sign in", robots: { index: false } };

const ICONS: Record<string, React.ReactNode> = {
  github: (
    <svg viewBox="0 0 24 24" className="size-5 shrink-0" fill="currentColor" aria-hidden="true">
      <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.39-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z" />
    </svg>
  ),
  google: (
    <svg viewBox="0 0 24 24" className="size-5 shrink-0" aria-hidden="true">
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8Z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24Z" />
      <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6h-4a12 12 0 0 0 0 10.8l4-3.1Z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9Z" />
    </svg>
  ),
};

// GitHub first: it's where Holt's readers already have an account.
const PROVIDERS = [
  { id: "github", name: "GitHub" },
  { id: "google", name: "Google" },
];

export default async function SignInPage({ searchParams }: PageProps<"/signin">) {
  const sp = await searchParams;
  // Back to where you signed in from, else your home (/me).
  const callbackUrl = afterSignIn(sp.callbackUrl);
  if (await currentUser()) redirect(callbackUrl);
  const configured = new Set(oauthProviders.map((p) => p.id));
  const notice = signInNotice(sp.error);
  // Worded from the callback (lib/signin.ts); a longer heading is set smaller.
  const heading = signInHeading(sp.callbackUrl);

  const providers: Provider[] = PROVIDERS.map((p) => ({
    ...p,
    icon: ICONS[p.id],
    action: configured.has(p.id)
      ? async () => {
          "use server";
          await signIn(p.id, { redirectTo: callbackUrl });
        }
      : null,
  }));

  return (
    <PageTransition>
      <div className="relative overflow-hidden">
        <div aria-hidden="true" className="hero-backdrop" />
        <div className="wrap relative flex min-h-[78dvh] items-center justify-center py-10 sm:py-16">
          <section aria-labelledby="signin-title" className="w-full max-w-md border border-line-strong bg-panel p-6 shadow-card sm:p-9 lg:max-w-[27rem]">
            <CatFace mood={notice?.tone === "error" ? "startled" : "adoring"} blink={!notice} className="text-[1.7rem]" />
            <h1 id="signin-title" className={`display mt-5 [overflow-wrap:anywhere] ${heading === SIGN_IN_HEADING ? "text-[2.3rem] sm:text-[2.7rem]" : "text-[1.7rem] sm:text-[2rem]"}`}>
              {heading}
            </h1>
            <p className="prose-sans mt-3 text-[1rem]">
              Holt keeps the repos you save and shows where your open PRs stand.
            </p>

            {notice && (
              <div
                role={notice.tone === "error" ? "alert" : "status"}
                className={`mt-6 border-l-2 px-4 py-3 font-sans ${notice.tone === "error" ? "border-orange bg-orange/10" : "border-blue bg-blue/10"}`}
              >
                <p className={`text-[0.95rem] font-semibold ${notice.tone === "error" ? "text-orange" : "text-blue"}`}>{notice.title}</p>
                {notice.body && <p className="mt-1 text-[0.9rem] leading-relaxed text-muted">{notice.body}</p>}
              </div>
            )}

            <div className="mt-7">
              <ProviderButtons providers={providers} />
            </div>

            {devSignInEnabled && (
              <form action="/api/dev-signin" method="post" className="mt-6 border border-amber/50 bg-amber/10 p-4">
                <p className="text-[0.85rem] font-semibold text-amber">Development only</p>
                <p className="mt-1 font-sans text-[0.9rem] text-muted">No OAuth app is configured, so you can sign in as a local test user.</p>
                <input type="hidden" name="callbackUrl" value={callbackUrl} />
                <div className="mt-3 grid grid-cols-[1fr_auto] gap-2">
                  <label htmlFor="dev-name" className="sr-only">Test user name</label>
                  <input id="dev-name" name="name" defaultValue="Dev Student" className="h-11 min-w-0 border border-line-strong bg-bg px-3 text-[0.9rem] outline-none focus:border-blue" />
                  <button type="submit" className="btn-primary min-h-11 bg-amber">dev sign-in</button>
                </div>
              </form>
            )}

            <div className="mt-7 space-y-2 border-t border-line pt-5 font-sans text-[0.88rem] leading-relaxed text-muted">
              <p className="flex gap-2.5">
                <LockIcon />
                <span>
                  Holt only reads public GitHub data. It never posts, comments or opens PRs for you. From the account you pick, it gets your name, email and avatar.
                </span>
              </p>
              <p className="text-faint">
                By continuing you agree to the <Link href="/terms" className="text-link">Terms</Link> and{" "}
                <Link href="/privacy#google" className="text-link">Privacy Policy</Link>.
              </p>
            </div>

            <p className="mt-6 font-sans text-[0.9rem] text-muted">
              Just curious? <Link href={EXAMPLES_PATH} className="text-link">Try an example report →</Link>
            </p>
          </section>
        </div>
      </div>
    </PageTransition>
  );
}

function LockIcon() {
  return (
    <svg viewBox="0 0 16 16" className="mt-[0.3em] size-3.5 shrink-0 text-green" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <rect x="3" y="7" width="10" height="7" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
    </svg>
  );
}
