# Holt e2e smoke tests

Playwright smoke tests against a deployed Holt, at phone (390×844) and
desktop (1440×900) sizes. The default target is staging,
https://staging.githolt.com (`STAGING_HOST` names another staging host,
`BASE_URL` any other site). They use **rules mode only** and never start an
AI report.

They use the server's cached Chromium (`~/.cache/ms-playwright`, the one
`shot` uses) and never download a browser. Set `CHROMIUM_PATH` to use
another one.

```sh
cd e2e
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci
npx playwright test --workers=1                 # both sizes, one browser at a time
npx playwright test --project=phone -g pricing  # one test, one size
BASE_URL=http://127.0.0.1:3000 npx playwright test   # a local web app (needs the API behind it)
node lighthouse.mjs                              # mobile Lighthouse for /, /pallets/flask, /find
```

## Behind Cloudflare Access

If the site is behind Cloudflare Access, set a service token and everything
here gets through:

```sh
export STAGING_CF_ACCESS_CLIENT_ID=<client id>.access
export STAGING_CF_ACCESS_CLIENT_SECRET=<client secret>
npx playwright test --workers=1
node lighthouse.mjs
```

How it works (`access.mjs`): before the first test, one request to the
site's `/` sends the `CF-Access-Client-Id` / `CF-Access-Client-Secret`
headers, without following redirects, and keeps the `CF_Authorization`
cookie Access answers with. `global-setup.ts` saves that cookie in
`.access/state.json` (gitignored, deleted when the run ends), and the
config's `storageState` starts every browser context and API request
context with it, set for the site's host only. The browser never sends the
token itself. Headers added per request would go further than that: a
route's headers follow redirects to other sites, and so do an API request
context's `extraHTTPHeaders`. A cookie stays with its host, so github.com,
redirects and third-party images never see it.

`lighthouse.mjs` does the same with a Chrome of its own per run (the cookie
set over the DevTools protocol, then `lighthouse --port`). Lighthouse's
`--extra-headers` would send the token to every origin a page loads from.
`scripts/record-demo/record.mjs` reads the same variables.

Both are needed together; one alone stops the run with a message. A token
Access doesn't accept stops the run before any test, saying so. Without
either variable nothing changes. Staging's own run gets them from
`~/.config/holt/secrets.env` (see `deploy/README.md`, "Behind Cloudflare
Access").

What they check:

- The landing paste box takes `https://github.com/pallets/flask` and ends on
  `/pallets/flask` with a verdict.
- The URL trick: `/github.com/pallets/flask` (and a deep `https://github.com/…/pulls`)
  redirects to the report.
- `/find` with Python + Hacktoberfest lists at least one repo with a GitHub
  issue link. If the site is rate limiting us, the test is skipped, not failed.
- The Hacktoberfest pill's × hides it, and it stays hidden after a reload (skipped outside the season).
- The theme toggle survives a reload.
- `/pricing` shows the plans.
- The extension's `/api/public/*` endpoints answer JSON with CORS headers.
- `/__build` is valid JSON.
- Phones (`tests/mobile.spec.ts`): no page scrolls sideways at 360px (the
  failure names the elements that stick out), the viewport meta is
  device-width, and on desktop the OPEN / SOURCE band moves as you scroll.
- `/`, `/pallets/flask`, `/find`, `/pricing` and `/how-it-works` log no console errors.
- Motion (`tests/motion.spec.ts`, see `docs/design/MOTION.md`): no layout
  shift on `/`, `/pallets/flask`, `/find?go=1…` and `/pricing`, cold and
  after a client navigation; a slow page (its response held 600ms) shows the
  loading skeleton and keeps it at least 300ms; a fast one (server under
  100ms, else skipped) never shows it; a click while the prefetch is still
  being applied (the router commits the route as nothing, the bug behind
  #57) still shows the skeleton, through the layout's fallback, and shifts
  nothing; the phone menu opens and closes on
  Escape, a click outside and a link; with reduced motion, nothing moves.

Staging runs this suite after every rebuild goes live
(`deploy/staging/preview.sh`, three browsers at once) and shows the result
on `/__build` under `"smoke"`. A failure doesn't roll the build back. The
tests don't sign in or change anything another test reads, so they can run
in parallel; keep it that way. `[skip smoke]` in a commit message skips the
run for the build that commit is new in.
