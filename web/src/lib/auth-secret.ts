/**
 * The secret Auth.js signs sessions with. In development a missing or empty
 * AUTH_SECRET (`.env.example` ships it empty) falls back to a fixed dev value;
 * anywhere else it stays unset, so Auth.js refuses to run without one.
 */
export function authSecret(env: { AUTH_SECRET?: string; NODE_ENV?: string }): string | undefined {
  if (env.AUTH_SECRET) return env.AUTH_SECRET;
  return env.NODE_ENV === "development" ? "holt-dev-only-secret" : undefined;
}
