// Content script for github.com. Wires the page controller to navigation and
// to the background worker, which does the actual fetching (content scripts
// cannot make cross-origin requests with the extension's host permission).
import { createPageController, type LookupFn } from "./page";
import type { LookupMessage } from "./types";

const lookup: LookupFn = (kind, r) =>
  new Promise((resolve) => {
    const msg: LookupMessage = { type: "holt:lookup", kind, owner: r.owner, repo: r.repo };
    try {
      chrome.runtime.sendMessage(msg, (res) => {
        // Reading lastError marks it handled (e.g. the extension was reloaded).
        if (chrome.runtime.lastError || !res) resolve({ state: "error" });
        else resolve(res);
      });
    } catch {
      resolve({ state: "error" });
    }
  });

const page = createPageController(document, lookup);
let queued = false;

function schedule(): void {
  if (queued) return;
  queued = true;
  setTimeout(() => {
    queued = false;
    void page.sync(location.pathname);
  }, 100);
}

// GitHub navigates client-side (Turbo, and React routes that fire no event), so
// besides the known events we watch the DOM and re-sync; sync() is idempotent.
for (const ev of ["turbo:load", "turbo:render", "pjax:end", "popstate"]) {
  addEventListener(ev, schedule);
}
new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
schedule();
