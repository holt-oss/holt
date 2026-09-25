import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";
import { getReport } from "@/lib/api";
import { humanHours } from "@/lib/format";
import { isValidRepo } from "@/lib/repo";
import { SITE_HOST } from "@/lib/site";

export const alt = "Holt report: is this repository worth your time?";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const regular = readFile(join(process.cwd(), "assets/fonts/JetBrainsMono-400.ttf"));
const bold = readFile(join(process.cwd(), "assets/fonts/JetBrainsMono-700.ttf"));

// Dark brand card with a lighter frame, so it holds its edge in light and dark feeds.
const C = { bg: "#0d0e0e", panel: "#141615", ink: "#e7e5dc", muted: "#a3a39b", line: "#3b3e3a", blue: "#83a9ff", green: "#69c7a6", orange: "#ee925d", amber: "#ffb331" };

export default async function Image({ params }: { params: Promise<{ owner: string; repo: string }> }) {
  const { owner, repo } = await params;
  const valid = isValidRepo(owner, repo);
  const r = valid ? await getReport(`${owner}/${repo}`) : null;
  const report = r?.ok ? r.data : null;
  const name = report?.repo ?? `${owner}/${repo}`;
  const tone = !report ? C.blue : report.verdict === "viable" ? C.green : report.verdict === "not_viable" ? C.orange : C.amber;
  const cat = !report ? "(=^•ω•^=)" : report.verdict === "viable" ? "(=^•ω•^=)" : report.verdict === "not_viable" ? "(=;ω;=)" : "(=•_•=)?";
  const s = report?.stats;
  const stats = s
    ? [
        [`${s.outsider_merged} of ${s.outsider_attempts}`, "outside PRs merged"],
        [s.median_first_response_hours == null ? "none" : humanHours(s.median_first_response_hours), "typical first reply"],
        [String(s.first_time_merged_authors), "first-timers merged"],
      ]
    : [];

  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", background: C.line, padding: 3, fontFamily: "JetBrains Mono" }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", background: C.bg, borderTop: `8px solid ${tone}`, padding: "48px 64px 44px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 28, color: C.muted }}>
            <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
              <span style={{ color: C.blue, letterSpacing: -3 }}>{cat}</span>
              <span style={{ color: C.ink, fontWeight: 700 }}>holt</span>
            </div>
            <span>{SITE_HOST}/{name.length > 28 ? repo : name}</span>
          </div>

          <div style={{ display: "flex", marginTop: 48, fontSize: 40, color: C.muted, letterSpacing: -1 }}>{name}</div>
          <div style={{ display: "flex", marginTop: 8, fontSize: report ? 92 : 76, fontWeight: 700, color: tone, letterSpacing: -5, lineHeight: 1.05 }}>
            {report ? `${report.headline}.` : "Worth your time?"}
          </div>

          {report ? (
            <div style={{ display: "flex", marginTop: "auto", gap: 20 }}>
              {stats.map(([big, label]) => (
                <div key={label} style={{ flex: 1, display: "flex", flexDirection: "column", background: C.panel, border: `2px solid ${C.line}`, padding: "20px 24px" }}>
                  <span style={{ fontSize: 40, fontWeight: 700, color: C.ink, letterSpacing: -1.5 }}>{big}</span>
                  <span style={{ fontSize: 22, color: C.muted, marginTop: 4 }}>{label}</span>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ display: "flex", marginTop: "auto", fontSize: 32, color: C.ink, lineHeight: 1.4, maxWidth: 980 }}>
              Holt reads the pull request history and tells you, in plain English, whether newcomers get replies and get merged.
            </div>
          )}
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "JetBrains Mono", data: await regular, weight: 400, style: "normal" },
        { name: "JetBrains Mono", data: await bold, weight: 700, style: "normal" },
      ],
    },
  );
}
