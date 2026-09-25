// Shapes the extension reads from the Holt public API. They are a subset of the
// Report and StarterIssue objects in API.md; everything else is ignored.

export type Verdict = "viable" | "not_viable" | "insufficient_evidence";

export interface Report {
  repo: string;
  verdict: Verdict;
  headline?: string;
  stats?: {
    outsider_attempts?: number;
    outsider_merged?: number;
  } | null;
}

export interface StarterIssue {
  number: number;
  title?: string;
  url?: string;
  why?: string[];
}

export interface StarterIssues {
  repo: string;
  issues: StarterIssue[];
}

/** What the background worker answers for one lookup. */
export type Lookup<T> =
  | { state: "found"; data: T }
  | { state: "missing" } // 404: nothing cached for this repo yet
  | { state: "error" }; // network, 5xx, bad JSON

export type LookupKind = "report" | "starter-issues";

export interface LookupMessage {
  type: "holt:lookup";
  kind: LookupKind;
  owner: string;
  repo: string;
}

export interface Repo {
  owner: string;
  repo: string;
}
