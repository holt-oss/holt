# Holt documentation

Start with the [README](../README.md). Everything else is here.

## Using Holt

| Page | What it is for |
|---|---|
| [USAGE.md](USAGE.md) | The command line, from install to reading an answer |
| [COMMANDS.md](COMMANDS.md) | Every command and flag, with real output |
| [../extension/README.md](../extension/README.md) | The browser extension: build it, load it, what it sends |
| [../SUPPORT.md](../SUPPORT.md) | Where to ask for help |

## Contributing and running the code

| Page | What it is for |
|---|---|
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Your first pull request in 15 minutes, then the full setup |
| [DEV-WORKFLOW.md](DEV-WORKFLOW.md) | Working on Holt every day: local web with mock or real data, engine changes, branch to staging to production, the rules that bite |
| [../web/README.md](../web/README.md) | The web app (Next.js): run it locally, routes, mock API |
| [../server/README.md](../server/README.md) | The HTTP API server (FastAPI): run it, environment |
| [../API.md](../API.md) | The contract between the server and the web app |
| [../e2e/README.md](../e2e/README.md) | Playwright smoke tests against a deployed Holt |
| [../deploy/README.md](../deploy/README.md) | Container images and the staging preview |
| [RELEASING.md](RELEASING.md) | How a PyPI release is cut (maintainers) |
| [../GOVERNANCE.md](../GOVERNANCE.md), [../SECURITY.md](../SECURITY.md), [../CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) | How the project is run |

## How Holt decides, and how well

| Page | What it is for |
|---|---|
| [DESIGN.md](DESIGN.md) | Why the verdict is a pipeline of rules and not a prompt |
| [research/REVIEW-2026-09-30.md](research/REVIEW-2026-09-30.md) | The verdict rules in plain English, the evidence for each threshold, and the 30 Sep go/no-go review |
| [research/EVALUATION.md](research/EVALUATION.md) | How the competition benchmark was built (retired as a gate), the numbers, and what they depend on |
| [research/REPRODUCTION.md](research/REPRODUCTION.md) | Reproduce every published number from a clone, with no key and no spend |
| [research/LIVE-AI-TEST-2026-09-28.md](research/LIVE-AI-TEST-2026-09-28.md) | First run of every AI feature on a real model: honesty checks, cost and latency, fixes |
| [../golden/README.md](../golden/README.md) | The golden set: 62 recorded repositories, the engine's approved answer on each, and the before/after table every engine change is checked with |
| [../eval/](../eval/) | The benchmark itself: pools, labels, recorded runs and their pre-registration notes |

## Plans and drafts

| Page | What it is for |
|---|---|
| [launch/posts.md](launch/posts.md) | Launch post drafts |
| [launch/good-first-issues.md](launch/good-first-issues.md) | Issues to open for Hacktoberfest |
| [design/MOTION.md](design/MOTION.md) | The web app's motion and loading plan |
| [strategy/BUSINESS.md](strategy/BUSINESS.md) | Costs, pricing and the break-even plan |
