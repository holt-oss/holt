# Holt business strategy, v2: credits, Pro first, foreign payers

*25 Sep 2026, for the Hacktoberfest launch (1 Oct 2026). Prices were checked that day; sources are at the end. **A** marks an assumption.*

### What changed from v1
- **Real hosting instead of the home server** (commercial use). I recommend a Hetzner CX23 at **₹775 a month** ($8.07).
- **Credits instead of report counts**, like v0. Different models cost different numbers of credits: the free tier uses cheap models only, and paid users get every model.
- **Pro is the main plan and foreign payers the main target.** It costs **$6** through Dodo, or **₹299** in India through Razorpay.
- **"Student" is now a verified 50% discount on Pro**, not a separate, weaker plan.
- **The goal is at least ₹50,000 in revenue** (assumed: in the first 6 months, by 31 Mar 2027), not just breaking even.
- **The domain is $15 a year.** Fixed costs are now **₹895 a month**.

---

## The short version
- **The price sheet:**
  - **Free:** unlimited rules reports, plus 10 credits a month on cheap models (≈ 5 AI reports).
  - **Pro:** $6/mo for 600 credits, or ₹299 for 400 credits in India.
  - **Verified student Pro:** $3 for 300 credits, or ₹149 for 200.
  - **Top-ups:** $5 for 500 credits, or ₹199 for 250.
- **1 credit = $0.01 at list price** (₹0.75 in India). Each model's credit cost per report is set so that **the model costs at most 33% of what the user pays for those credits, even on a long report.**
- **Every paid item keeps at least 48% of its price** as contribution even if the user spends every credit. At typical use it keeps **70–85%**.
- **Fixed costs: ₹895 a month.** On top of that, free AI spend is capped at **₹1,000 a month**, so the worst month with no revenue costs **₹1,895**.
- **Break-even month:** realistic **Oct**, optimistic **Oct**, pessimistic **Jan**.
- **When revenue passes ₹50k:** realistic in **month 5 (Feb)**, optimistic in **month 3–4**, pessimistic in **month 12**.
- **Runway:** set aside **₹10,000**. That covers about 5 months with zero revenue, or the pessimistic dip (−₹2,300) plus one-time costs with room to spare.

---

## 1. The price sheet

| | Free | **Pro** | **Pro, verified student** | Top-up pack |
|---|---|---|---|---|
| USD (Dodo, merchant of record) | $0 | **$6/mo** | **$3/mo** | **$5** one-time |
| India (Razorpay, INR) | ₹0 | **₹299/mo** | **₹149/mo** | **₹199** one-time |
| credits (USD / India) | 10 a month | 600 / 400 a month | 300 / 200 a month | 500 / 250 |
| rules reports, find, starter issues, badge | unlimited | unlimited | unlimited | — |
| models | free models only | all models | all models | all models |
| priority queue | — | yes | yes | — |
| credits expire | monthly, no rollover | monthly, no rollover | monthly, no rollover | **12 months** |

- **Anonymous visitors** get rules reports only, as today.
- **BYOK stays free and unlimited.** It's a good answer for students who have credits somewhere else.
- **A top-up unlocks all models** while its credits last, like v0's paid credits. The margin holds on every model (§2).
- **Top-ups are $5 or more.** Dodo's fixed 40¢ makes smaller USD packs a poor deal.
- **Annual plans** ($60 a year, two months free) can come later. They help cash flow once churn is known.

**Positioning:** GitHub Copilot Pro is $10, Raycast Pro $10, Cursor Pro $20, Perplexity Pro $20 and v0 Plus $30. Holt at **$6** is a narrow tool at a coffee price. Cursor is the only one of these with a published India price (₹649 for a limited "Start" plan). Holt's ₹299 is about half its USD price.

**Why India gets fewer credits for its lower price:** models bill Holt in dollars, so a true PPP discount on credits eats the margin. The India price is about 50% of the USD price. India gets 400 credits for ₹299 (**₹0.75 a credit**), and the USD plan gets 600 credits for $6 (₹0.96 a credit). That's still a real regional discount per credit (22%) with a healthy margin. For other lower-income countries, Dodo supports per-country prices and PPP. Use them later with a regional product that has fewer credits, because Dodo's PPP discounts only the price, never the credit grant.

---

## 2. Credits and models

### How credits work (modelled on v0)
- **v0:**
  - Free includes "$5 of included monthly credits". Paid plans include credits equal to the price.
  - Each model burns credits at its own per-token rate (v0 Mini $0.20/$1.20 per 1M tokens, v0 Max $5/$25).
  - Paid-plan monthly credits roll over for one month.
  - Bought credits expire after a year, and only paid plans can buy them.
- **Lovable:** credits, top-ups at $0.30 a credit that last 12 months, and plan credits that expire after 2 months.
- **Perplexity:** "100 credits = $1"; monthly credits don't roll over, and bought ones last a year.
- **Cursor:** charges other models "at the model's API price" from a monthly pool, with pay-as-you-go overage.

**Holt's version: 1 credit = $0.01 at list price.**
- **A fixed credit price per report for each model**, not per token, so users know the cost before they click. Each price is set from the p90 (long-report) cost.
- **Target:** model cost ≤ 33% of the credits' list price on a long report, so a gross margin of at least 67% before payment fees.
- **Formula:** `credits = ceil(p90 cost × 3 / $0.01)`.
- **Recalibrate every month** from the actual cost per job, which the server should log.

### Per-model unit economics
Tokens per report were measured from 71 committed trajectories: 4 calls, median 9.0k in / 6.0k out, p90 13.4k in / 7.5k out. Prices come from the OpenRouter API and include its 5.5% top-up fee.

| model | tier | $/1M tokens in / out | median cost | long-report (p90) cost | **credits per report** | worst cost ÷ credit value |
|---|---|---|---|---|---|---|
| openai/gpt-5-nano | free | 0.05 / 0.40 | $0.0030 | $0.0039 | **2** | 19% |
| deepseek/deepseek-v4.1-flash | free | 0.099 / 0.60 | $0.0048 | $0.0062 | **2** | 31% |
| **openai/gpt-5-mini** (paid default) | paid | 0.25 / 2.00 | $0.0151 | $0.0194 | **6** | 32% |
| google/gemini-3.8-flash | paid | 0.75 / 3.75 | $0.0310 | $0.0403 | **13** | 31% |
| anthropic/claude-sonnet-5 (premium) | paid | 2.00 / 10.00 | $0.0828 | $0.1075 | **33** | 33% |

- **Evaluation first (A):** all token counts come from gpt-5-mini. Every model except gpt-5-mini must pass `docs/EVALUATION.md` before it's offered. Its real tokens then replace the estimate, and its credit price is recalculated.
- **What that means for the free tier:** 10 free credits is 5 reports on nano or deepseek.
- **What that means for Pro (600 credits):** 100 reports on gpt-5-mini, or 18 on Sonnet 5.

### Margin per item
Worst case: every credit spent on the model with the highest cost per credit, all on long reports. Typical: 40% of credits used, median reports. Fees: Razorpay 2% + GST = 2.36%; Dodo about 6% + 40¢ on subscriptions and 5.5% + 40¢ one-time.

| item | price | credits | fee | worst AI cost | **worst contribution** | typical contribution |
|---|---|---|---|---|---|---|
| Pro (USD) | $6 (₹576) | 600 | ₹73 | ₹188 | **₹315 (55%)** | ₹445 (77%) |
| Student (USD) | $3 (₹288) | 300 | ₹56 | ₹94 | **₹138 (48%)** | ₹203 (70%) |
| Top-up (USD) | $5 (₹480) | 500 | ₹65 | ₹156 | **₹259 (54%)** | ₹366 (76%) |
| Pro (India) | ₹299 | 400 | ₹7 | ₹125 | **₹167 (56%)** | ₹253 (85%) |
| Student (India) | ₹149 | 200 | ₹4 | ₹63 | **₹83 (56%)** | ₹126 (85%) |
| Top-up (India) | ₹199 | 250 | ₹5 | ₹78 | **₹116 (58%)** | ₹170 (85%) |

- **The v1 problem is fixed.** v1's Pro could lose money; with credits no item can, whatever model the user picks.
- **GST: not charged at launch (to confirm with a CA).**
  - Below ₹20 lakh a year, an individual in Punjab selling on their own site doesn't need GST registration.
  - Dodo is the merchant of record for USD sales and handles VAT and sales tax.
  - Show "prices include all taxes".

---

## 3. Hosting: the recommendation

Real memory use on staging, 25 Sep:

| service | memory |
|---|---|
| web | 72 MB |
| API | 83 MB |
| Postgres | 32 MB (8 MB database) |
| edge | 7 MB |
| warm/job process | ~85 MB |
| **total** | **≈ 280 MB steady** |

- **Build images in GitHub Actions** and pull them to the server, so the server never needs the RAM a Next.js build takes.

| option | what | per month | notes |
|---|---|---|---|
| **A. Hetzner CX23 (pick)** | 2 vCPU / 4 GB / 40 GB, EU. Web, API, Postgres and jobs in Docker; Hetzner backups (20%); nightly `pg_dump` to Cloudflare R2 (free up to 10 GB) | **€7.09 = $8.07 = ₹775** | Cheapest. 4 GB is 10× today's use. EU→India adds about 130–150 ms, but foreign payers are the target and Cloudflare sits in front anyway. CX23 is sometimes sold out; resize to **CX33** (4 vCPU / 8 GB, €8.49) if so: **₹1,170** all-in. |
| B. DigitalOcean Bangalore | 2 vCPU / 4 GB droplet $24 + weekly backups $4.80; self-run Postgres. Or add Managed Postgres (+$15.15) | $28.80 = **₹2,765** (managed: **₹4,220**) | Best latency in India, 3.5–5× the price. |
| C. Vercel Pro + small VPS | Vercel Pro $20 (Hobby is non-commercial by its terms) + Hetzner CX23 for API and Postgres | $28 = **₹2,700** | Adds nothing Holt needs, and brings a second bill and function limits. |
| Managed Postgres alone | Neon free (0.5 GB), Supabase free (pauses after a week idle), DO $15.15, Vultr $18, Linode $16 | $0–18 | Not needed at 8 MB. Revisit at 5 GB or when uptime matters. |

**Pick: A, Hetzner CX23 with self-run Postgres, Hetzner backups, and nightly dumps to R2.**

| fixed item | ₹ per month |
|---|---|
| hosting (CX23 + backups + IPv4) | 775 |
| domain ($15 a year) | 120 |
| email (Resend free tier) | 0 |
| **total** | **₹895 = $9.30** |

- **Keep staging on the home server.** Staging isn't commercial use.
- **Cloudflare stays in front** (free), for caching and to hide the origin.

---

## 4. Break-even, runway, and the path to ₹50k

### Assumptions (A)
- Subscribers grow linearly and are counted **net of churn**.
- Each free signed-in user costs ₹0.90 a month in AI (3 of their 10 credits on cheap models), and total free AI spend is **capped at ₹1,000 a month**.
- Fixed costs: ₹895 a month.
- Contribution per payer at typical use:

  | payer | contribution a month |
  |---|---|
  | USD Pro | ₹445 |
  | India Pro | ₹253 |
  | India student | ₹126 |
  | USD student | ₹203 |
  | USD top-up | ₹318 |
  | India top-up | ₹145 |

### Scenarios: revenue, break-even and ₹50k

| scenario | new subscribers per month (USD Pro / India Pro / students) | break-even month | revenue by month 3 (Dec) | **revenue by month 6 (Mar)** | revenue by month 12 (Sep) | subscribers in March |
|---|---|---|---|---|---|---|
| pessimistic | +0.5 / +0.5 / +1 | **Jan** | ₹1,968 | ₹11,690 | **₹50,722** | 10 |
| **realistic** | +3 / +2 / +5 | **Oct** | ₹21,789 | **₹78,583** (₹50k passed in Feb) | ₹2.97 lakh | 59 |
| optimistic | +7 / +4 / +10 | **Oct** | ₹47,898 | ₹1.71 lakh | ₹6.43 lakh | 125 |

The months (realistic case):

| month | subscribers | revenue | net after all costs | cumulative revenue |
|---|---|---|---|---|
| Oct | 9 | ₹3,373 | ₹1,019 | ₹3,373 |
| Nov | 19 | ₹7,263 | ₹3,748 | ₹10,636 |
| Dec | 29 | ₹11,152 | ₹6,757 | ₹21,789 |
| Jan | 39 | ₹15,042 | ₹9,767 | ₹36,830 |
| Feb | 49 | ₹18,931 | ₹12,776 | **₹55,762** |
| Mar | 59 | ₹22,821 | ₹15,785 | ₹78,583 |

### What ₹50k in 6 months takes
₹50k over 6 months is **₹8,300 a month on average**. With subscribers growing steadily, that means about **50 subscribers by month 5–6**. The realistic mix above hits it with, in March:

| payer type | count in March |
|---|---|
| USD Pro | 17 |
| India Pro | 12 |
| India students | 25 |
| USD students | 5 |
| top-ups | ~13 a month |

**Foreign Pro is the lever:** one USD Pro is worth two India Pros or four Indian students. Other ways to average ₹8,300 a month:

| mix (average paying subscribers over the 6 months) | revenue a month |
|---|---|
| 10 USD Pro + 5 India Pro + 7 students | ₹8,300 |
| 14 USD Pro | ₹8,064 |
| 6 USD Pro + 10 India Pro + 6 students + 4 India top-ups | ₹8,136 |

### Runway
**Cash needed before revenue:**

| cost | when | amount |
|---|---|---|
| hosting + domain | monthly | ₹895 |
| free AI (cap) | monthly | ₹1,000 |
| CA consultation | one-time | ~₹2,000 |
| Razorpay KYC | one-time | ₹199 |
| first OpenRouter top-up (float, not spent) | one-time | $15 = ₹1,440 |
| domain, paid upfront | one-time | ₹1,440 |

- **Zero-revenue burn:** at most **₹1,895 a month**.
- **With ₹10,000 set aside,** you last **about 5 months with no revenue at all**. The pessimistic case's worst dip is **−₹2,300** (Dec).
- **Lean mode:** launch on the home server while nothing is paid (free and BYOK only). Move to Hetzner the day paid plans go live, which cuts the first weeks' burn to about ₹1,000.

---

## 5. Free tier: abuse controls and the global budget

**The global cap:**
- A **monthly free-AI budget (₹1,000)**, enforced in the server.
- When it's spent, free AI says "free AI is used up this month". Rules reports stay free, and so do BYOK, paid plans and top-ups.
- Alert the founder at 50%, 80% and 100%.
- OpenRouter is prepaid, which is a second backstop, but paying users share the same key, so the server needs its own counter.

**Controls:**

| vector | control |
|---|---|
| farming with many accounts | Free credits only after GitHub sign-in, for accounts **≥ 30 days old** (**A**). One free grant per GitHub account; Google-only accounts get rules reports only. |
| scripted jobs | The existing per-user and per-IP limits on "work", plus the global cap. |
| long outputs and prompt injection | `max_tokens` per stage, and an alert when any job costs over $0.05. |
| repeated repos | The cache: a fresh AI report is free for everyone and uses no credits. Consider 72-hour caching for AI reports. |
| student-discount abuse | Verification (§6); one verified email per account; re-verify every 12 months. |
| payment fraud and chargebacks | Low value per sale. Razorpay and Dodo do the risk checks; cancel on chargeback. |

---

## 6. Student verification (cheap to build)

| method | cost | verdict |
|---|---|---|
| **University email + one-time code**, domains from the Hipo `university-domains-list` (MIT licence, updated 22 Sep 2026; 10,268 domains, 477 in India) plus Holt's own allowlist | ₹0 (email through Resend's free tier) | **Use this.** Match on suffix (`cs.x.edu` counts as `x.edu`). The list **lacks thapar.edu**, so the allowlist starts with Thapar. It's the same method Lovable uses (university email). |
| GitHub Student Developer Pack | — | **Not possible.** There's no public API or OAuth scope. The partner programme takes 5–10 partners a year, and partner offers must be free. **Worth applying anyway with a free offer** (e.g. 3 months of student Pro): that's distribution, not a check. |
| SheerID | custom quote, sales-led | Too heavy now. Perplexity uses it for Education Pro. |
| ISIC, UNiDAYS | contact sales | No. |

---

## 7. What to change in the billing code
To turn into tasks. Branches: `billing-server`, `billing-web`.

1. **Credits ledger instead of report counts.**
   - Table `credit_ledger (id, user_id, delta, kind: grant_monthly|topup|spend|refund|adjust, source_id, expires_at, created_at)`.
   - The balance is the sum of unexpired rows.
   - Spend the credits that expire soonest first: monthly credits, then top-ups.
   - Replace the monthly counter and pack credits.
2. **A model-to-credits table** in `plans.toml`: `[models.<id>] credits = 6, tier = "free"|"paid", enabled = true`. Plus the OpenRouter id and a max-tokens setting per stage. Recalculate from logged cost monthly.
3. **Charge on job insert, refund on failure.** Keep the "atomic `UPDATE` in the same transaction" pattern from today's quota code, and **log the real cost** (tokens × price) on every job.
4. **Choosing a model:** add `model` to `POST /v1/analyses` (default: the tier default). Reject a paid-tier model without paid credits, returning `needs_credits` (a new error code, documented in `API.md`).
5. **Plans:**
   - Pro and verified-student Pro, in USD and INR;
   - a monthly grant on each successful renewal (webhook);
   - no rollover;
   - top-ups as one-time products that grant credits with a 12-month expiry (Dodo credit-based billing supports one-time credit grants; for Razorpay, grant on the payment webhook).
6. **Currency and region:** INR through Razorpay for India (detected from `CF-IPCountry`, and the user can switch); USD through Dodo for everyone else. Store the currency on the subscription.
7. **Student verification:** an email one-time code, the Hipo list plus an allowlist, a `verified_student_until` date, and a price only verified students can buy. Re-verify yearly.
8. **Free-tier controls:** the global monthly free-AI budget with alerts; the GitHub account-age check; free credits only on free-tier models.
9. **`GET /v1/me`:**
   - balance by bucket (monthly, top-up) and expiry dates;
   - the model list with credit costs and which are unlocked;
   - the student status.

   Update `API.md` in the same PR.
10. **Web:**
    - a pricing page showing the credit table;
    - a model picker showing each model's credit cost;
    - "credits left" in the header menu;
    - a top-up flow and a student verification page.
11. **An admin cost dashboard** (can start as SQL): cost per job by model, cache hit rate, free spend against the cap, conversion.
12. **Tests:** ledger math (expiry order, refunds, parallel spends), webhook idempotency, a model not allowed for a tier.

---

## 8. Launch plan and metrics

| when | what |
|---|---|
| **1 Oct** | Free launch: unlimited rules reports and free AI (10 credits, cheap models), BYOK, GitHub Sponsors. Stays on the home server while nothing is sold. |
| by mid-Oct | Hetzner CX23 live; Razorpay (the 0% fee offer for new accounts covers the launch quarter) with India Pro and top-ups; the student email check; a Thapar workshop through the senior. |
| by end of Oct | Dodo live (USD Pro, student, top-ups); gpt-5-nano and deepseek pass the evaluation, or free models are limited to whichever passes. |
| Nov–Dec | Gemini and Sonnet after evaluation; apply to GitHub Education with a free student offer; post the Hacktoberfest numbers publicly. |
| Jan–Mar | Annual plans; regional USD prices through Dodo for other lower-income countries; decide on the maintainer tier. |

**Weekly metrics:**
- activation (a first report in the same session);
- signed-in rate;
- AI reports per signed-in user;
- **cache hit rate**;
- **cost per job by model** against its credit price;
- free spend against the cap;
- free → paid conversion;
- **the USD share of revenue**;
- churn;
- GitHub points per report (about 11 today).

**Other income (v1 ranking still stands):** campus workshops (the most realistic, and also adoption), GitHub Sponsors (low effort), and a labelled sponsor on the Hacktoberfest page later. Leave the API and maintainer tier for after March, and skip affiliate links.

---

## 9. Risks

| risk | mitigation |
|---|---|
| model price changes or token blow-ups | per-model credit prices recalculated monthly; the 33% cost ceiling; `max_tokens`; the free-AI cap |
| a cheap model gives bad explanations | evaluation before listing; verdicts are rules-based anyway, so a weak model only hurts the explanation, not the verdict |
| GitHub rate limits (5,000 points an hour per token, ~11 per report) | the cache and warm pass; a GitHub App (up to 12,500 an hour); don't pool personal tokens |
| payment and tax | Razorpay KYC needs terms, privacy and refund pages; a CA on GST and on treating Dodo payouts as exports; Dodo payouts are USD-only (a $5 fee under $1,000, $25 SWIFT), so batch them |
| hosting outage on one small VPS | Hetzner backups plus a nightly R2 dump, with a written restore script; a resize takes minutes |
| brand risk from verdicts | cited evidence, "for a first-time contributor, right now" wording, a "maintainer? tell us" path, no "worst repos" lists |

---

## Sources (read 25 Sep 2026)
- **Measured in this repo:**
  - tokens: `fixtures/trajectories/*.jsonl` (71 runs, product calls only);
  - GitHub points: staging, 2 runs, 11 each;
  - memory: `docker stats` on staging.
- **OpenRouter:**
  - model prices: `https://openrouter.ai/api/v1/models`;
  - fees: https://openrouter.ai/docs/faq, https://openrouter.ai/pricing
- **Pricing mechanics:**
  - v0: https://v0.app/pricing, https://v0.app/docs/pricing, https://v0.app/students
  - Cursor: https://cursor.com/pricing, https://cursor.com/docs/account/pricing
  - Lovable: https://lovable.dev/pricing, https://docs.lovable.dev/introduction/plans-and-credits, https://lovable.dev/students
  - Perplexity: https://www.perplexity.ai/hub/pricing, and its credits and Education Pro help articles (Sep 2026)
  - GitHub Copilot: https://github.com/features/copilot/plans
  - Raycast: https://www.raycast.com/pricing
- **Payments:**
  - Razorpay: https://razorpay.com/pricing/ and https://razorpay.com/terms/90-day-free-pg-offer/
  - Dodo fees: https://dodopayments.com/pricing
  - Dodo features: https://docs.dodopayments.com/features/credit-based-billing, https://docs.dodopayments.com/features/purchasing-power-parity, https://docs.dodopayments.com/features/payouts
- **GST:**
  - CGST Act s.24: https://taxinformation.cbic.gov.in/content/html/tax_repository/gst/acts/2017_CGST_act/active/chapter6/section24_v1.00.html
  - https://cleartax.in/s/gst-registration-limits-increased
- **Hosting:**
  - Hetzner: https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/ and the price API the site calls
  - DigitalOcean: https://www.digitalocean.com/pricing/droplets, https://www.digitalocean.com/pricing/managed-databases
  - Vultr: https://www.vultr.com/pricing/
  - Vercel: https://vercel.com/docs/plans/hobby, https://vercel.com/docs/plans/pro-plan
  - Neon: https://neon.com/pricing
  - Supabase: https://supabase.com/pricing
  - Cloudflare R2: https://developers.cloudflare.com/r2/pricing/
- **Student verification:**
  - Hipo list: https://github.com/Hipo/university-domains-list
  - GitHub Education partners: https://github.com/education/partners
  - SheerID: https://www.sheerid.com/pricing/
- **Other:**
  - Resend: https://resend.com/pricing
  - GitHub limits: https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api
  - exchange rate $1 = ₹96.02: https://open.er-api.com (25 Sep 2026)

### Unconfirmed
- Razorpay: whether UPI pays the 2% platform fee (its page says both "0% MDR" and "2% platform fee"). I assumed 2.36% everywhere.
- Whether Hetzner prices include VAT (they're normally shown without it). Whether CX23 is in stock.
- Whether Neon and Supabase free tiers allow commercial use (their terms don't say they don't).
- Every **A**, especially the growth ramps and conversion. Measure from week 2 and replace them.
