import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { devSignInEnabled, oauthProviders, signIn } from "@/auth";
import { CatFace } from "@/components/cat-face";
import { safeCallback } from "@/lib/safe-url";
import { currentUser } from "@/lib/session";

export const metadata: Metadata = { title: "Sign in", robots: { index: false } };

const ICONS: Record<string, React.ReactNode> = {
  github: (
    <svg viewBox="0 0 24 24" className="size-5" fill="currentColor" aria-hidden="true">
      <path d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.28 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.83 1.19 3.09 0 4.41-2.69 5.39-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5Z" />
    </svg>
  ),
  google: (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8Z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24Z" />
      <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6h-4a12 12 0 0 0 0 10.8l4-3.1Z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9Z" />
    </svg>
  ),
};

export default async function SignInPage({ searchParams }: PageProps<"/signin">) {
  const sp = await searchParams;
  const callbackUrl = safeCallback(sp.callbackUrl);
  if (await currentUser()) redirect(callbackUrl);
  const configured = new Set(oauthProviders.map((p) => p.id));

  return (
    <div className="wrap grid min-h-[70dvh] place-items-center py-12">
      <div className="w-full max-w-md">
        <CatFace mood="adoring" blink className="text-[2rem]" />
        <h1 className="display mt-6 text-[2.2rem] sm:text-[2.6rem]">Sign in to Holt</h1>
        <p className="prose-sans mt-3">
          Free reports don&apos;t need an account. Sign in for AI reports, your history, and to use your own API key.
        </p>

        <div className="mt-8 space-y-3">
          {[
            { id: "github", name: "GitHub" },
            { id: "google", name: "Google" },
          ].map((p) =>
            configured.has(p.id) ? (
              <form
                key={p.id}
                action={async () => {
                  "use server";
                  await signIn(p.id, { redirectTo: callbackUrl });
                }}
              >
                <button type="submit" className="flex min-h-13 w-full items-center justify-center gap-3 border border-line-strong bg-panel text-[0.92rem] font-semibold transition-colors hover:border-blue">
                  {ICONS[p.id]} continue with {p.name}
                </button>
              </form>
            ) : (
              <div key={p.id} className="flex min-h-13 w-full items-center justify-center gap-3 border border-dashed border-line-strong text-[0.88rem] text-faint" aria-disabled="true">
                {ICONS[p.id]} {p.name} sign-in isn&apos;t set up here
              </div>
            ),
          )}
        </div>

        {devSignInEnabled && (
          <form action="/api/dev-signin" method="post" className="mt-8 border border-amber/50 bg-amber/10 p-4">
            <p className="text-[0.72rem] uppercase tracking-[0.08em] text-amber">development only</p>
            <p className="mt-1 font-sans text-[0.88rem] text-muted">No OAuth app is configured, so you can sign in as a local test user.</p>
            <input type="hidden" name="callbackUrl" value={callbackUrl} />
            <div className="mt-3 grid grid-cols-[1fr_auto] gap-2">
              <label htmlFor="dev-name" className="sr-only">Test user name</label>
              <input id="dev-name" name="name" defaultValue="Dev Student" className="h-11 min-w-0 border border-line-strong bg-bg px-3 text-[0.9rem] outline-none focus:border-blue" />
              <button type="submit" className="btn-primary min-h-11 bg-amber">dev sign-in</button>
            </div>
          </form>
        )}

        <p className="mt-8 font-sans text-[0.8rem] text-faint">
          Holt only asks for your name, email and avatar. It never gets access to your repositories and never posts anything.
        </p>
      </div>
    </div>
  );
}
