import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/** The newest cached Chromium: CHROMIUM_PATH, else full chromium, else the headless shell. */
export function chromiumPath(): string | undefined {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH;
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.homedir(), ".cache/ms-playwright");
  if (!fs.existsSync(cache)) return undefined;
  const pick = (prefix: string, rels: string[]) =>
    fs.readdirSync(cache)
      .filter((d) => d.startsWith(prefix))
      .sort()
      .reverse()
      .flatMap((d) => rels.map((r) => path.join(cache, d, r)))
      .find((p) => fs.existsSync(p));
  return (
    pick("chromium-", ["chrome-linux64/chrome", "chrome-linux/chrome"]) ||
    pick("chromium_headless_shell-", ["chrome-headless-shell-linux64/chrome-headless-shell", "chrome-linux/headless_shell"])
  );
}
