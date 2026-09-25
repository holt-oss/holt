// Records Holt demo clips with Playwright's video capture.
//
//   node scripts/record-demo/record.mjs [desktop|phone|trick ...]
//
// Env:
//   HOLT_URL        site to record (default https://holt-new.aahil-khan.xyz)
//   OUT_DIR         where raw .webm files go (default scripts/record-demo/out)
//   PLAYWRIGHT_CORE path to a playwright-core package (default: resolve it, then ~/.local/share/cx-tools)
//   CHROMIUM_PATH   browser binary (default: newest cached headless shell in ~/.cache/ms-playwright)
//
// One browser, one clip at a time; the browser is always closed. Then run
// scripts/record-demo/encode.sh to make the mp4/gif files in assets/.
import { createRequire } from "node:module";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const require = createRequire(import.meta.url);
const HOLT_URL = (process.env.HOLT_URL || "https://holt-new.aahil-khan.xyz").replace(/\/$/, "");
const HOST = new URL(HOLT_URL).host;
const OUT = path.resolve(process.env.OUT_DIR || path.join(path.dirname(new URL(import.meta.url).pathname), "out"));
const REPO_URL = "https://github.com/pallets/flask";

function loadPlaywright() {
  const candidates = [process.env.PLAYWRIGHT_CORE, "playwright-core", path.join(os.homedir(), ".local/share/cx-tools/node_modules/playwright-core")];
  for (const c of candidates.filter(Boolean)) {
    try {
      return require(c);
    } catch {}
  }
  throw new Error("playwright-core not found; set PLAYWRIGHT_CORE");
}

function chromiumPath() {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH;
  const cache = path.join(os.homedir(), ".cache/ms-playwright");
  const found = fs
    .readdirSync(cache)
    .filter((d) => d.startsWith("chromium_headless_shell-"))
    .sort()
    .reverse()
    .map((d) => path.join(cache, d, "chrome-headless-shell-linux64/chrome-headless-shell"))
    .find((p) => fs.existsSync(p));
  if (!found) throw new Error("no cached Chromium; set CHROMIUM_PATH");
  return found;
}

const SIZES = {
  desktop: { viewport: { width: 1280, height: 720 }, scale: 1, mobile: false },
  phone: { viewport: { width: 390, height: 844 }, scale: 2, mobile: true },
};

const wait = (page, ms) => page.waitForTimeout(ms);

async function smoothScrollTo(page, selector, offset = 90) {
  await page.evaluate(
    ([sel, off]) => {
      const el = document.querySelector(sel);
      if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - off, behavior: "smooth" });
    },
    [selector, offset],
  );
}

async function smoothScrollBy(page, dy) {
  await page.evaluate((d) => window.scrollBy({ top: d, behavior: "smooth" }), dy);
}

/** landing → paste a GitHub URL → report → starter issues → /hacktoberfest (Python). */
async function mainFlow(page, mobile) {
  await page.goto(HOLT_URL, { waitUntil: "networkidle" });
  await wait(page, 2200);
  const input = page.locator("#repo-input");
  await input.click();
  await input.pressSequentially(REPO_URL, { delay: 45 });
  await wait(page, 500);
  await input.press("Enter");
  // A cached report renders at once; an uncached one streams its stages first.
  const reportFrom = at();
  await page.waitForSelector("#issues", { timeout: 180_000 });
  if (at() - reportFrom > 8) cuts.push([reportFrom + 4, at() - 0.5]);
  await wait(page, 3500);
  await smoothScrollTo(page, "#issues");
  await wait(page, 3500);
  await smoothScrollBy(page, mobile ? 700 : 450);
  await wait(page, 2500);
  await page.goto(`${HOLT_URL}/hacktoberfest?lang=python`, { waitUntil: "domcontentloaded" });
  const waitFrom = at();
  await page.waitForSelector("text=Pick one of these", { timeout: 180_000 });
  // Keep ~2 s of "searching…", cut the rest.
  if (at() - waitFrom > 4) cuts.push([waitFrom + 2, at() - 0.3]);
  await wait(page, 1500);
  await smoothScrollTo(page, 'nav[aria-label="Language"]', mobile ? 70 : 80);
  await wait(page, 3000);
  await smoothScrollBy(page, mobile ? 600 : 400);
  await wait(page, 2500);
}

/** A drawn address bar: swap github.com for our host, then land on the real page. */
async function trickFlow(page) {
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  await page.setContent(`<!doctype html><html><body style="margin:0;background:#0d0e0e;color:#e7e5dc;font:34px 'JetBrains Mono','DejaVu Sans Mono',ui-monospace,monospace;display:grid;place-items:center;height:100vh">
    <div style="width:min(1180px,94vw)">
      <p style="color:#a3a39b;font-size:26px;margin:0 0 26px">Already on GitHub? Change one word.</p>
      <div style="display:flex;gap:14px;align-items:center;border:1px solid #3b3e3a;border-radius:999px;padding:26px 34px;background:#141615">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#8a8a83" stroke-width="2" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg><span id="u"><span style="color:#8a8a83">https://</span><span id="h" style="color:#e7e5dc">github.com</span><span>/pallets/flask</span></span><span id="c" style="display:inline-block;width:2px;height:40px;background:#83a9ff"></span>
      </div>
    </div></body></html>`);
  await wait(page, 1800);
  // "select" github.com, delete it, type the host
  await page.evaluate(() => {
    const h = document.getElementById("h");
    h.style.background = "#83a9ff";
    h.style.color = "#0d0e0e";
  });
  await wait(page, 700);
  await page.evaluate(() => {
    const h = document.getElementById("h");
    h.textContent = "";
    h.style.background = "transparent";
    h.style.color = "#69c7a6";
  });
  for (const ch of HOST) {
    await page.evaluate((c) => (document.getElementById("h").textContent += c), esc(ch));
    await wait(page, 70);
  }
  await wait(page, 1100);
  await page.goto(`${HOLT_URL}/github.com/pallets/flask`, { waitUntil: "networkidle" });
  await page.waitForSelector("#issues", { timeout: 120_000 });
  await wait(page, 4000);
}

async function record(chromium, exe, name, sizeKey, flow) {
  const s = SIZES[sizeKey];
  const dir = path.join(OUT, `${name}-tmp`);
  fs.rmSync(dir, { recursive: true, force: true });
  const browser = await chromium.launch({ executablePath: exe });
  try {
    const ctx = await browser.newContext({
      viewport: s.viewport,
      deviceScaleFactor: s.scale,
      isMobile: s.mobile,
      hasTouch: s.mobile,
      colorScheme: "dark",
      recordVideo: { dir, size: { width: s.viewport.width * s.scale, height: s.viewport.height * s.scale } },
    });
    await ctx.addInitScript(() => {
      try {
        localStorage.setItem("holt-theme", "dark");
      } catch {}
    });
    const page = await ctx.newPage();
    clipStart = Date.now();
    cuts.length = 0;
    await flow(page, s.mobile);
    const video = page.video();
    await ctx.close();
    const raw = path.join(OUT, `${name}.webm`);
    fs.renameSync(await video.path(), raw);
    fs.writeFileSync(path.join(OUT, `${name}.cuts.json`), JSON.stringify(cuts));
    fs.rmSync(dir, { recursive: true, force: true });
    console.log(raw);
  } finally {
    await browser.close();
  }
}

/**
 * Make sure the Python find has run once, with a single request: load the
 * page, and if the find is queued, follow that one job's events until it is
 * done. Never poll the page itself: every load of /hacktoberfest starts a
 * find, and the server rate-limits anonymous work per IP.
 */
async function warm() {
  const url = `${HOLT_URL}/hacktoberfest?lang=python`;
  const html = await fetch(url).then((r) => r.text()).catch(() => "");
  if (html.includes("Pick one of these")) return console.log("warm: find already cached");
  if (html.includes("Too many checks")) throw new Error("staging is rate-limiting this IP; try again later");
  const job = html.match(/jobId\\?"?:\\?"([A-Za-z0-9_-]{1,64})/)?.[1];
  if (!job) return console.log("warm: no job id found; recording will show the wait");
  const res = await fetch(`${HOLT_URL}/api/find/${job}/events`, { signal: AbortSignal.timeout(180_000) }).catch(() => null);
  const text = res ? await res.text().catch(() => "") : "";
  console.log(`warm: find ${job} ${text.includes("event: done") ? "done" : "did not finish"}`);
}

/** Seconds (from the start of the clip) to cut: long waits for data. */
const cuts = [];
let clipStart = 0;
const at = () => (Date.now() - clipStart) / 1000;

await warm();
const { chromium } = loadPlaywright();
const exe = chromiumPath();
fs.mkdirSync(OUT, { recursive: true });
const want = process.argv.slice(2).length ? process.argv.slice(2) : ["desktop", "phone", "trick"];
if (want.includes("desktop")) await record(chromium, exe, "demo-desktop", "desktop", mainFlow);
if (want.includes("phone")) await record(chromium, exe, "demo-phone", "phone", mainFlow);
if (want.includes("trick")) await record(chromium, exe, "url-trick", "desktop", trickFlow);
