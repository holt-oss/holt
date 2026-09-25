// Lighthouse (mobile) for the key pages, one run at a time, with the cached Chromium.
//   node lighthouse.mjs                         # staging: /, /pallets/flask, /find
//   node lighthouse.mjs --runs 3 --calibrate    # median of 3, CPU slowdown calibrated
//   BASE_URL=http://127.0.0.1:3000 node lighthouse.mjs / /find
//
// Lighthouse's default 4x CPU slowdown assumes a high-end desktop host
// (benchmarkIndex 1500-2000). On a slower or busy host that emulates a
// low-end phone instead. --calibrate reads the benchmarkIndex of each run
// and picks the multiplier from Lighthouse's docs (docs/throttling.md) for
// a mid-tier phone target: >=1500 -> 4x, 1000-1500 -> 2x, <1000 -> 1x.
// Each run waits until the 1-minute load is under LH_MAX_LOAD (default 4,
// up to 10 minutes). Reports go to lighthouse/<page>-<n>.json.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const argv = process.argv.slice(2);
const flag = (f) => { const i = argv.indexOf(f); if (i < 0) return false; argv.splice(i, 1); return true; };
const opt = (f, d) => { const i = argv.indexOf(f); if (i < 0) return d; const v = argv[i + 1]; argv.splice(i, 2); return v; };
const calibrate = flag("--calibrate");
const runs = Number(opt("--runs", 1));
const fixedCpu = opt("--cpu", null);
const base = (process.env.BASE_URL || "https://holt-new.aahil-khan.xyz").replace(/\/$/, "");
const pages = argv.length ? argv : ["/", "/pallets/flask", "/find"];
const maxLoad = Number(process.env.LH_MAX_LOAD || 4);

function chrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.homedir(), ".cache/ms-playwright");
  const dir = fs.readdirSync(cache).filter((d) => d.startsWith("chromium-")).sort().reverse()[0];
  return dir && path.join(cache, dir, "chrome-linux64/chrome");
}

function waitForQuiet() {
  for (let waited = 0; waited < 600; waited += 15) {
    if (os.loadavg()[0] < maxLoad) return;
    if (waited === 0) console.error(`waiting for load < ${maxLoad} (now ${os.loadavg()[0].toFixed(1)})`);
    spawnSync("sleep", ["15"]);
  }
  console.error(`host still busy (load ${os.loadavg()[0].toFixed(1)}); measuring anyway`);
}

const multiplierFor = (bi) => (bi >= 1500 ? 4 : bi >= 1000 ? 2 : 1);

function lighthouse(url, out, cpu) {
  waitForQuiet();
  const args = ["-y", "lighthouse@13", url, "--quiet", "--output=json", `--output-path=${out}`,
    "--only-categories=performance,accessibility,best-practices,seo",
    "--chrome-flags=--headless=new --no-sandbox --disable-gpu"];
  if (cpu) args.push(`--throttling.cpuSlowdownMultiplier=${cpu}`);
  const r = spawnSync("npx", args, { stdio: ["ignore", "ignore", "inherit"], env: { ...process.env, CHROME_PATH: chrome() } });
  return r.status === 0 && fs.existsSync(out) ? JSON.parse(fs.readFileSync(out, "utf-8")) : null;
}

fs.mkdirSync("lighthouse", { recursive: true });
const median = (xs) => { const a = [...xs].sort((x, y) => x - y); return a[Math.floor(a.length / 2)]; };
const rows = [];
for (const p of pages) {
  const slug = p.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "") || "home";
  const results = [];
  for (let n = 1; n <= runs; n++) {
    let lhr = lighthouse(base + p, path.join("lighthouse", `${slug}-${n}.json`), fixedCpu);
    if (lhr && calibrate) {
      const cpu = multiplierFor(lhr.environment.benchmarkIndex);
      if (cpu !== 4) lhr = lighthouse(base + p, path.join("lighthouse", `${slug}-${n}-cal.json`), cpu);
    }
    if (lhr) results.push(lhr);
  }
  if (!results.length) { rows.push([p, "failed"]); continue; }
  // The run with the median performance score stands for the page.
  const perf = (l) => l.categories.performance.score;
  const lhr = results.find((l) => perf(l) === median(results.map(perf)));
  const c = lhr.categories, a = lhr.audits;
  rows.push([p, ...["performance", "accessibility", "best-practices", "seo"].map((k) => Math.round(c[k].score * 100)),
    a["first-contentful-paint"].displayValue, a["largest-contentful-paint"].displayValue,
    a["total-blocking-time"].displayValue, a["cumulative-layout-shift"].displayValue,
    `${lhr.configSettings.throttling.cpuSlowdownMultiplier}x`, Math.round(lhr.environment.benchmarkIndex),
    results.map((l) => Math.round(perf(l) * 100)).join("/")]);
}
console.log("\n| page | perf | a11y | best practices | SEO | FCP | LCP | TBT | CLS | CPU | benchmark | perf, all runs |\n|---|---|---|---|---|---|---|---|---|---|---|---|");
for (const r of rows) console.log(`| ${r.join(" | ")} |`);
