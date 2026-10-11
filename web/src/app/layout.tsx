import type { Metadata, Viewport } from "next";
import { Archivo, JetBrains_Mono } from "next/font/google";
import { cookies } from "next/headers";
import { Footer } from "@/components/footer";
import { MarketingHeader } from "@/components/header";
import { MenuAutoClose } from "@/components/motion/menu-autoclose";
import { NavPending } from "@/components/motion/nav-pending";
import { RouteFallback } from "@/components/motion/route-fallback";
import { SmoothScroll } from "@/components/motion/smooth-scroll";
import { CheckWatch } from "@/components/check-watch";
import { appShell } from "@/components/shell/app-shell";
import { CheckLinks } from "@/components/shell/check-focus";
import { ShellFrame } from "@/components/shell/shell-frame";
import { themeScript } from "@/components/theme-toggle";
import { ANALYTICS } from "@/lib/analytics";
import { motionAttr, motionFromCookies } from "@/lib/motion";
import { currentUser } from "@/lib/session";
import { RAIL_COOKIE, railCollapsed } from "@/lib/shell";
import { SITE_URL } from "@/lib/site";
import "lenis/dist/lenis.css";
import "./globals.css";

const mono = JetBrains_Mono({
  variable: "--font-jetbrains",
  // greek: the ω in the header cat is on every page; preloading it with latin
  // saves a second font swap (and re-layout) right after first paint.
  subsets: ["latin", "greek"],
  display: "swap",
});

// Only the hero's sub-line uses it, at the regular weight.
const sans = Archivo({
  variable: "--font-archivo",
  weight: "400",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Holt · will this repo merge your PR?",
    template: "%s · Holt",
  },
  description:
    "Paste any GitHub repo. Holt reads its recent pull requests and tells you, in plain English, whether outside contributors get replies, get merged, and where their work lands.",
  openGraph: {
    siteName: "Holt",
    type: "website",
    title: "Holt · check whether a repo actually merges outsiders' PRs",
    description: "See how a project treats outside contributors before you spend your week on it. Swap hub for holt in any GitHub link.",
  },
  twitter: { card: "summary_large_image" },
  // Staging and previews: keep search engines out (robots.txt disallows too).
  ...(process.env.ROBOTS_NOINDEX === "1" ? { robots: { index: false, follow: false } } : {}),
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8f6f1" },
    { media: "(prefers-color-scheme: dark)", color: "#121312" },
  ],
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // Signed in: the app shell's sidebar and top bar, used on app pages (lib/shell.ts).
  const jar = await cookies();
  const user = await currentUser();
  // The desktop rail folded or not, on <html> before the first paint (lib/shell.ts).
  const rail = railCollapsed(jar.get(RAIL_COOKIE)?.value);
  const app = user ? await appShell(user, rail) : null;
  // The motion setting, on <html> before the first paint (lib/motion.ts).
  const motion = motionAttr(motionFromCookies(jar));
  return (
    <html lang="en" className={`${mono.variable} ${sans.variable}`} data-motion={motion} data-rail={rail ? "collapsed" : undefined} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        {ANALYTICS && <script defer src={ANALYTICS.src} data-website-id={ANALYTICS.websiteId} />}
      </head>
      {/* Extensions such as Grammarly add attributes to <body> before React
          hydrates. This only silences attribute mismatches on <body> itself. */}
      <body className="flex min-h-dvh flex-col" suppressHydrationWarning>
        <a href="#content" className="skip-link">
          Skip to content
        </a>
        <ShellFrame marketingHeader={<MarketingHeader user={user} />} footer={<Footer signedIn={Boolean(user)} />} topBar={app?.topBar ?? null} rail={app?.rail ?? null}>
          {children}
          <RouteFallback />
        </ShellFrame>
        {user && <CheckWatch />}
        <NavPending />
        <MenuAutoClose />
        <CheckLinks />
        <SmoothScroll />
      </body>
    </html>
  );
}
