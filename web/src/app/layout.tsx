import type { Metadata, Viewport } from "next";
import { JetBrains_Mono } from "next/font/google";
import { Footer } from "@/components/footer";
import { Header } from "@/components/header";
import { themeScript } from "@/components/theme-toggle";
import { SITE_URL } from "@/lib/site";
import "./globals.css";

const mono = JetBrains_Mono({
  variable: "--font-jetbrains",
  // greek: the ω in the header cat is on every page; preloading it with latin
  // saves a second font swap (and re-layout) right after first paint.
  subsets: ["latin", "greek"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Holt — find an open-source project that will actually merge your first PR",
    template: "%s · Holt",
  },
  description:
    "Paste any GitHub repo. Holt reads its recent pull requests and tells you, in plain English, whether newcomers get replies, get merged, and where their work lands.",
  openGraph: {
    siteName: "Holt",
    type: "website",
    title: "Holt — find an open-source project that will actually merge your first PR",
    description: "See how a project treats outside contributors before you spend your week on it.",
  },
  twitter: { card: "summary_large_image" },
  // Staging and previews: keep search engines out (robots.txt disallows too).
  ...(process.env.ROBOTS_NOINDEX === "1" ? { robots: { index: false, follow: false } } : {}),
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ece8dd" },
    { media: "(prefers-color-scheme: dark)", color: "#121312" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={mono.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="flex min-h-dvh flex-col">
        <a href="#content" className="skip-link">
          Skip to content
        </a>
        <Header />
        <main id="content" className="flex-1">
          {children}
        </main>
        <Footer />
      </body>
    </html>
  );
}
