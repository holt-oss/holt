# Working on Holt every day

For the two owners of `holt-oss/holt`, on their own laptops (Linux, macOS or
Windows). It is the short path: what to run, and what bites. Each command below
was run before it was written down; the details live in the READMEs it links.

You need Node 22+, [`uv`](https://docs.astral.sh/uv/) (installs the right
Python for you), `git`, the [GitHub CLI](https://cli.github.com/) (`gh auth
login` once) and, for anything with a database, Docker. On Windows, run the
commands in WSL, or use the PowerShell notes marked **Windows**; Docker
Desktop is enough for the database.

## 1. Changing the layout (fastest path)

```sh
git clone https://github.com/holt-oss/holt.git && cd holt/web
npm ci
MOCK_API=1 npm run dev          # http://localhost:3000
```

**Windows (PowerShell):** `$env:MOCK_API=1; npm run dev`. Or, anywhere, copy
`web/.env.example` to `web/.env.local`: it already says `MOCK_API=1`, so plain
`npm run dev` works from then on.

No key, no database, no API server. Saving a file reloads the page in about a
second (checked). If it shows a stale page anyway, stop it and delete
`web/.next`.

`MOCK_API=1` swaps the API for made-up but realistic reports (`web/src/lib/mock/`,
following [`API.md`](../API.md)). The named repos below carry the verdict and
counts the real engine gave them on 28 Sep 2026, so the mock never contradicts
the live site; the rest of each page is illustrative. Which URL shows which state:

| Open | You see |
|---|---|
| `/home-assistant/core`, `/NixOS/nixpkgs`, `/psf/requests`, `/pytorch/pytorch` | A finished report, **Worth your time**. Instant. |
| `/pallets/flask`, `/aden-hive/hive` | A finished report, **Not worth your time**. Instant. |
| `/anything/else` | The loading screen with live stages for about 6 seconds, then a report. The verdict is picked from the repo name, so it is stable. `MOCK_JOB_MS=20000` makes the wait longer. |
| `/example/new-thing`, `/tiny/thing` | The same, ending in **Not enough evidence** (any name containing `tiny`, `empty` or `new-` does). |
| `/mock/outdated` | The "we couldn't refresh this" fallback (an old report whose fresh check fails). |
| `/doesnotexist/x`, `/private/x` | The repository-not-found page. |
| `/discover`, `/find`, `/hacktoberfest`, `/compare?repos=home-assistant/core,pallets/flask` | The list pages, filled from the mock repos. |
| `/signin`, `/settings`, `/me/history`, `/for-you` | Signed-out versions until you sign in (below). |

Other switches: `MOCK_PLAN=pro` (every pick on `/for-you`), `MOCK_PRO=0` (hide
the playbook), `MOCK_PRO_OFF=1` (pre-flight "coming soon"). The full list is
in [`web/README.md`](../web/README.md).

Check the phone size in the browser's responsive mode. Both themes: the header
toggle.

### Signed-in screens

Pages that need an account (`/settings`, `/me/history`, AI reports) need the
dev sign-in, which needs Postgres for the session. From `web/`:

```sh
cp .env.example .env.local
docker compose up -d db
npm run db:migrate
npm run dev
```

Then open `/signin`, type a name under "development only" and press dev
sign-in. Each name is a separate test user with 3 free AI credits and a small
history. Stop the database with `docker compose down` (add `-v` to erase it).

`AUTH_SECRET=` can stay empty: in development an empty or missing value falls
back to a fixed dev-only secret (`web/src/lib/auth-secret.ts`). Anywhere else
the app refuses to sign anyone in without a real one.

Things that did not work as written:

- **Port 5432 already taken** (a Postgres you already run)? Set
  `HOLT_DB_PORT=5433` in `.env.local` and in `.env` (`cp .env.local .env`; the
  compose file reads `.env`), and change the port in `DATABASE_URL` to match.
- Without a database, `/api/dev-signin` answers 500 (and the web log says
  "password authentication failed"). Every other page still works.

## 2. Real data on your machine

Same web app, but talking to the real API server and the real engine, with your
own GitHub token (read-only; no permissions needed). One Postgres serves both:
the web app uses database `holt`, the API uses a second one. From the repo
root, with the database from section 1 running:

```sh
uv sync
docker compose -f web/compose.yml exec db createdb -U holt holt_api
cp server/.env.example server/.env
```

Edit `server/.env` (it is gitignored) so these four lines read:

```sh
DATABASE_URL=postgresql+asyncpg://holt:holt@127.0.0.1:5432/holt_api
HOLT_INTERNAL_KEY=change-me                 # must equal HOLT_INTERNAL_KEY in web/.env.local
HOLT_SECRET_KEY=<python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())">
GITHUB_TOKENS=<your token: gh auth token, or a fine-grained one with no extra access>
```

Then two terminals:

```sh
# 1. the API   (http://127.0.0.1:8000, /health; add HOLT_ENV=dev for the /docs page)
cd server && uv run holt-server

# 2. the web app, with the mock switched off (edit .env.local: MOCK_API=0)
cd web && npm run dev
```

(Prefer a separate Postgres for the API? `docker compose -f server/compose.yml
up -d` starts one on port 20131, and `server/.env.example` already points
there. Its service, volume and port variable (`api-db`, `HOLT_API_DB_PORT`) are
named apart from the web app's, so the two never share a data directory, even
under one `COMPOSE_PROJECT_NAME`.)

The server creates its tables on first start (it prints `migrating the schema
from empty`). Open `/home-assistant/core`: the loading screen now shows real stages,
and a report takes about 10 to 30 seconds. One report costs about 10 GitHub
points of the 5,000 an hour a token has. Sign-in works as in section 1.

- Web files hot-reload. The server does not: stop it and start it again after
  a change under `server/` or `src/holt/`. It runs the engine from your
  checkout, so engine edits show up on the next start.
- AI reports need `OPENROUTER_API_KEY` in `server/.env`; without it they say
  "not available" and cost nothing.
- Reports are cached for 24 hours (`HOLT_CACHE_HOURS`), so a repo you already
  opened comes back instantly with the old numbers. To see an engine change on
  it, ask for a fresh run (`POST /api/analyses` with `"refresh": true` queues one):
  ```sh
  curl -X POST localhost:3000/api/analyses -H 'content-type: application/json' \
    -d '{"repo":"home-assistant/core","refresh":true}'
  ```
  A new `ENGINE_VERSION` also makes every old report count as out of date.
- Never point your local server at the production or staging database.

## 3. Changing the engine or the CLI

```sh
uv sync
uv run pytest tests/test_<area>.py -q        # only what you touched; the full suite is ~3 minutes
uv run holt analyze NixOS/nixpkgs --replay               # offline, from a clone, no key
export GITHUB_TOKEN=$(gh auth token)                     # Windows: $env:GITHUB_TOKEN = (gh auth token)
uv run holt analyze pallets/flask --live --no-model      # real data, about 25 seconds
```

**The golden set** is 62 recorded repositories and the verdict the engine
approved for each. It is how an engine change shows what it did
([`golden/README.md`](../golden/README.md)):

```sh
uv run python -m golden diff                  # the before/after table for your change; paste it in the PR
uv run python -m golden approve --reason "why this is right"    # accept it (commit golden/expected.json)
uv run python -m golden check                 # exit 1 on any unapproved change; CI runs it
```

On a clean checkout `diff` says "No differences" (about 10 seconds).

**When to bump `ENGINE_VERSION`** (`src/holt/engine_version.py`, add one): when
the same evidence would now produce a different report, meaning the verdict
rules, the signals and thresholds they read, or the report's fields and
wording. Not for refactors, tests or docs. Bumping makes the server stop
serving reports made by the old engine. After it is on production, whoever
deploys runs `deploy/prod/warm.sh --stale-only` (section 4). If the golden diff
shows a changed verdict or count, you almost certainly need the bump.

Adding a repo to the golden set, or changing verdict rules, has more steps:
[`CONTRIBUTING.md`](../CONTRIBUTING.md#changing-the-verdict-rules).

## 4. From branch to production

1. **Branch, never `main`.** Both of you can push branches straight to
   `holt-oss/holt`; no fork is needed.
   ```sh
   git switch main && git pull && git switch -c short-name-of-change
   ```
2. **Commit, push, open a draft PR.**
   ```sh
   git push -u origin HEAD
   gh pr create --draft --base main
   ```
   Fill in the template: what changed for a user, how you checked it (paste
   the commands and their output), and, if `API.md` or the engine moved, say so.
   Nothing should say Claude or any AI tool wrote it: no `Co-Authored-By`
   trailer, no "Generated with" line.
3. **CI** starts by itself and takes 1 to 3 minutes (about 3 for Python). What
   runs depends on the files you changed:
   - `tests`: Python tests on all cores, the no-key smoke commands, the golden
     check, the wheel build, and the server tests on real Postgres (this also
     runs every migration from empty). Skipped when you only touched `web/`,
     `extension/`, `e2e/`, `website/` or `docs/`.
   - `web`: lint, typecheck, unit tests and a production build of the web app;
     the extension's typecheck, tests and build; the generated
     `web/src/lib/api-schema.ts` is up to date (fix with
     `server/scripts/api_types.sh`); and ruff on Python (`uvx ruff@0.16.9
     check .`).

   `main` is not protected, so GitHub lets you merge a red PR. Don't.
4. **Preview it on staging** (optional, for anything you want to see or show
   on a real URL): add the `staging` label.
   ```sh
   gh pr edit <number> --add-label staging
   ```
   Staging is https://staging.githolt.com: the real server and engine, real
   data, a separate database, never indexed. It is `main` plus every open PR
   with the label, rebuilt by a timer that looks every 3 minutes, so your
   change is live about 3 to 6 minutes after you label or push. Open it in a
   browser: Cloudflare Access asks for your email and mails you a one-time
   code, and only the emails on the allow-list get in. `curl` gets the login
   page instead, unless you use a service token
   ([`deploy/README.md`](../deploy/README.md#behind-cloudflare-access)).
   Sign-in is off on staging ("isn't set up here") and AI reports say "needs a
   key" unless someone has given it its own OAuth apps and model key
   ([`deploy/README.md`](../deploy/README.md#sign-in-on-staging)); check the
   page rather than assume.

   Check that your commit is the one running:
   https://staging.githolt.com/__build. It lists the `main` commit, each PR
   included with its commit, any PR left out with the reason (a conflict with
   another labelled PR, for example), when it was built, the smoke-test result
   for that build (`smoke`, which finishes about 4 minutes after the site is
   live), and `last_attempt` (`building`, `waiting`, or `failed` with why).
   Take the label off when you are done so it stops joining other people's
   previews.
5. **Merge to `main`.** Mark the PR ready, wait for green, squash-merge (that is
   what the history shows): `gh pr merge <number> --squash`. Staging follows
   `main` on its own.
6. **Production** (https://githolt.com) never updates by itself. Only the
   repo owner runs `deploy/prod/deploy.sh`, from `main`, when they decide to
   ([`deploy/prod/README.md`](../deploy/prod/README.md)): it builds, migrates
   the database first, swaps the containers, checks the site, and rolls back
   if that fails. Nobody else deploys, and nothing that isn't on `main` does.
   Ask. After a deploy that bumped `ENGINE_VERSION`, run
   `deploy/prod/warm.sh --stale-only`. `https://githolt.com/__build` shows the
   commit that is live.

## 5. Rules that bite

- **`API.md` moves with the code.** Change what the server returns or what the
  web app sends only in the same PR as the code, and say so in the PR. After a
  change to the server's response models, run `server/scripts/api_types.sh`
  and commit `web/src/lib/api-schema.ts`; CI fails when it is stale.
- **One migration head.** Schema changes are Alembic migrations in
  `server/holt_server/migrations/versions/` ([how](../server/README.md#changing-the-schema)).
  Before you push, `git fetch && git merge origin/main` (merge, don't rebase),
  and make sure this prints exactly one line, with your migration as the head:
  ```sh
  uv run alembic -c server/alembic.ini heads
  ```
  Two people adding `0016` at once is the usual way to get two heads. A
  migration must also work with the previous release, because deploys migrate
  before they swap containers and a rollback doesn't undo it: add columns as
  nullable or with a default, and drop or rename only in a later release.
- **No AI attribution** in commits, PR descriptions or comments. Check
  `git log -3` before you push if an assistant helped.
- **Never commit to `main`.** Branch, PR, merge.
- **Secrets stay out of the repo.** `.env`, `.env.local` and `server/.env` are
  gitignored; keep tokens there and nowhere else, and never paste one into a
  PR, an issue or a log.
- **Holt only reads from GitHub.** It never posts, opens PRs or contacts anyone.
- **User-facing words are plain English.** No `not_viable`, no "MCC".
- **The verdict comes from rules, never from a model.** The model explains it.
- **Tests never use the network.** `web/` also runs `npm test`; `extension/` has
  its own `npm test`.
