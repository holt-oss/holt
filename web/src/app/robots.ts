import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

// Read ROBOTS_NOINDEX at request time, not at build.
export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  if (process.env.ROBOTS_NOINDEX === "1") {
    return { rules: { userAgent: "*", disallow: "/" } };
  }
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/api/", "/me/", "/settings", "/signin"] },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
