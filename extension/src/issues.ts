import type { Repo, StarterIssue } from "./types";

export const STARTER_CLASS = "holt-starter";

/**
 * Marks issue title links on an issue list that appear in Holt's starter-issue
 * list. Returns how many links it marked this call. Idempotent.
 */
export function markStarterIssues(doc: Document, r: Repo, issues: StarterIssue[]): number {
  const byNumber = new Map<number, StarterIssue>();
  for (const i of issues) if (Number.isInteger(i.number)) byNumber.set(i.number, i);
  if (byNumber.size === 0) return 0;

  const prefix = `/${r.owner}/${r.repo}/issues/`.toLowerCase();
  let marked = 0;
  for (const a of Array.from(doc.querySelectorAll<HTMLAnchorElement>("a[href]"))) {
    if (a.dataset.holtStarter !== undefined || a.closest(`.${STARTER_CLASS}`)) continue;
    const n = issueNumber(a, prefix);
    if (n === null || !isTitleLink(a)) continue;
    const issue = byNumber.get(n);
    if (!issue) continue;
    a.dataset.holtStarter = String(n);
    a.after(starterBadge(doc, issue));
    marked++;
  }
  return marked;
}

function issueNumber(a: HTMLAnchorElement, prefix: string): number | null {
  let url: URL;
  try {
    url = new URL(a.getAttribute("href")!, "https://github.com");
  } catch {
    return null;
  }
  if (url.hostname !== "github.com" || url.hash) return null;
  const path = url.pathname.toLowerCase();
  if (!path.startsWith(prefix)) return null;
  const rest = path.slice(prefix.length);
  return /^[1-9]\d*$/.test(rest) ? Number(rest) : null;
}

// Issue rows link to the same issue several times (title, comment count,
// linked PRs). Only the title link gets a badge: it is the one GitHub marks as
// such, or failing that, the one whose text is not just "#123" or a number.
function isTitleLink(a: HTMLAnchorElement): boolean {
  if (a.matches("[data-testid='issue-pr-title-link'], a[id^='issue_'][id$='_link'], .js-navigation-open")) {
    return true;
  }
  const text = (a.textContent ?? "").trim();
  return text.length > 0 && !/^#?\d+$/.test(text);
}

function starterBadge(doc: Document, issue: StarterIssue): HTMLSpanElement {
  const s = doc.createElement("span");
  s.className = STARTER_CLASS;
  s.textContent = "Holt pick";
  const why = (issue.why ?? []).filter((w) => typeof w === "string").slice(0, 3);
  s.title = why.length ? `Good for a first contribution: ${why.join("; ")}` : "Good for a first contribution";
  return s;
}

export function removeStarterMarks(doc: Document): void {
  doc.querySelectorAll(`.${STARTER_CLASS}`).forEach((s) => s.remove());
  doc.querySelectorAll<HTMLElement>("[data-holt-starter]").forEach((a) => delete a.dataset.holtStarter);
}
