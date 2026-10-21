// Types for the Holt HTTP API (API.md). The shapes come from the server's
// pydantic models via ./api-schema.ts, which is generated: change the server
// (server/holt_server/schema.py) and run server/scripts/api_types.sh.
import type * as S from "./api-schema";

export type Report = S.Report;
export type Stats = S.Stats;
export type LandingPath = S.LandingPath;
export type EvidenceItem = S.EvidenceItem;
export type Odds = S.Odds;
export type Counted = S.Counted;
export type StarterIssue = S.StarterIssue;
export type RepoSearch = S.RepoSearch;
export type RepoHit = S.RepoHit;
export type FindResult = S.FindResult;
// The web always sends every field; the server has defaults for them.
export type FindQuery = Required<S.FindIn>;
export type JobStatus = S.JobStatus;
export type FindJobStatus = S.FindJobStatus;
export type Me = S.Me;
export type History = S.History;
export type HistoryItem = S.HistoryItem;
export type GitHubConnection = S.GitHubConnection;
export type Contributions = S.Contributions;
export type ContributionPR = S.ContributionPullRequest;
export type AlertAccess = S.AlertAccess;
export type AlertItem = S.AlertItem;
export type AlertList = S.AlertList;
export type AlertCount = S.AlertCount;
export type AlertSettings = S.AlertSettings;
// Only the fields sent change, so every one is optional (the generated type marks the body's default too).
export type AlertSettingsBody = S.AlertSettingsBody;
export type Unsubscribed = S.Unsubscribed;
export type ApiError = S.Error;
export type FeedbackOut = S.FeedbackOut;
export type DiscoverOut = S.DiscoverOut;
export type DiscoverRepo = S.DiscoverRepo;
export type DiscoverSort = S.DiscoverOut["sort"];
export type ProfileOut = S.ProfileOut;
export type ProfilePrefs = S.ProfilePrefs;
export type Recommendations = S.Recommendations;
export type Recommendation = S.Recommendation;
export type RecommendationBasis = S.RecommendationBasis;
export type SavedList = S.SavedList;
export type SavedItem = S.SavedItem;
export type SavedState = S.SavedState;
export type ContributionType = ProfilePrefs["contributions"][number];
export type Level = ProfilePrefs["level"];

export type Mode = Report["mode"];
export type Verdict = Report["verdict"];
/** The colour of a verdict or of the odds, chosen by the server. */
export type Tone = Report["tone"];
export type ApiErrorCode = ApiError["code"];
export type Credits = S.Credits;
export type Pass = S.PassOffer;
export type PassPrice = S.PassPrice;
export type PassFeature = S.PassFeature;
export type Passes = S.Passes;
export type Checkout = S.Checkout;
export type Order = S.Order;
export type OrderConfirmed = S.OrderConfirmed;
/** What Razorpay Checkout hands the page after a successful payment. */
export interface RazorpaySuccess {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

export type Access = S.Access;
export type Entitlements = S.Entitlements;
export type Playbook = S.Playbook;
export type PlaybookItem = S.PlaybookItem;
export type PlaybookSource = S.PlaybookSource;
export type PlaybookClosingReason = S.PlaybookClosingReason;
export type PlaybookState = S.PlaybookState;
export type PlaybookSectionKey = S.PlaybookTeaserSection["key"];
export type Preflight = S.Preflight;
export type PreflightCheck = S.PreflightCheck;
export type PreflightState = S.PreflightState;
export type PreflightVerdict = S.PreflightCheck["verdict"];
export type PreflightFor = S.PreflightFor;
export type PreflightStart = S.Queued;
export type MergePlan = S.MergePlan;
export type MergePlanState = S.MergePlanState;
export type MergePlanStart = S.Queued;
export type AnalysisStart = S.AnalysisDone | S.Queued;
export type PlaybookStart = S.PlaybookDone | S.Queued;
export type FindStart = S.FindDone | S.FindQueued;
export type FindIndexPart = S.FindIndexPart;

/** Result of a call: either data or a plain-English error. */
export type Result<T> = { ok: true; data: T } | { ok: false; error: ApiError; status: number };
