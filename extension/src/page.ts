import { ensureChip, removeChips, updateChip } from "./chip";
import { markStarterIssues, removeStarterMarks } from "./issues";
import { isIssueListPath, parseRepo, repoKey } from "./repo";
import type { Lookup, LookupKind, Report, Repo, StarterIssues } from "./types";

export type LookupFn = <K extends LookupKind>(
  kind: K,
  r: Repo,
) => Promise<Lookup<K extends "report" ? Report : StarterIssues>>;

/**
 * Keeps the page decorated as the user moves around GitHub. `sync()` is cheap
 * and idempotent, so callers run it on every navigation or DOM change. Each
 * repo is looked up at most once per page session.
 */
export function createPageController(doc: Document, lookup: LookupFn) {
  const reports = new Map<string, Promise<Lookup<Report>>>();
  const settledReports = new Map<string, Lookup<Report>>();
  const starters = new Map<string, Promise<Lookup<StarterIssues>>>();
  const settledStarters = new Map<string, Lookup<StarterIssues>>();

  function getReport(r: Repo): Promise<Lookup<Report>> {
    const key = repoKey(r);
    let p = reports.get(key);
    if (!p) {
      p = lookup("report", r).catch((): Lookup<Report> => ({ state: "error" }));
      p.then((res) => settledReports.set(key, res));
      reports.set(key, p);
    }
    return p;
  }

  function getStarters(r: Repo): Promise<Lookup<StarterIssues>> {
    const key = repoKey(r);
    let p = starters.get(key);
    if (!p) {
      p = lookup("starter-issues", r).catch((): Lookup<StarterIssues> => ({ state: "error" }));
      p.then((res) => settledStarters.set(key, res));
      starters.set(key, p);
    }
    return p;
  }

  /** Returns a promise that settles once any lookups this call started have been applied. */
  function sync(pathname: string): Promise<void> {
    const r = parseRepo(pathname);
    if (!r) {
      removeChips(doc);
      removeStarterMarks(doc);
      return Promise.resolve();
    }
    const key = repoKey(r);
    const work: Promise<void>[] = [];

    const known = settledReports.get(key);
    const chip = ensureChip(doc, r, known ?? { state: "loading" });
    if (chip && known) {
      if (chip.dataset.holtState !== known.state) updateChip(chip, r, known);
    } else if (chip) {
      work.push(
        getReport(r).then((res) => {
          // If GitHub re-rendered the header meanwhile, the next sync() puts
          // back a chip from settledReports.
          if (chip.isConnected) updateChip(chip, r, res);
        }),
      );
    }

    if (isIssueListPath(pathname)) {
      const s = settledStarters.get(key);
      if (s) {
        if (s.state === "found") markStarterIssues(doc, r, s.data.issues ?? []);
      } else {
        work.push(
          getStarters(r).then((res) => {
            if (res.state === "found") markStarterIssues(doc, r, res.data.issues ?? []);
          }),
        );
      }
    } else {
      removeStarterMarks(doc);
    }
    return Promise.all(work).then(() => undefined);
  }

  return { sync };
}
