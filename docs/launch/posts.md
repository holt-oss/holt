# Launch posts (drafts)

Plain-language drafts for the Hacktoberfest launch. The site is
https://githolt.com. Lines in `[brackets]` are for you to fill in with your
own words. Please don't post a guessed version of them.

**Numbers used below** are from live Holt reports on 28 September 2026
(`holt analyze <repo> --live --no-model`, the same engine as githolt.com).
Re-check them on the day you post, because reports refresh:

| Repo | Verdict | Outside PRs merged | Closed or left with no reply | Typical first reply |
|---|---|---|---|---|
| home-assistant/core | Worth your time | 43 of 58 | 8 got no reply | ~15 hours |
| pallets/flask | Not worth your time | 5 of 171 | 99 closed without a word | ~40 minutes |
| psf/requests | Worth your time | 14 of 120 | 13 got no reply, 68 closed without a word | ~3 hours |

Holt's verdicts were identical across three runs on all 55 repositories tested
(see `docs/research/EVALUATION.md` and `docs/research/REPRODUCTION.md` — that
evaluation is historical competition research now, not a live product claim).
Holt won "Most useful real-world workflow" in micro1's Frontier Engineering
Challenge.

Things to keep true in every post:
- Holt is free for rules reports, and bringing your own AI key is free. Don't
  quote paid-plan prices until payments are live.
- The verdict comes from fixed rules; AI only explains it.
- Holt only reads public GitHub data. It never comments or opens PRs.

---

## LinkedIn (founder voice)

> I built a tool that tells you whether an open-source project will actually review your pull request. It's free, and it's live for Hacktoberfest.
>
> [One or two lines, in your own words, about why: e.g. a first PR of yours, or a friend's, that sat unanswered for weeks.]
>
> Holt reads a repository's recent pull requests from outside contributors and answers one question: is this worth a newcomer's time? It shows how many outside PRs got merged, how many never got a reply, how fast maintainers respond, and which folders newcomer work actually lands in. Every claim links to the GitHub conversation it came from.
>
> Some of what it finds is humbling. Flask is a well-run, much-loved project, and Holt says it's not worth a newcomer's time right now: only 5 of the last 171 outside pull requests were merged, and 99 were closed without a word. Home Assistant, a far bigger project, merged 43 of its last 58. That's the difference between "popular" and "a good place for your first PR".
>
> A few things I cared about:
> - The verdict comes from fixed, written rules. An AI can explain the evidence, but it can't change the answer.
> - It's read-only. It never comments or opens PRs for you.
> - Rules reports are free. Bringing your own AI key is free too.
>
> Holt started as my entry to micro1's Frontier Engineering Challenge, where it won "Most useful real-world workflow".
>
> Hacktoberfest starts on 1 October. If you're taking part, or you run a college coding club, there's a page of welcoming projects with starter issues by language: https://githolt.com/hacktoberfest
>
> It's open source (Apache-2.0 for the engine and CLI, AGPL-3.0 for the web app). Feedback and contributions are very welcome.

---

## X thread (6 posts)

1/
Before you spend a week on your first open-source PR, check whether the project merges outsiders' PRs at all.

I built Holt to answer that. Paste a GitHub repo, get a plain-English verdict with evidence. Free.

https://githolt.com

2/
It reads the repo's recent pull requests from outside contributors:
· how many got merged
· how many never got a reply
· how fast maintainers respond
· which folders newcomer work actually lands in

Every claim links to the GitHub thread it came from.

3/
Popular ≠ welcoming.

Flask, right now: 5 of the last 171 outside PRs merged, 99 closed without a word. Holt says not worth your time.

Home Assistant, a much bigger project: 43 of the last 58 merged. Worth your time.

4/
The verdict is decided by fixed, written rules, not by a model. AI can write an explanation on top, but it can't change the answer.

It's read-only: it never comments or opens PRs for you.

5/
The trick I use most: on any GitHub repo page, swap hub for holt in the address bar.

github.com/home-assistant/core → githolt.com/home-assistant/core

6/
Doing Hacktoberfest? Welcoming projects with starter issues, by language:
https://githolt.com/hacktoberfest

Open source (Apache-2.0 engine/CLI, AGPL-3.0 web app). It won "Most useful real-world workflow" in micro1's Frontier Engineering Challenge. Feedback welcome.

---

## Reddit (r/opensource, r/developersIndia)

**Title:** How do you tell if a repo will actually review a newcomer's PR? I built a free checker, with the numbers it found

> A lot of first-time contributors pick a project because it's popular, open a PR, and then hear nothing for weeks. Stars and issue counts tell you a project is healthy. They don't tell you what happens to someone from outside who sends a pull request.
>
> So I built a tool that looks at exactly that. It reads a repo's recent pull requests from outside contributors and reports:
>
> - how many were merged, and how many never got a reply
> - the typical time to a first response
> - which folders outside contributions actually get merged into (and which never do)
> - open, unclaimed issues that suit a newcomer
>
> Every number links back to the GitHub threads it came from, so you can check it yourself.
>
> An example that surprised me: Flask. Only 5 of the last 171 outside PRs were merged, and 99 were closed without a word. When someone does reply, it's fast (around 40 minutes), but most outside work is never merged, so the tool says it's not worth a newcomer's time right now. Home Assistant, which you might expect to be harder, merged 43 of its last 58 outside PRs, and the tool says it's worth your time.
>
> The verdict comes from fixed rules, not an LLM. There's an optional AI explanation, but it can't change the verdict. The tool only reads public data and never posts anything.
>
> It's free and open source (Apache-2.0 engine/CLI, AGPL-3.0 web app): https://githolt.com. There's also a Hacktoberfest page with welcoming repos by language: https://githolt.com/hacktoberfest.
>
> I'd really like feedback, especially cases where you think the verdict is wrong for a repo you know well.

*(For r/developersIndia, you can add one line on the college/student angle; keep the rest the same. Check each subreddit's self-promotion rules before posting.)*

---

## WhatsApp / college group (~60 words)

> Doing Hacktoberfest this year? Before you pick a repo, check it on Holt. It tells you if the project actually merges newcomers' PRs, how fast they reply, and gives you real starter issues to pick. Free, no sign-up for the basic report.
> Welcoming repos by language: https://githolt.com/hacktoberfest
> Tip: swap hub for holt in any repo link: github.com → githolt.com.

---

## Show HN

**Title:** Show HN: Holt – check whether an open-source repo merges newcomers' PRs

**First comment:**

> Hi HN. Holt answers one question for someone about to make their first contribution: will this project actually review and merge a pull request from an outsider?
>
> It reads the repo's recent PRs from people outside the project and reports the merge rate, how many got no reply, time to first response, and which parts of the codebase outside work actually lands in, with links to every thread it used. It also lists open issues that suit a newcomer.
>
> Design choices you may care about:
> - The verdict ("worth your time", "not worth your time", "not enough evidence") comes from a small written ruleset over verified findings. A model can write an explanation, but it cannot change the verdict, and a claim whose evidence doesn't resolve is dropped.
> - It is read-only toward GitHub.
> - Verdicts were stable across three runs, 55/55, in a benchmark run as part of the original competition entry (now historical research, not a live claim). Details and a reproduction guide are in the repo.
>
> It started as an entry to micro1's Frontier Engineering Challenge ("Most useful real-world workflow"). The engine and CLI are Apache-2.0; the web app is AGPL-3.0. There's a CLI (`uv tool install holt-cli`) and a web app: https://githolt.com. On any GitHub URL, swap hub for holt: github.com → githolt.com.
>
> I'd especially like to hear about repos where you think it gets the answer wrong.

---

## Email / DM to a college coding-club lead

**Subject:** A 30-minute "your first open-source PR" session for Hacktoberfest?

> Hi [name],
>
> I'm [your name], and I build Holt, a free, open-source tool that helps students pick open-source projects that actually review newcomers' pull requests. It won "Most useful real-world workflow" in micro1's Frontier Engineering Challenge.
>
> With Hacktoberfest starting on 1 October, would your club be up for a 30-minute session on making a first open-source PR? A rough plan:
>
> - 5 min: why first PRs get ignored, and how to spot a welcoming project
> - 15 min: everyone picks a repo in a language they know and a real starter issue (using https://githolt.com/hacktoberfest)
> - 10 min: how to write the comment, the PR description and the follow-up so a maintainer actually replies
>
> No sign-up or payment is needed for students; the basic reports are free. I can run it online or [in person], at a time that suits you.
>
> Would that be useful for your members?
>
> Thanks,
> [your name]
> https://githolt.com
