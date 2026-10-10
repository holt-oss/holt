// What /signin says when Auth.js sends someone back with ?error=<code>.
// Auth.js v5 passes only a few codes to the page (the rest become
// "Configuration"); the v4 names are kept because old links still carry them.
// And its heading, worded from where sign-in leads back to.
// Pure, so it runs under `node --test`.
import { isAppRoute } from "./app-routes.ts";
import { picksFromQuery } from "./find-picks.ts";
import { LANGS, MORE_LANGS } from "./profile.ts";
import { isValidRepo } from "./repo.ts";
import { safeCallback } from "./safe-url.ts";

export interface SignInNotice {
  /** "info" for a nudge (you need to sign in), "error" when sign-in failed. */
  tone: "info" | "error";
  title: string;
  body?: string;
}

const LINKED: SignInNotice = {
  tone: "error",
  title: "That email already has a Holt account",
  body: "It was made with the other sign-in button. Use that one instead.",
};
const UNFINISHED: SignInNotice = {
  tone: "error",
  title: "Sign-in didn't finish",
  body: "GitHub or Google didn't hand you back to Holt. Try again. If it keeps failing, try the other button.",
};
const OUR_SIDE: SignInNotice = {
  tone: "error",
  title: "Sign-in is broken on our side",
  body: "It's not something you did. Try again in a few minutes.",
};
const FALLBACK: SignInNotice = {
  tone: "error",
  title: "Sign-in didn't work",
  body: "Try again. If it keeps failing, try the other button.",
};

const NOTICES: Record<string, SignInNotice> = {
  OAuthAccountNotLinked: LINKED,
  AccountNotLinked: LINKED,
  AccessDenied: {
    tone: "error",
    title: "Sign-in was cancelled",
    body: "Nothing was shared with Holt. Try again when you're ready.",
  },
  OAuthCallbackError: UNFINISHED,
  OAuthCallback: UNFINISHED,
  OAuthSignInError: UNFINISHED,
  OAuthSignin: UNFINISHED,
  OAuthCreateAccount: UNFINISHED,
  Callback: UNFINISHED,
  MissingCSRF: {
    tone: "error",
    title: "Your browser dropped a sign-in cookie",
    body: "This happens when the page sat open a long time or cookies are blocked. Reload the page and try again.",
  },
  Verification: {
    tone: "error",
    title: "That sign-in link has expired",
    body: "Links work once and only for a short time. Start again below.",
  },
  Configuration: OUR_SIDE,
  AdapterError: OUR_SIDE,
  SessionRequired: {
    tone: "info",
    title: "Sign in to see that page",
  },
};

/** The notice for an Auth.js `?error=` value, or null when there is none. */
export function signInNotice(error: string | string[] | undefined | null): SignInNotice | null {
  const code = Array.isArray(error) ? error[0] : error;
  if (!code) return null;
  return Object.hasOwn(NOTICES, code) ? NOTICES[code] : FALLBACK;
}

export const SIGN_IN_HEADING = "Sign in to Holt";
// A longer repo name than this would crowd the card; it gets the plain heading.
const MAX_REPO = 50;

/**
 * The sign-in page's heading, from its `callbackUrl`: the repo a check waits
 * on, or the language a Find search does. The callback is anyone's to write,
 * so it only ever picks between these wordings: a report path whose owner and
 * name are valid GitHub ones, or /find with one language Holt lists. Anything
 * else gets the plain heading.
 */
export function signInHeading(callbackUrl: string | string[] | undefined | null): string {
  const to = safeCallback(callbackUrl, "");
  if (!to) return SIGN_IN_HEADING;
  const { pathname, search } = new URL(to, "http://holt.invalid");
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 2 && !isAppRoute(parts[0]) && isValidRepo(parts[0], parts[1]) && pathname.length - 1 <= MAX_REPO) {
    return `Sign in to check ${parts[0]}/${parts[1]}`;
  }
  if (pathname === "/find") {
    const langs = picksFromQuery(search.slice(1))?.langs ?? [];
    const name = langs.length === 1 ? [...LANGS, ...MORE_LANGS].find((l) => l.toLowerCase() === langs[0]) : undefined;
    if (name) return `Sign in to search ${name} projects`;
  }
  return SIGN_IN_HEADING;
}
