// Builds dist/chrome and dist/firefox. HOLT_HOST (default holt.aahil-khan.xyz)
// sets where reports come from, e.g. HOLT_HOST=localhost:20080 npm run build.
import { build } from "esbuild";
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const host = process.env.HOLT_HOST || "holt.aahil-khan.xyz";
if (!/^[a-z0-9.-]+(:\d{1,5})?$/i.test(host)) {
  console.error(`HOLT_HOST must be a bare host name like holt.example.com, got "${host}"`);
  process.exit(1);
}
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf-8"));
const hostPattern = `https://${host.replace(/:\d+$/, "")}/*`;

function manifest(browser) {
  const m = {
    manifest_version: 3,
    name: "Holt for GitHub",
    short_name: "Holt",
    version: pkg.version,
    description: "See on any GitHub repo whether newcomers get their pull requests merged.",
    icons: { 16: "icons/16.png", 32: "icons/32.png", 48: "icons/48.png", 128: "icons/128.png" },
    permissions: [],
    host_permissions: ["https://github.com/*", hostPattern],
    content_scripts: [
      {
        matches: ["https://github.com/*"],
        js: ["content.js"],
        css: ["content.css"],
        run_at: "document_idle",
      },
    ],
  };
  if (browser === "firefox") {
    m.background = { scripts: ["background.js"] };
    m.browser_specific_settings = {
      gecko: {
        id: "holt@aahil-khan.xyz",
        strict_min_version: "121.0",
        // The owner/repo of GitHub pages you visit is sent to the Holt host.
        data_collection_permissions: { required: ["browsingActivity"] },
      },
    };
  } else {
    m.background = { service_worker: "background.js" };
    m.minimum_chrome_version = "102";
  }
  return m;
}

for (const browser of ["chrome", "firefox"]) {
  const out = join(root, "dist", browser);
  rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
  await build({
    entryPoints: { content: join(root, "src/content.ts"), background: join(root, "src/background.ts") },
    outdir: out,
    bundle: true,
    format: "iife",
    target: browser === "firefox" ? "firefox121" : "chrome102",
    minify: false,
    legalComments: "none",
    define: { __HOLT_HOST__: JSON.stringify(host) },
    logLevel: "warning",
  });
  cpSync(join(root, "src/content.css"), join(out, "content.css"));
  cpSync(join(root, "icons"), join(out, "icons"), { recursive: true });
  writeFileSync(join(out, "manifest.json"), JSON.stringify(manifest(browser), null, 2) + "\n", "utf-8");
  console.log(`built dist/${browser} for ${host}`);
}
