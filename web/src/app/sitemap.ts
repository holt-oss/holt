import type { MetadataRoute } from "next";
import { listReports } from "@/lib/api";
import { SITE_URL } from "@/lib/site";

// Rendered per request: the list of cached reports changes all the time, and
// a build has no API to ask.
export const dynamic = "force-dynamic";

const STATIC: { path: string; priority: number; changeFrequency: "daily" | "weekly" }[] = [
  { path: "/", priority: 1, changeFrequency: "weekly" },
  { path: "/hacktoberfest", priority: 0.9, changeFrequency: "daily" },
  { path: "/find", priority: 0.8, changeFrequency: "daily" },
  { path: "/how-it-works", priority: 0.5, changeFrequency: "weekly" },
  { path: "/pricing", priority: 0.4, changeFrequency: "weekly" },
  { path: "/terms", priority: 0.2, changeFrequency: "weekly" },
  { path: "/privacy", priority: 0.2, changeFrequency: "weekly" },
  { path: "/refunds", priority: 0.2, changeFrequency: "weekly" },
  { path: "/contact", priority: 0.2, changeFrequency: "weekly" },
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  if (process.env.ROBOTS_NOINDEX === "1") return [];
  const reports = await listReports(500);
  return [
    ...STATIC.map((s) => ({ url: `${SITE_URL}${s.path === "/" ? "" : s.path}`, changeFrequency: s.changeFrequency, priority: s.priority })),
    ...reports.map((r) => ({ url: `${SITE_URL}/${r.repo}`, lastModified: r.generated_at, changeFrequency: "daily" as const, priority: 0.6 })),
  ];
}
