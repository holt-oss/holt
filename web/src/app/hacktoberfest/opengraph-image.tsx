import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";
import { SITE_HOST } from "@/lib/site";

export const alt = "Hacktoberfest: repos that will actually review your pull request, from Holt";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const regular = readFile(join(process.cwd(), "assets/fonts/JetBrainsMono-400.ttf"));
const bold = readFile(join(process.cwd(), "assets/fonts/JetBrainsMono-700.ttf"));

export default async function Image() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", background: "#3b3e3a", padding: 3, fontFamily: "JetBrains Mono" }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", background: "#0d0e0e", borderTop: "8px solid #ee925d", padding: "56px 64px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 30 }}>
            <span style={{ color: "#83a9ff", letterSpacing: -3 }}>(=^•ω•^=)</span>
            <span style={{ color: "#e7e5dc", fontWeight: 700 }}>holt</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", marginTop: 56, fontSize: 70, fontWeight: 700, letterSpacing: -4, lineHeight: 1.08, color: "#e7e5dc" }}>
            <span style={{ color: "#ee925d", fontSize: 40, letterSpacing: -1 }}>Hacktoberfest 2026</span>
            <span style={{ marginTop: 12 }}>Repos that will actually</span>
            <span>review your pull request.</span>
          </div>
          <div style={{ display: "flex", marginTop: "auto", justifyContent: "space-between", fontSize: 26, color: "#a3a39b" }}>
            <span>Starter issues by language. Free.</span>
            <span style={{ color: "#69c7a6" }}>{SITE_HOST}/hacktoberfest</span>
          </div>
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
