// Types for the Holt HTTP API. Source of truth: API.md at the repo root.

export type Mode = "rules" | "ai";
export type Verdict = "viable" | "not_viable" | "insufficient_evidence";

export type ApiErrorCode =
  | "unauthorized"
  | "not_found"
  | "invalid_repo"
  | "invalid_request"
  | "rate_limited"
  | "quota_exceeded"
  | "needs_key"
  | "upstream"
  | "internal"
  | "not_implemented"
  | "invalid_signature"
  | "already_subscribed";

export interface ApiError {
  code: ApiErrorCode;
  message: string;
  retry_after?: number;
}

export interface Stats {
  outsider_attempts: number;
  outsider_merged: number;
  distinct_outsiders: number;
  first_time_merged_authors: number;
  no_reply: number;
  median_first_response_hours: number | null;
  bot_share: number;
}

export interface LandingPath {
  path: string;
  merged: number;
  attempted: number;
}

export interface EvidenceItem {
  id: string;
  url: string;
  kind: string;
  value: string;
  text: string;
  quote: string | null;
}

export interface Report {
  repo: string;
  mode: Mode;
  days: number;
  verdict: Verdict;
  headline: string;
  summary: string | null;
  stats: Stats;
  decided_by: string[];
  unknowns: string[];
  landing: LandingPath[];
  never_landed: { path: string; attempted: number }[];
  evidence: EvidenceItem[];
  evidence_until: string;
  generated_at: string;
  cost: { model: string; input_tokens: number; output_tokens: number } | null;
}

export interface StarterIssue {
  number: number;
  title: string;
  url: string;
  labels: string[];
  created_at: string;
  comments: number;
  why: string[];
}

export type AnalysisStart =
  | { status: "done"; report: Report }
  | { status: "queued"; job_id: string };

export interface JobStatus {
  status: "queued" | "running" | "done" | "error";
  stage: string;
  progress: number;
  report: Report | null;
  error: ApiError | null;
}

export interface FindQuery {
  languages: string[];
  topics: string[];
  days: number;
  hacktoberfest: boolean;
  limit: number;
}

export interface FindResult {
  repo: string;
  headline: string;
  verdict: Verdict;
  stats: Partial<Stats>;
  issues: StarterIssue[];
  /** Not in API.md v0; shown when present. */
  description?: string;
  language?: string;
  stars?: number;
}

export type FindStart = { status: "done"; results: FindResult[] } | { status: "queued"; job_id: string };

export interface FindJobStatus {
  status: "queued" | "running" | "done" | "error";
  stage: string;
  progress: number;
  results: FindResult[] | null;
  error: ApiError | null;
}

export type ByokProvider = "openrouter" | "openai" | "anthropic" | "gemini";

export interface Me {
  /** "free" | "student" | "pro" (ids come from the server's plans config) */
  plan: string;
  plan_name: string;
  /** Next charge, while the subscription renews. */
  renews_at: string | null;
  /** When paid access stops (cancelled or halted). */
  ends_at: string | null;
  /** One-time report credits; never expire. */
  pack_credits: number;
  quota: { ai_used: number; ai_limit: number; resets_at: string };
  byok: { provider: ByokProvider; model: string; set: boolean } | null;
}

// ---- Billing (API.md "Billing") -------------------------------------------

export interface Price {
  currency: string;
  /** Minor units: paise for INR, cents for USD. */
  amount: number;
  interval?: string;
  /** Optional wording from the server's plans config, e.g. GST. */
  tax_note?: string;
}

export interface Plan {
  id: string;
  name: string;
  ai_reports_per_month: number;
  priority: boolean;
  features: string[];
  prices: Price[];
}

export interface Pack {
  id: string;
  name: string;
  reports: number;
  prices: Price[];
}

export interface Plans {
  plans: Plan[];
  packs: Pack[];
  byok: { price: number; unlimited: boolean };
  /** null: payments are not set up on this server. */
  provider: "razorpay" | null;
  tax_note?: string;
}

export type BillingItem = { plan: string } | { pack: string };

interface CheckoutBase {
  provider: "razorpay";
  key_id: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
}
export type Checkout =
  | (CheckoutBase & { kind: "order"; order_id: string })
  | (CheckoutBase & { kind: "subscription"; subscription_id: string; short_url?: string });

/** Exactly what Razorpay Checkout's success handler returns. */
export interface RazorpaySuccess {
  razorpay_payment_id: string;
  razorpay_signature: string;
  razorpay_order_id?: string;
  razorpay_subscription_id?: string;
}

export interface VerifyResult {
  status: string;
  me: Me;
}

/** GET /v1/me/history -> {"items": HistoryItem[]} */
export interface HistoryItem {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  repo: string;
  mode: Mode;
  days: number;
  verdict: Verdict | null;
  headline: string | null;
  created_at: string;
}

/** Result of a call: either data or a plain-English error. */
export type Result<T> = { ok: true; data: T } | { ok: false; error: ApiError; status: number };
