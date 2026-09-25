// Lighthouse (mobile) for the key pages, one at a time, with the cached Chromium.
//   node lighthouse.mjs                  # staging
//   BASE_URL=http://127.0.0.1:3000 node lighthouse.mjs / /find
// Reports go to lighthouse/<page>.json; a score table is printed at the end.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const base = (process.env.BASE_URL || "https://holt-new.aahil-khan.xyz").replace(/\/$/, "");
const pages = process.argv.slice(2).length ? process.argv.slice(2) : ["/", "/pallets/flask", "/find"];

function chrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.homedir(), ".cache/ms-playwright");
  const dir = fs.readdirSync(cache).filter((d) => d.startsWith("chromium-")).sort().reverse()[0];
  return dir && path.join(cache, dir, "chrome-linux64/chrome");
}

fs.mkdirSync("lighthouse", { recursive: true });
const rows = [];
for (const p of pages) {
  const out = path.join("lighthouse", (p.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "") || "home") + ".json");
  const r = spawnSync("npx", ["-y", "lighthouse@13", base + p, "--quiet", "--output=json", `--output-path=${out}`,
    "--only-categories=performance,accessibility,best-practices,seo",
    "--chrome-flags=--headless=new --no-sandbox --disable-gpu"], {
    stdio: "inherit", env: { ...process.env, CHROME_PATH: chrome() },
  });
  if (r.status !== 0 || !fs.existsSync(out)) { rows.push([p, "failed"]); continue; }
  const lhr = JSON.parse(fs.readFileSync(out, "utf-8"));
  const c = lhr.categories, a = lhr.audits;
  rows.push([p, ...["performance", "accessibility", "best-practices", "seo"].map((k) => Math.round(c[k].score * 100)),
    a["first-contentful-paint"].displayValue, a["largest-contentful-paint"].displayValue,
    a["total-blocking-time"].displayValue, a["cumulative-layout-shift"].displayValue]);
}
console.log("\n| page | perf | a11y | best practices | SEO | FCP | LCP | TBT | CLS |\n|---|---|---|---|---|---|---|---|---|");
for (const r of rows) console.log(`| ${r.join(" | ")} |`);
