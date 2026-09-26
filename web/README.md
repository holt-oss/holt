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
  queued jobs that stream stages over SSE. `pallets/flask`, `NixOS/nixpkgs`,
  `psf/requests` and `pytorch/pytorch` are "cached" and load instantly; any
  other repo runs a fake analysis (about 6 s, `MOCK_JOB_MS`). Repos named
  `*/private*` or `doesnotexist/*` return `not_found`. Keep it for demos.
- **Sign-in**: set `AUTH_GITHUB_*` / `AUTH_GOOGLE_*` for OAuth. In development
  with neither set, `/signin` offers a dev-only sign-in that creates a real
  database session.
- **Site host**: `NEXT_PUBLIC_SITE_HOST` is the domain used in the
  "swap hub for holt" URL trick (github.com → githolt.com), badges, share links and OG images.

## Routes

| Path | What |
|---|---|
| `/` | Landing: paste box, find CTA, Hacktoberfest banner, URL trick |
| `/{owner}/{repo}` | Report. Starts a rules analysis if nothing is cached and streams progress. `?mode=ai` for the AI report, `?days=` for the time budget |
| `/github.com/o/r`, `/https://github.com/o/r`, `/o/r/pulls`… | Redirect to `/o/r` (`src/proxy.ts`) |
| `/{owner}/{repo}/opengraph-image` | Per-repo share image |
| `/find` | Beginner flow: languages, time, Hacktoberfest → welcoming repos + starter issues |
| `/compare?repos=a/b,c/d` | Up to 4 repos side by side |
| `/signin`, `/settings`, `/pricing`, `/me/history`, `/how-it-works` | Account, BYOK, plans, history, methodology |
| `/badge/{owner}/{repo}.svg` | README badge (proxied from the API) |
| `/api/*` | BFF route handlers: start analysis, SSE proxy, starter issues, find events |

## Production

Required env: `AUTH_URL` (public URL, for OAuth callbacks), `AUTH_SECRET`,
`DATABASE_URL`, `HOLT_API_URL`, `HOLT_INTERNAL_KEY`, OAuth app ids/secrets,
and `NEXT_PUBLIC_SITE_HOST` at build time. Run `npm run db:migrate` on deploy.

- `TRUST_PROXY_HEADERS=1` only when the app is reachable solely through our
  proxy (Cloudflare tunnel). The standalone server should listen on
  `HOSTNAME=127.0.0.1` or only on the compose network, never on a public
  interface, or visitors could forge their rate-limit IP.
- The server refuses to start with `MOCK_API=1` in production unless
  `ALLOW_MOCK_IN_PROD=1` (demo deployments only).

## Checks

```sh
npm run lint
npm run typecheck
npm test          # node --test, no network
npm run build
```

## Design

Tokens live in `src/app/globals.css`: the dark palette is the original
`website/` brand and the light palette is a warm "paper" adaptation. Every
text colour passes WCAG AA in both themes. The theme follows the system until
the visitor picks one with the header toggle; a small inline script sets it
before first paint. Motion is CSS-first. GSAP, ScrollTrigger and Lenis load
only on desktop, only after the page is idle, and never with
`prefers-reduced-motion`.

`screenshots/` holds PR screenshots (both themes, phone and desktop, mock mode).
