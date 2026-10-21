# Holt web

The main Holt product: paste a GitHub repo, get a plain-English verdict on
whether a newcomer's pull request will get reviewed and merged.

Next.js 16 (App Router) · TypeScript · Tailwind 4 · Auth.js v5 (GitHub, Google)
· Postgres via Drizzle. The browser never calls the Holt API; server code does,
with `HOLT_API_URL` and `HOLT_INTERNAL_KEY` (contract: [`../API.md`](../API.md)).

## Run it

```sh
cd web
npm ci
cp .env.example .env.local          # MOCK_API=1 works without the API server
cp .env.local .env                  # compose reads HOLT_DB_PORT from .env
docker compose up -d db             # Postgres for users and sessions
npm run db:migrate
npm run dev -- -p $PORT
```

- **Mock API** (`MOCK_API=1`): realistic fixtures that follow API.md, including
  queued jobs that stream stages over SSE. `home-assistant/core`, `pallets/flask`,
  `NixOS/nixpkgs`, `psf/requests`, `pytorch/pytorch` and `vercel/next.js` are "cached" and load
  instantly, with the verdicts the real engine gave them (docs/DEV-WORKFLOW.md); any
  other repo runs a fake analysis (about 6 s, `MOCK_JOB_MS`). Repos named
  `*/private*` or `doesnotexist/*` return `not_found`. `MOCK_REPORT_MS=600`
  makes every report take that long to read, which is how to see the report
  page's loading screen (a report read in under 120 ms never shows one). Keep it for demos.
- **Sign-in**: set `AUTH_GITHUB_*` / `AUTH_GOOGLE_*` for OAuth. In development
  with neither set, `/signin` offers a dev-only sign-in that creates a real
  database session.
- **Site host**: `NEXT_PUBLIC_SITE_HOST` is the domain used in the
  "swap hub for holt" URL trick (github.com → githolt.com), badges, share links and OG images.

## Routes

| Path | What |
|---|---|
| `/` | Landing: paste box, find CTA, Hacktoberfest banner, URL trick |
| `/{owner}/{repo}` | Report. Signed in: starts a rules analysis if nothing is cached and streams progress. `?mode=ai` for the merge plan, `?days=` for the time budget. Signed out: the curated examples in full, any other repo as a teaser (verdict, reason, odds bar and one number; the rest locked behind sign-in). With nothing cached it runs the rules check first, for people only (never bots), with a ticket only this page mints and the server's per-IP limit; over the limit it asks for sign-in (`src/lib/gate.ts`, `src/lib/anon-check.ts`) |
| `/examples` | The curated example reports anyone can read without signing in (`src/lib/examples.ts`), plus the example merge plan |
| `/github.com/o/r`, `/https://github.com/o/r`, `/o/r/pulls`… | Redirect to `/o/r` (`src/proxy.ts`) |
| `/{owner}/{repo}/opengraph-image` | Per-repo share image |
| `/find` | Beginner flow: languages, time, Hacktoberfest → welcoming repos + starter issues |
| `/compare?repos=a/b,c/d` | Up to 4 repos side by side |
| `/example-merge-plan` | A recorded merge plan for processing/p5.js, readable without signing in; `?view=locked` shows it before unlocking. Static: `src/lib/example-merge-plan.json` |
| `/signin`, `/settings`, `/pricing`, `/me/repos`, `/how-it-works` | Account, plan and purchases, pricing, history, methodology |
| `/me/picks` | Every pick, the home's cards with each one's reason, loaded in parts as you scroll like a board's (`GET /api/picks?cursor=N`). The home (`/me`) shows the first three. `/for-you` is the old address. Picked for you: repos Holt rates Worth your time that match the profile and merged pull requests, with reasons and starter issues (`GET /v1/me/recommendations`). Free for everyone; a new account gets repos in popular languages |
| `/me/contributions` | My Contributions: a connected user's public pull requests with Holt's verdict per repo, "found via Holt", refresh with a 15-minute cooldown |
| `/settings/alerts`, the bell | PR watch (API.md, "PR watch (alerts)"): the bell in the app's top bar, a mute toggle and a "new" tag on My Contributions rows, the "turn on alerts" card, and the alert settings. All hidden while the server has it switched off (`access.state` is `unavailable`). The browser goes through `/api/alerts/*`; the email address is the signed-in account's own, added there, never typed. `MOCK_PR_WATCH=0` hides it in the mock, `MOCK_PR_WATCH=ended` shows it after the 14 days |
| `/alerts/unsubscribe?t=…` | An alert email's "Stop these emails" link. The page sends the token from the browser once it is open, never while rendering on the server (mail scanners fetch links), and offers an undo. `POST /api/alerts/unsubscribe?t=…` is the mail client's one-click (RFC 8058); a GET there only goes to the page. In the mock the token is `mock-unsubscribe-token` |
| `/terms`, `/privacy`, `/refunds`, `/contact` | Policy pages the payment processors require. Static; contact details come from `NEXT_PUBLIC_CONTACT_EMAIL` / `NEXT_PUBLIC_CONTACT_CITY` (`src/lib/site.ts`), and `LEGAL_UPDATED` there is the "Last updated" date |
| `/badge/{owner}/{repo}.svg` | README badge (proxied from the API) |
| `/api/*` | BFF route handlers: start analysis, SSE proxy, starter issues, find events. Starting an analysis or a find needs a signed-in user (401 `unauthorized` otherwise); `/api/public/*` (the extension's) stays open |

## Production

Required env: `AUTH_URL` (public URL, for OAuth callbacks), `AUTH_SECRET`,
`DATABASE_URL`, `HOLT_API_URL`, `HOLT_INTERNAL_KEY`, OAuth app ids/secrets,
and, at build time, `NEXT_PUBLIC_SITE_HOST` plus `NEXT_PUBLIC_CONTACT_EMAIL`
and `NEXT_PUBLIC_CONTACT_CITY`. A production build (`next build`) refuses to
run when either is unset or still the placeholder `CONTACT_EMAIL` /
`CONTACT_CITY`, so the policy pages can never ship them; a local build without
the real values needs `HOLT_ALLOW_PLACEHOLDER_CONTACT=1`. Run `npm run db:migrate` on deploy.

- `TRUST_PROXY_HEADERS=1` only when the app is reachable solely through our
  proxy (Cloudflare tunnel). The standalone server should listen on
  `HOSTNAME=127.0.0.1` or only on the compose network, never on a public
  interface, or visitors could forge their rate-limit IP.
- The server refuses to start with `MOCK_API=1` in production unless
  `ALLOW_MOCK_IN_PROD=1` (demo deployments only).
- Signed-out views of the public pages (landing, Discover, Examples, pricing,
  How it works, the policy pages, and a report page whose report exists) are
  sent with `Cache-Control: public, max-age=0, must-revalidate, s-maxage=60`
  and `CDN-Cache-Control: public, s-maxage=60, stale-while-revalidate=300`,
  so a CDN in front may keep them for a minute. Any request with a cookie the
  app could read (a session, a half-done sign-in, a display setting) gets
  Next's own `private, no-store`, and so does every other page. The rules are
  in `src/lib/edge-cache.ts`; the proxy applies them. A CDN that caches these
  pages must skip its cache for requests whose cookies contain `authjs` or
  `holt`: a cached copy is served without asking the app.

## Checks

```sh
npm run lint
npm run typecheck # generates route types first; needs the same env as the build
npm test          # node --test, no network
HOLT_ALLOW_PLACEHOLDER_CONTACT=1 npm run build   # or set NEXT_PUBLIC_CONTACT_EMAIL / _CITY
E2E_BASE_URL=http://localhost:3000 npm run e2e   # smoke: policy pages exist and are in the footer (needs a running app)
```

## Design

Tokens live in `src/app/globals.css`: the dark palette is the original
`website/` brand and the light palette is warm paper with cool navy ink. Every
text colour passes WCAG AA in both themes. The theme follows the system until
the visitor picks one with the header toggle; a small inline script sets it
before first paint. Motion is CSS-first. GSAP, ScrollTrigger and Lenis load
only on desktop (mouse or trackpad) and never with `prefers-reduced-motion`:
Lenis smooths wheel scrolling site-wide from hydration, and the landing cat
starts once the page is idle. See the motion plan §5.

`screenshots/` holds PR screenshots (both themes, phone and desktop, mock mode).
