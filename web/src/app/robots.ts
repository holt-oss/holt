import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

// Read ROBOTS_NOINDEX at request time, not at build.
export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  if (process.env.ROBOTS_NOINDEX === "1") {
    return { rules: { userAgent: "*", disallow: "/" } };
  }
  return {
    rules: { userAgent: "*", allow: "/", disallow: [
        "/api/", "/signin",
        // Account pages (lib/gate.ts): signed out, each is a redirect to sign-in.
        // The "$" keeps repos whose owner starts the same way (/comparex/y) crawlable.
        "/me/", "/settings", "/compare$", "/compare?", "/preflight$", "/preflight?",
        // Board facets (an order, a topic) run a heavy query per hit; the boards themselves stay crawlable.
        "/discover?", "/discover/*?", "/hacktoberfest?",
        // A Find search is /find with other filters; /find itself stays crawlable.
        "/find?",
      ],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
