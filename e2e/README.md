# Holt e2e smoke tests

Playwright smoke tests against a deployed Holt, at phone (390×844) and
desktop (1440×900) sizes. The default target is staging,
https://holt-new.aahil-khan.xyz. They use **rules mode only** and never
start an AI report.

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

Staging runs this suite after every rebuild (`deploy/staging/preview.sh`)
and shows the result on `/__build` under `"smoke"`. A failure doesn't roll
the build back.
