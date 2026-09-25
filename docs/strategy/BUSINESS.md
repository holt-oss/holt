# Holt business strategy: the break-even plan

*Written 25 Sep 2026 for the Hacktoberfest launch (1 Oct 2026). Prices were checked that day; sources are at the end. **A** marks an assumption, not a measurement.*

## The short version

- **Breaking even is easy if the free AI reports have a hard monthly budget.** Hosting, domain and email cost about **₹100 a month** while Holt runs on the home server. Nearly all the money goes on free AI reports. Everything else is small.
- **One AI report costs ₹1.45** (₹1.86 for a long one) on today's model, `openai/gpt-5-mini`, including OpenRouter's 5.5% top-up fee. Rules reports cost nothing except GitHub API points.
- **Fix one plan before launch:** Pro at ₹299 for 250 AI reports **loses money** for a heavy user (−₹71 a month, down to −₹173 for long reports). Cut it to **100 reports**, or keep 250 only once a cheaper model passes the evaluation.
- **Free AI quota:** make it **1 a month** at launch, not 3, and put a **₹1,000 monthly cap** on server-paid free AI. Rules reports stay free and unlimited, and BYOK (bring your own key) stays free. That caps the worst possible month at about **₹1,100**, while keeping the "wow" moment for every new user.
- **To break even**, about **1 in 140 signed-in users** has to pay (0.7%) with a free quota of 1, or 1 in 70 (1.4%) with a quota of 3. A student product might see 0.5–3% of users pay (**A**).
- **Adoption is the goal.** In the first 90 days, campus workshops and GitHub Sponsors are the realistic money outside the plans. Sell the maintainer and API products later.

---

## 1. What things cost

### 1.1 One AI report
I measured token use in the 71 committed trajectories in `fixtures/trajectories/`, all on gpt-5-mini. I counted only the four calls a real report makes (`classify`, `outcomes`, `opportunity`, `narrate`), and left out the evaluation-only `baseline` calls.

| per report | input tokens | output tokens (includes reasoning) |
|---|---|---|
| median | 9,033 | 6,039 |
| p90 (a long report) | 13,406 | 7,513 |
| max | 18,516 | 8,890 |

Cost per report on OpenRouter. Prices come from the OpenRouter models API. The cost includes the 5.5% fee on credit top-ups, and uses $1 = ₹96.02.

| model | $ per 1M in / out | median report | long report (p90) | per 1,000 reports |
|---|---|---|---|---|
| **openai/gpt-5-mini** (today) | 0.25 / 2.00 | **₹1.45** | ₹1.86 | ₹1,452 |
| openai/gpt-5-nano | 0.05 / 0.40 | ₹0.29 | ₹0.37 | ₹290 |
| google/gemini-2.5-flash | 0.30 / 2.50 | ₹1.80 | ₹2.31 | ₹1,804 |
| google/gemini-3.1-flash-lite | 0.25 / 1.50 | ₹1.15 | ₹1.48 | ₹1,146 |
| deepseek/deepseek-v4.1-flash | 0.099 / 0.60 | ₹0.46 | ₹0.59 | ₹458 |
| qwen/qwen3.8-flash | 0.15 / 0.47 | ₹0.42 | ₹0.56 | ₹425 |

**A:** The token counts are from gpt-5-mini. Other models write more or less (especially reasoning tokens), so these costs are estimates. **Don't switch models on price alone.** Run the evaluation in `docs/EVALUATION.md` first. A cheaper model that explains verdicts badly would hurt the brand more than it saves.

**The cache matters.** A finished AI report for the same repo, mode and days is served to *anyone* for 24 hours, and it costs nothing and uses no quota (`server/holt_server/api.py`). During Hacktoberfest many students will open the same popular repos.

| share of AI report views served from cache | cost per AI report *viewed* (gpt-5-mini) |
|---|---|
| 0% | ₹1.45 |
| 30% | ₹1.02 |
| 60% | ₹0.58 |

Quota is only charged on uncached reports. So caching lowers the *average* cost, but not the worst case: someone who uses their whole quota on uncached repos.

### 1.2 Rules reports and GitHub
- **Cost:** a rules report is free apart from GitHub API points. I measured **about 11 GraphQL points** per fresh rules report (two runs on staging, 25 Sep).
- **Limit per token:** a personal token gets **5,000 points an hour**, so about **450 uncached rules reports an hour**, less when starter issues and find are also running.
- **A GitHub App** gets up to **12,500 an hour** per installation.
- **Cache hits cost 0 points.**

### 1.3 Payment fees

| route | fee | on ₹99 | on ₹299 | notes |
|---|---|---|---|---|
| Razorpay, domestic cards / UPI (standard) | 2% + 18% GST on the fee = **2.36%** | ₹2.34 | ₹7.06 | No setup or yearly fee. Razorpay's pricing data lists UPI as "0% MDR for most transactions", so UPI may cost less. I use 2.36% for everything to be safe. |
| Razorpay, new-merchant offer | **0%** platform fee for 90 days or until ₹5 lakh | ₹0 | ₹0 | For accounts activated from 1 Jul 2026, so it covers the launch quarter. Amex, Diners and corporate cards are excluded. GST still applies. A one-time ₹199 KYC fee may apply. |
| Razorpay card subscriptions | +0.9% on top | ₹3.2 | ₹9.8 | UPI Autopay pricing is "on request". |
| Razorpay international cards | up to 3% + GST | — | — | Holt would need to handle tax and compliance itself. Use a merchant of record (MoR) instead. |
| Dodo Payments (MoR), international | 4% + 40¢, +1.5% outside the US, +0.5% for subscriptions → **about 6% + 40¢** | — | $5 → **$0.70 (14%)** | Dodo handles VAT and sales tax. Payouts are in USD, EUR or GBP only (INR payouts were discontinued); $5 per payout under $1,000, and $25 per USD SWIFT payout to non-US businesses. |

**Payout fees dominate at small volumes.** A $25 SWIFT fee on a $100 monthly payout is 25%. Hold international payouts until each one is a few hundred dollars.

### 1.4 GST (an individual seller in Punjab, domestic sales)
- **Registration threshold:** GST registration for services is required above **₹20 lakh a year** of turnover. Punjab is a normal-category state, not a ₹10-lakh one. ₹20 lakh a year is about 1,680 Student subscriptions every month, far beyond anything in this plan.
- **Selling on your own site with Razorpay:** as far as I can tell, this is **not** selling "through an e-commerce operator", which is the rule that forces registration at any turnover. Razorpay is a payment processor.
- **Inter-state sales:** service suppliers under ₹20 lakh are exempt from compulsory registration (Notification 10/2017-IT).
- **The OIDAR rule** (online services, register regardless of turnover) targets suppliers *outside* India.
- **If registered,** SaaS is taxed at 18%. Decide now whether displayed prices include GST: `tax_note` in `plans.toml` is empty.
- **International sales via Dodo:** Dodo is the seller to the customer; Holt supplies Dodo. Treating that as a zero-rated export needs GST registration plus a Letter of Undertaking (LUT), and proof of foreign remittance. Below ₹20 lakh you don't need to register just for this.
- **Get a CA to confirm all of the above in writing before the first paid sale** (about ₹1–3k for a consultation, **A**). Income tax on profits is separate, and a CA can advise on that too.

### 1.5 Hosting, domain, email

| item | option | per month |
|---|---|---|
| hosting | **today:** home server + Cloudflare Tunnel (the tunnel is free) | ~₹0 extra (**A**: electricity not measured; the box is already on) |
| | Hetzner CX23 (2 vCPU, 4 GB), Germany/Finland, €5.49 + VAT | ≈ ₹600 (+ IPv4, price unconfirmed). No India region; CX23 is sometimes sold out. |
| | Hostinger KVM 2 (2 vCPU, 8 GB), ₹799 on a 2-year term, renews at ₹1,199 | ₹799–1,199 |
| | DigitalOcean Bangalore, 2 vCPU / 4 GB, $24 | ≈ ₹2,300 |
| domain | .dev at Cloudflare Registrar, about $12.20 a year (Porkbun: $8.75 first year, then $12.87) | ≈ ₹100 |
| | .in at Porkbun, $7.83 a year | ≈ ₹63 |
| email | Resend free (3,000 a month, 100 a day) or Brevo free (300 a day) | ₹0. Sign-in is OAuth and Razorpay sends receipts, so Holt barely needs email yet. |
| GitHub API | free (personal token or GitHub App) | ₹0 |

**Fixed costs: about ₹100 a month on the home server, or about ₹700 on Hetzner.**

**Variable costs:** free AI reports (§4), and AI plus payment fees for paying users (§2).

---

## 2. Margin per plan
Plans come from `server/holt_server/plans.toml` on `billing-server`. **Note:** that file has Pro at **$5**, not $6, and has **no USD pack**. The task brief said Pro was ₹299 or $6 and packs were ₹49 or $2. I show both.

Contribution is what's left per month after payment fees and AI cost (gpt-5-mini, median report; the p90 figure is in brackets), with no cache help. Each column is the share of the quota actually used.

| plan | price | quota | 100% used | 50% | 25% |
|---|---|---|---|---|---|
| Student | ₹99 | 40 | ₹39 (₹22) | ₹68 (₹59) | ₹82 (₹78) |
| **Pro** | ₹299 | 250 | **−₹71 (−₹173)** | ₹110 (₹59) | ₹201 (₹176) |
| Pro, capped at **100** | ₹299 | 100 | ₹147 (₹106) | — | — |
| Pack | ₹49 | 10 | ₹33 (₹29) | ₹41 | ₹44 |
| Pro (Dodo) | $5 | 250 | ₹50 (−₹53) | — | — |
| Pro (Dodo) | $6 | 250 | ₹140 (₹38) | — | — |
| Pack (Dodo), not in the file | $2 | 10 | ₹129 | — | — |

- **Student and packs are healthy** even at full use. Most students won't use all 40.
- **Pro at 250 is the one leak.** At full use with a cheaper model it would be fine:

  | model (Pro, 250 reports) | AI cost | contribution |
  |---|---|---|
  | gpt-5-nano | ₹73 | ₹219 |
  | deepseek-v4.1-flash | ₹114 | ₹178 |
  | qwen3.8-flash | ₹106 | ₹186 |

  All of these need to pass the evaluation first.
- **Priority queue** costs nothing to provide.
- **BYOK is free for Holt.** The user pays their provider, and OpenRouter charges Holt nothing for it.

---

## 3. Break-even
**Contribution per average paying user: ₹80 a month (A).**
- Plan mix: 80% Student, 5% Pro, 15% packs.
- Students use 30% of their quota, Pro users 15%, and packs are fully used.

**Cost per free signed-in user:**

| free AI quota | who uses it (A) | cost per free user a month |
|---|---|---|
| 3 | 40% use AI, 2 reports on average | ₹1.16 |
| 1 | 40% use AI, 1 report | ₹0.58 |

**Break-even conversion:** the share of signed-in users who must pay just to cover free AI.

| free AI quota | break-even conversion |
|---|---|
| 3 | **1.4%** |
| 1 | **0.7%** |

**Fixed costs** take a few more paying users on top: **1–2** on the home server, **9** on Hetzner, **30** on DigitalOcean Bangalore.

### Scenarios
One month at steady state, free AI quota 3, home server.

| | pessimistic | realistic | optimistic |
|---|---|---|---|
| signed-in users a month (**A**) | 300 | 1,500 | 5,000 |
| paid conversion (**A**) | 0.5% | 1.5% | 3% |
| paying users | 1–2 | ~22 | 150 |
| revenue | ₹152 | ₹2,284 | ₹15,225 |
| contribution from payers | ₹120 | ₹1,806 | ₹12,039 |
| free AI cost | ₹347 | ₹1,717 | ₹5,635 |
| fixed | ₹98 | ₹98 | ₹98 |
| **net** | **−₹324** | **−₹8** | **+₹6,307** |
| net with free quota **1** | −₹150 | **+₹850** | **+₹9,100** |
| net on Hetzner instead | −₹924 | −₹608 | +₹5,707 |

About these assumptions:
- **Paid conversion.** Published freemium conversion for B2B software is 3–5% ("good") and 8–12% ("great"). That's the ChartMogul 2026 report, which surveyed B2B products. Students have less money and a free BYOK route, so I assume lower: 0.5–3%.
- **Pessimistic loses about ₹300 a month.** Paid for out of pocket, that's the cost of a Hacktoberfest-sized marketing experiment.
- **Realistic breaks even. With a free quota of 1, it earns a little.**
- **"Break even for sure"** comes from the budget cap in §4, not from the forecast.

---

## 4. Is the free tier sustainable?
Monthly cost of free AI reports on gpt-5-mini:

| signed-in users | quota 3, typical | quota 3, worst case (everyone uses all 3, long reports) | quota 1, typical | quota 1, worst |
|---|---|---|---|---|
| 500 | ₹581 | ₹2,792 | ₹290 | ₹931 |
| 2,000 | ₹2,324 | ₹11,170 | ₹1,162 | ₹3,723 |
| 10,000 | ₹11,618 | ₹55,850 | ₹5,809 | ₹18,617 |

**Recommendation: a free AI quota of 1 a month at launch**, plus two safeguards:
1. **A hard monthly budget for free AI (e.g. ₹1,000).** When it's spent, free AI shows "this month's free AI reports are used up". The rules report is still free, and so are BYOK and paid plans. OpenRouter is prepaid, so topping up only a fixed amount is already a hard stop. But paying users share the same key, so Holt needs its own counter (**to build**: a global monthly free-AI budget in the server).
2. **Popular repos get cached.** AI reports on the Hacktoberfest favourites will mostly come from the cache.

Why 1 rather than 0: the AI report is the thing people screenshot and share. One free report per person is ₹1.45 of marketing per activated user, the cheapest acquisition Holt will ever buy. Why not 3: it doubles the free cost without doubling sharing. Raise it to 2–3 later if conversion is strong.

### Abuse, and what to do about it

| vector | cost to Holt | mitigation |
|---|---|---|
| Many Google or GitHub accounts farming free AI | ₹1.45–1.86 per report | Free AI only for GitHub sign-ins (to build) with an account older than 30 days (**A**). The global budget caps the damage. |
| Scripted AI jobs from many IPs | as above | The existing per-user and per-IP limits (`HOLT_USER_RATE_PER_HOUR`), plus the global budget. |
| Prompt injection making long outputs | up to max tokens per call | Cap `max_tokens` per stage (check that it's set). Alert when a job costs over ₹5. |
| Rules-report floods burning GitHub points | points only | Already mitigated: anonymous rate limits, the cache, and badge-lane caps. |
| Reselling a paid account | small | Ignore at this scale. |

---

## 5. Revenue beyond plans
Ranked by expected money in the next 90 days for the effort, for a solo student founder.

| # | option | effort | money in 90 days (**A**) | honest take |
|---|---|---|---|---|
| 1 | **Campus workshops and club partnerships** (Thapar first, through the senior; then other Punjab/NCR colleges) | medium: a 90-minute "your first open-source PR" session using Holt | ₹0–15k (2–5 sessions at ₹0–5k, often paid from club or department budgets) | **Most realistic.** It's also the best adoption channel. Charge when there's a budget and do it free when there isn't; the users are worth more than the fee. |
| 2 | **GitHub Sponsors** | low (a profile plus a README badge) | ₹0–3k | 0% fee on personal sponsorships. Set it up at launch; it costs nothing. |
| 3 | **A labelled sponsor on the /hacktoberfest page** (devrel budgets) | medium: outreach plus a media kit | ₹0–25k, uncertain | Budgets for Oct 2026 are mostly spent, so aim at GSoC (Feb–Mar) and Hacktoberfest 2027. Label it clearly, and never let a sponsor touch verdicts. |
| 4 | **A paid API** (Pro "API access, coming later") | medium–high: keys, docs, billing | ₹0–2k | Very little demand yet. Build it after a user asks twice. |
| 5 | **A maintainer or organisation tier** (dashboard, alerts, "how welcoming is my repo") | high | ~₹0 in 90 days | A good long-term product, but it takes longer than 90 days to sell to maintainers. Keep the badge free, because it spreads Holt. |
| 6 | **Open Collective** | low | ₹0–2k | 10% host fee. Only useful if a company wants an invoice for a donation. |
| 7 | **Affiliate links or a job board** | medium | small | **Avoid for now.** It conflicts with "the verdict can't be bought" and would cost trust, which is the product. |

---

## 6. Recommendations

### Pricing changes
1. **Pro: 250 → 100 AI reports a month** at ₹299, until a cheaper model passes the evaluation. Pro users rarely need 250 reports in a month anyway (**A**).
2. **Free AI: 3 → 1 a month**, with a ₹1,000 monthly budget cap (to build) and GitHub-login age checks.
3. **International: keep Pro at $5 or raise it to $6.** $5 leaves a thin margin (−₹53 at worst). $6 is safer. Don't add a $2 pack: Dodo's fixed 40¢ takes 26% of it. Make any USD pack at least $4.
4. **Decide the GST wording now:** "prices include all taxes", while below the threshold.
5. **Cache AI reports for 72 hours instead of 24.** Verdict data moves slowly, and cache hits are free. `HOLT_CACHE_HOURS` currently covers both modes, so this needs a separate AI setting.

### Launch on 1 Oct vs later

| launch on 1 Oct | by mid-Oct | later (Q1 2027) |
|---|---|---|
| unlimited free rules reports, find, starter issues, badge | Razorpay live (on the 0% offer): Student ₹99 and packs ₹49 | Dodo for international Pro |
| free AI 1 a month (GitHub sign-in) + BYOK | Pro ₹299/100 | maintainer tier, API |
| GitHub Sponsors | first campus workshop | sponsor deck for GSoC and Hacktoberfest 2027 |

Billing isn't on staging yet: #28 is waiting for the #12 migrations. Paid plans should follow the launch by about two weeks. Don't delay the free launch for billing.

### Metrics to track every week

| metric | definition | healthy early target (**A**) |
|---|---|---|
| activation | visitors who complete their first report in one session | > 30% |
| signed-in rate | report users who sign in | > 15% |
| AI reports per signed-in user | charged plus cached | 1–2 |
| **cache hit rate** | report views served from cache ÷ all report views | > 40% by week 3 |
| **cost per charged AI report** | OpenRouter spend ÷ charged jobs | ≤ ₹1.60 |
| free AI spend | per day and per month, against the cap | under budget |
| paid conversion | payers ÷ signed-in users | ≥ 0.7% (break-even) |
| GitHub points per report | points used ÷ uncached reports | ≈ 11 (alert at 25) |
| shares and badges | share clicks, badge embeds | rising |
| Thapar share | signups with a college email or UTM tag | tells whether the campus channel works |

### The 90-day plan
- **Weeks 0–2 (1–14 Oct):**
  - launch free;
  - Thapar session through the senior (UTM-tagged links);
  - daily cost and cache dashboard;
  - CA consultation on GST;
  - Razorpay KYC (needs terms, privacy and refund pages).
- **Weeks 3–4:**
  - paid Student plan and packs live (0% fee window);
  - Pro at 100;
  - read activation and conversion, and adjust the free quota (1 → 2 if conversion is ≥ 1.5%).
- **Weeks 5–8 (Nov):**
  - model evaluation of nano, deepseek and qwen against gpt-5-mini;
  - if one passes, move free AI to it first (the cheapest risk);
  - 2 more college workshops;
  - write up the Hacktoberfest numbers as a public post (publicity).
- **Weeks 9–13 (Dec):**
  - decide on international (Dodo) based on non-Indian traffic;
  - sponsor deck for the GSoC season;
  - decide whether the maintainer tier is worth building, from badge-embed numbers.

---

## 7. Risks

| risk | how it happens | mitigation |
|---|---|---|
| **AI cost spike** | model price changes, long outputs, farming, a viral day | the global free-AI budget; per-stage `max_tokens`; a prepaid OpenRouter balance; the cache; a cheaper evaluated model on standby |
| **GitHub rate limits at scale** | 5,000 points an hour per token, about 450 fresh rules reports an hour | the cache (24h reports, starter issues), the warm pass for popular repos, a **GitHub App** (up to 12,500 an hour per installation). Pooling many personal tokens may break GitHub's terms, so prefer an App. |
| **Payment compliance** | Razorpay KYC and website policy pages; recurring-mandate rules; GST at ₹20 lakh; USD payouts need proof of foreign remittance | publish terms, privacy and refund pages before KYC; a CA consultation; start INR-only |
| **Brand risk from verdicts on popular repos** | "Not worth your time" on a famous project goes viral; maintainers push back | verdicts are fixed rules with cited evidence; say "for a first-time contributor, right now", not "bad project"; show "Not enough evidence" when unsure; a clear "maintainer? tell us" path; never publish "worst repos" lists; the badge only shows positive or neutral states (check this) |
| **Single point of failure** | the home server, power or ISP | the Cloudflare tunnel survives an IP change; keep a Hetzner image ready (~₹700 a month) for when uptime matters more than cost |
| **Founder time** | a student schedule | automate the numbers (the dashboard), do workshops in batches, say no to the maintainer tier until the data asks for it |

---

## Sources (read 25 Sep 2026)
- OpenRouter model prices: `https://openrouter.ai/api/v1/models`. Credit fee (5.5%, $0.80 minimum): https://openrouter.ai/docs/faq and https://openrouter.ai/pricing
- Razorpay fees: https://razorpay.com/pricing/ ("Last updated: May 2026"). 90-day offer: https://razorpay.com/terms/90-day-free-pg-offer/. UPI mandates: https://razorpay.com/docs/payments/payment-gateway/s2s-integration/recurring-payments/upi/
- Dodo Payments: https://dodopayments.com/pricing, https://docs.dodopayments.com/features/payouts, https://docs.dodopayments.com/miscellaneous/faq
- GST: CGST Act s.24 (compulsory registration), https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter6/section24_v1.00.html. Thresholds: https://cleartax.in/s/gst-registration-limits-increased. LUT: https://cleartax.in/s/gst-export-bond-and-lut
- Hetzner: https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/. DigitalOcean: https://www.digitalocean.com/pricing/droplets. Hostinger: https://www.hostinger.com/in/vps-hosting
- Domains: Porkbun pricing API (`https://api.porkbun.com/api/json/v3/pricing/get`); Cloudflare at-cost prices via https://cfdomainpricing.com (secondary)
- Email: https://resend.com/pricing, https://www.brevo.com/pricing/
- GitHub limits: https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api
- GitHub Sponsors fees: https://docs.github.com/en/sponsors/sponsoring-open-source-contributors/about-sponsorships-fees-and-taxes. Open Source Collective fees: https://docs.oscollective.org/welcome-and-introduction-to-osc/fees
- Conversion benchmarks: https://chartmogul.com/reports/saas-conversion-report/ (Feb 2026, B2B sample)
- Exchange rate $1 = ₹96.02: https://open.er-api.com (25 Sep 2026)
- Measured in this repo: tokens per report from `fixtures/trajectories/*.jsonl` (71 runs); GitHub points per rules report on staging (2 runs, 11 points each)

### Unconfirmed
- Razorpay: whether UPI pays the 2% platform fee (its page says both "0% MDR" and "2% platform fee"), and the UPI Autopay price. Ask at onboarding.
- Whether Dodo collects Indian GST on sales to Indian customers, and whether a payout from Dodo counts as a zero-rated export (ask a CA).
- Hetzner's IPv4 price. Electricity cost of the home server. Everything marked **A**.
