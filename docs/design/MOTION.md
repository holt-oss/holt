# Holt motion and loading plan

*25 Sep 2026. Research for the "too snappy, like a government website" feedback. No code yet; the checklist in §8 is for the web worker, after the mobile-fixes PR.*

## The short version
- **Why it feels abrupt:**
  - Menus are `<details>` elements that snap open and never close when you click elsewhere.
  - No route has a `loading.tsx`.
  - Nothing has a motion token, so every change is an instant swap.
- **What good sites do (measured, §1):**
  - Hover and colour: **80–160 ms**.
  - Menus and popovers: **180–250 ms**, opacity plus a **tiny** scale (.95–.98) or a **4–6 px** shift, on a decelerating curve.
  - Exits about **⅔** of entrances.
  - Page changes are mostly an instant swap, with skeletons for data and a delayed progress bar (GitHub).
- **Holt's plan:**
  1. **Motion tokens** in CSS variables.
  2. **Native popovers + `@starting-style`** for every menu: zero JavaScript, and they close when you click outside.
  3. **React `<ViewTransition>`**, which our Next 16.3 supports with **no configuration**, for a subtle page crossfade, the free/AI tab crossfade and skeleton → content reveals.
  4. **`loading.tsx` skeletons on every route**, with one shared `<Skeleton>`, a 300 ms appearance delay (§4.1) and a single-sweep shimmer.
  5. **No new JS library.** Motion (motion.dev) costs 8–47 KB gzipped; the CSS we need is under 1 KB.
- **Performance:** the mobile budget holds. There's no GSAP on phones, and view transitions only run on navigation, never during the first load that Lighthouse measures. Hero text keeps the rule from #34: never start the LCP text at opacity 0 on phones.
- **Reduced motion:** movement is removed and very short fades stay, as Linear and GitHub do.

---

## 1. What the best sites actually do
Measured 25 Sep 2026 with Playwright and the cached Chromium, at 1440×900, signed out, by polling `document.getAnimations()` after each interaction. The CSS was grepped for tokens.

| site | common durations | easing / tokens | menu or tab (measured) | page navigation | reduced motion |
|---|---|---|---|---|---|
| **Linear** | 160, 200, 120, 180 ms | `--ease-out-quad (.25,.46,.45,.94)`; `--speed-quickTransition .1s`, `--speed-regularTransition .25s` | popup: **opacity + scale .98 → 1, 180 ms**; close is a mirror (180 ms); trigger colour 100 ms | soft navigation, instant swap | movement only inside `(prefers-reduced-motion: no-preference)` |
| **v0** | 200, 150, 300 ms | Tailwind/Geist tokens, `(.22,1,.36,1)` | dropdown: **opacity + scale .95 → 1, 200 ms**, mirror on exit; chevron rotates 150 ms | full page load | 10 rules |
| **Vercel** | 150, 200, 250 ms; hover 100–150 ms | `--ease-out (0,0,.2,1)`; Geist `--ds-motion-popover-duration .2s`, overlay .3s, scale .96 | mega-menu: **no animation**; the page behind fades | soft navigation, instant | 21 rules |
| **Stripe** | 300, 500, 150, 200 ms | `(.25,1,.5,1)`; `--navigation-menu-transition-delay .1s` | popup: **clip-path wipe, 200 ms**; backdrop 240 ms after a **100 ms hover-intent delay**, no delay on close | full load | the strongest: reduce zeroes 453 of 462 transitions |
| **GitHub** | 80, 200, 250 ms | Primer: micro/short/medium/long = **100/200/300/500 ms**; **enter 300 ms ease-out `(.3,.8,.6,1)`, exit 200 ms ease-in `(.7,.1,.75,.9)`** | overlays: scale-fade 200 ms | soft navigation (Turbo) **with a top bar** (grows 300 ms, fades out 150 ms) **and skeletons** (1.5 s shimmer) on Issues | movement inside `no-preference` |
| **Apple** | 320, 240, 80 ms | `(.4,0,.6,1)` | flyout: height 254 ms; items **fade + 4 px rise, 320 ms, staggered 80–280 ms**; **close 180–240 ms, no stagger** | full load | not measured |
| **Raycast** | 300, 200, 150 ms | mostly `ease-in-out`; a spring as `linear()` | monthly/yearly toggle: **pill slides by `transform`, 200 ms** | soft navigation; old page held, then an instant swap | 10 rules |

**Published guidance:**

| source | numbers |
|---|---|
| NN/g | 100–400 ms for most UI; about 100 ms for simple feedback; 200–300 ms for big changes; ≥ 500 ms "a drag"; exits shorter ("300 ms in, 200–250 out") |
| Material 3 | short 50–200 ms, medium 250–400 ms; standard curve `(.2,0,0,1)`, emphasized decelerate `(.05,.7,.1,1)` |
| IBM Carbon | 70/110/150/240/400/700 ms. "Productive" (everyday) `(.2,0,.38,.9)`, exits accelerate |
| Progress bars | nprogress has no delay; **Inertia shows its bar after 250 ms, Turbo after 500 ms** |

**Browser support** (caniuse and MDN data, Sep 2026):

| feature | Chrome | Safari | Firefox |
|---|---|---|---|
| same-document View Transitions | 111+ | 18.0+ | 144+ |
| cross-document `@view-transition` | 126+ | 18.2+ | no |
| nested groups | 140+ | no | no |

**Takeaway:**
- Use short, decelerating, tiny-distance motion.
- Make exits faster than entrances.
- Show skeletons for data.
- Delay any progress bar.
- No site among the seven ships view transitions yet. Use them only as a progressive enhancement: everything must look right without them.

---

## 2. Motion tokens
Add to `web/src/app/globals.css`, next to the colour tokens:

```css
:root {
  --dur-press: 80ms;     /* :active scale */
  --dur-fast: 120ms;     /* hover, colour, small exits */
  --dur-base: 180ms;     /* menus open, tabs, skeleton → content */
  --dur-slow: 240ms;     /* page enter, report sections, mobile sheet */
  --dur-exit: 120ms;     /* exits ≈ ⅔ of entrances */
  --stagger: 50ms;       /* list and report reveal step; stop after 6 items */
  --ease-out: cubic-bezier(0.2, 0, 0, 1);     /* Material standard: everything that enters */
  --ease-in: cubic-bezier(0.4, 0, 1, 1);      /* exits */
  --ease-move: cubic-bezier(0.4, 0, 0.2, 1);  /* things that move and stay (tab pill) */
  --ease-expressive: cubic-bezier(0.16, 1, 0.3, 1); /* landing hero only (existing) */
  --shift: 6px;          /* enter translate */
  --pop-scale: 0.97;     /* menu enter scale */
}
@media (prefers-reduced-motion: reduce) {
  :root { --shift: 0px; --pop-scale: 1; --stagger: 0ms; --dur-slow: var(--dur-fast); }
}
```

- **Convert every hard-coded `160ms ease` / `180ms ease`** in `globals.css` to `var(--dur-fast) var(--ease-out)`.
- **Replace the existing blanket `animation-duration: 0.01ms` reduced-motion rule** with the token approach above plus the view-transition rule in §6. Keep a catch-all only for `animation-iteration-count: 1` on infinite loops.

---

## 3. The patterns

### 3.1 Page navigation: a subtle crossfade
- **Mechanism:** React `<ViewTransition>`.
  - Next 16.3.6 bundles a React canary that exports it (`import { ViewTransition } from "react"`), and `@types/react` 19.3 types it.
  - The Next guide (`node_modules/next/dist/docs/01-app/02-guides/view-transitions.md`) says it works in the App Router **with no configuration**. Route navigations are transitions, so it fires on every `<Link>` click.
- **Where to wrap:** each `page.tsx` body, not the layout, because layouts persist, so enter and exit never fire there. Use one `<PageTransition>` helper:

```tsx
// components/motion/page-transition.tsx (server-safe, no "use client")
import { ViewTransition } from "react";
export function PageTransition({ children }: { children: React.ReactNode }) {
  return <ViewTransition enter="page-in" exit="page-out" default="none">{children}</ViewTransition>;
}
```

```css
::view-transition-old(.page-out) { animation: var(--dur-slow) var(--ease-in) both vt-fade-out; }  /* 240 ms, see §4.1 rule 2 */
::view-transition-new(.page-in)  { animation: var(--dur-slow) var(--ease-out) both vt-rise-in; }
@keyframes vt-fade-out { to { opacity: 0; } }
@keyframes vt-rise-in  { from { opacity: 0; translate: 0 var(--shift); } }
::view-transition { pointer-events: none; }   /* clicks during the 240 ms aren't lost */
```

- **Anchor the header** so only the content moves (from the Next guide):
  - put `style={{ viewTransitionName: "site-header" }}` on `<header>`;
  - `::view-transition-group(site-header) { animation: none; z-index: 100 }`;
  - `::view-transition-old(site-header) { display: none }`.
- **No directional slides.** Holt isn't a deep hierarchy, and none of the measured sites slide pages.
- **Opening a cached report now fades and rises in 240 ms** instead of snapping.

### 3.2 Instant feedback on click
- **`loading.tsx` on every route (§4).** Every route renders dynamically, because the header reads the session. With a `loading.tsx`, the click shows a skeleton immediately, and the page crossfades in when it streams. When the router has nothing to show (a click during an in-flight prefetch, §4.1 rule 6), the layout's `RouteFallback` shows the same skeleton.
- **Links with `prefetch={false}`** (the report tabs, after #34): use `useLinkStatus()` for a fixed-size inline hint. A 2 px underline sweeps under the clicked tab: `opacity` plus a `scaleX` animation, with no layout shift.
- **No global top bar at launch:** skeletons cover it. If it's ever added, show it only after **300 ms** (between Inertia's 250 ms and Turbo's 500 ms): grow with `scaleX` over 300 ms, then fade out in 150 ms, as GitHub does.

### 3.3 Menus: account dropdown and mobile nav
- **Problem:** today both are `<details>`. They snap open, don't close when you click outside, and don't close on Escape reliably.
- **Fix: the Popover API.** `popover` on the panel and `popovertarget` on the button.
  - Top layer, light dismiss and Escape come free.
  - **No JS, so the header stays a server component.**
  - Animate with `@starting-style` and discrete transitions:

```css
.menu[popover] {
  opacity: 1; transform: translateY(0) scale(1); transform-origin: top right;
  transition: opacity var(--dur-exit) var(--ease-in), transform var(--dur-exit) var(--ease-in),
              overlay var(--dur-exit) allow-discrete, display var(--dur-exit) allow-discrete;
}
.menu[popover]:not(:popover-open) { opacity: 0; transform: translateY(-4px) scale(var(--pop-scale)); }
.menu[popover]:popover-open { transition-duration: var(--dur-base); transition-timing-function: var(--ease-out); }
@starting-style { .menu[popover]:popover-open { opacity: 0; transform: translateY(-4px) scale(var(--pop-scale)); } }
```

- **Numbers:** open 180 ms ease-out, close 120 ms ease-in, scale .97 plus 4 px. This matches Linear's .98/180 ms and v0's .95/200 ms.
- **Mobile nav:** a full-width sheet under the header. Same rules, with `translateY(-8px)` and `--dur-slow` on open, plus `::backdrop { background: rgb(0 0 0 / .2) }` fading over 240 ms.
- **Fallback:** a browser without `@starting-style` or `allow-discrete` shows and hides the menu instantly, which is what happens today.
- **Support:** popovers are Baseline 2024, and `@starting-style` is in current Chrome, Safari and Firefox. Check both on caniuse at build time; I didn't measure them.
- **The chevron** rotates 180° in `--dur-fast`.

### 3.4 Tabs: free and AI report
- **The report card crossfades** between modes. Wrap it in `<ViewTransition key={mode} name="report-body" share="auto" enter="auto" default="none">`, the Next guide's "same-route crossfade".
- **The active-tab pill slides** with `transform` over 200 ms `--ease-move`, as Raycast's toggle does. Render one absolutely positioned pill under the two links, and set its `translateX` from `aria-current`.
- **Pending state:** the §3.2 underline hint, since the tabs don't prefetch.

### 3.5 The report reveal
**Order:** verdict → stats → sections → starter issues (streamed).

| element | motion | delay |
|---|---|---|
| verdict headline and sentence (the LCP element) | **none on phones; a 6 px rise without fade on desktop** (the rule from #34: no opacity 0 on the LCP text) | 0 |
| verdict pill and cat face | fade + 6 px | 0 |
| stats grid (existing `.fade-up`) | fade + 6 px, `--dur-slow` | 60 ms + 50 ms per tile (max 6) |
| "your first contribution", evidence, landing map | fade + 6 px | 180, 230, 280 ms |
| starter issues (Suspense) | skeleton → content crossfade (§4) | when streamed |

- **Only when the report arrives on the client.** The SSE "done" handoff in `analysis-runner` is the case. Wrap the swap in `startTransition` so `<ViewTransition>` runs; plain `setState` doesn't trigger it.
- **A server-rendered cached report** uses the page crossfade only (§3.1). No stagger on repeat visits: return visitors shouldn't wait.

### 3.6 Find results appearing
- **Where:** results come from SSE (`find-runner`) or render cached on the server.
- **Motion:** each card fades and rises 6 px over `--dur-slow`. Stagger with `style={{ "--i": index }}` and `animation-delay: calc(min(var(--i), 6) * var(--stagger))`, so the 7th and later cards don't wait.
- **Progress → results:** crossfade by wrapping the setState in `startTransition`, with `<ViewTransition>` on the list: exit 120 ms, enter 240 ms.

### 3.7 Hover and press
| element | hover | press |
|---|---|---|
| buttons (`.btn-*`) | colour and border change, `--dur-fast`, `--ease-out` | `transform: scale(.98)`, `--dur-press` |
| cards (issues, find) | border to `--blue` plus a 1 px shadow deepening, `--dur-fast` | none |
| text links | underline colour, `--dur-fast` | none |

- **Mouse-only hover:** wrap hover styles in `@media (hover: hover)`, so phones don't keep a sticky hover after a tap.

---

## 4. Skeletons

### 4.1 Rules
1. **Match the final layout exactly.** Same grid, gaps and heights, with text lines using the real line-height. **The goal is CLS = 0.** Every skeleton gets a test (§8, step 12).
2. **Don't flash on fast loads.** The skeleton renders at once but becomes visible only after **300 ms** (`--sk-delay`), using `animation: sk-appear var(--dur-fast) var(--ease-out) var(--sk-delay) both` on `.sk-region`, with `sk-appear` going from `opacity: 0`. No JS.
   - *Shipped as 300 ms, not the 100 ms first planned (#48).* React holds a Suspense fallback for at least 300 ms once it has been committed (`FALLBACK_THROTTLE_MS`, rule 3), and `loading.tsx` is committed on every navigation, however fast the server answers. With a 100 ms delay the skeleton would therefore fade in on **every** navigation, hold for the rest of the 300 ms, and swap: a flash on each click. Matching the delay to the throttle means the skeleton is only ever seen when the page really took longer than 300 ms.
   - *Consequence for the page exit (§3.1):* the old page's fade-out is **240 ms** (`--dur-slow`), not the 120 ms `--dur-exit` first planned. During a fast navigation the skeleton is invisible for its first 300 ms; a 120 ms exit would leave the page blank for most of that time. At 240 ms the old page is still fading when the new one starts to rise in.
4. **Crossfade from skeleton to content** with the Next guide's Suspense-reveal pattern:
   - fallback: `<ViewTransition exit="sk-out" default="none">` (fade out, `--dur-exit`);
   - content: `<ViewTransition enter="sk-in" default="none">` (fade + 6 px, `--dur-base`, starting after the exit).
5. **Accessibility:** the wrapper gets `aria-busy="true"` plus a visually hidden "Loading…". Skeleton blocks are `aria-hidden`.
6. **A route can commit as nothing; the layout covers it.** *Found on production (githolt.com, 26 Sep 2026), never locally.* If a link is clicked while its prefetch response is still being applied (on production the prefetch takes 300-800 ms through the Cloudflare tunnel, so the window is easy to hit), Next 16.3's segment cache builds the new route from a prefetch that is still pending: the page segment's prefetched data resolves to `null`, the route's `loading.tsx` boundary ends up in *content* state, and `<main>` holds two empty Suspense boundaries until the real response streams in. The root `loading.tsx` shows first, for under 300 ms (so it never became visible), then nothing. The footer, no longer hidden by `[data-route-loading]`, sat right under the header and was pushed down when the page landed: CLS 0.19 on desktop and 0.38 on phones (`e2e/tests/motion.spec.ts`, the client-navigation and slow-page tests). Chrome counts a visible footer moving into or out of the viewport as a shift, but not one hidden and shown with `display`.
   - **Fix (`components/motion/route-fallback.tsx`, in the root layout):** a client component watches `<main>` with a `MutationObserver`; while it has no element children it renders the loading skeleton of the route in the address bar (the same component as that route's `loading.tsx`, so the swap to content is still shift-free) and removes it when the page arrives.
   - **Two CSS rules make it airtight** (`globals.css`), because React applies those two updates only once the router's view transition is ready, 10-30 ms after the DOM changed: the footer is hidden while `<main>` has no element children (`body:has(main:not(:has(*))) > footer`), and the fallback is `display: none` as soon as it has a sibling (`main > [data-route-fallback]:not(:only-child)`), so the arriving page never pushes it for a frame (that frame alone was CLS 0.93).
   - **Reproduce locally** with a production build (`next build && next start`) and Playwright: delay the prefetch response by about 400 ms (`page.route` on requests with the `next-router-prefetch` header) and click 500 ms after the prefetch request goes out. Without the fallback: root skeleton, empty `<main>`, footer at the top, CLS 0.19. With it: root skeleton, report skeleton, page, CLS 0.

### 4.2 The shimmer: one gradient, no JS
```css
.sk { background: var(--panel-2); border-radius: 2px; position: relative; overflow: hidden; }
@media (prefers-reduced-motion: no-preference) {
  .sk::after {
    content: ""; position: absolute; inset: 0;
    background: linear-gradient(90deg, transparent, color-mix(in oklab, var(--ink) 6%, transparent), transparent);
    translate: -100% 0;
    animation: sk-sweep 1.8s var(--ease-move) infinite;   /* one 1.2 s sweep, then a 0.6 s rest */
  }
}
@keyframes sk-sweep { 66%, 100% { translate: 100% 0; } }
```
- **Cost:** only `translate` animates, on its own compositor layer: no layout or paint per frame.
- **Reduced motion:** the blocks stay a flat, static colour.
- **Dark mode:** `--ink` at 6% works in both themes.

### 4.3 One primitive, per-page skeletons
- **The primitive:** `components/skeleton.tsx` with `<Skeleton className="h-4 w-40" />` (block), `<SkeletonText lines={3} />` and `<SkeletonCard />`.
- **Per-page skeletons** are built from those three and sit next to the real component, so they change together.

### 4.4 Inventory: everything that waits on data

| where | waits on | skeleton shape (must match) | notes |
|---|---|---|---|
| `/` (landing) `loading.tsx` | session (header) | hero headline lines, paste box (h-16 bar), examples row | mostly static; rarely shows, thanks to the 100 ms delay |
| `/` Fig. 01 live report (Suspense) | `getReport` for the sample repo | the figure frame: kicker line, headline 2 lines, 3 stat tiles, one issue card | **today the fallback is the static example figure.** Replace it with the skeleton so the example never swaps for real data with a jump |
| `/[owner]/[repo]` `loading.tsx` | `getReport`, session | repo header (40 px avatar square, 2 text lines, tab pair), verdict card (kicker, 2-line headline, sentence, meta line), share row, stats grid (tiles as `StatsGrid`) | the most important one: cached reports appear as a crossfade instead of a blank wait |
| `/[owner]/[repo]` starter issues (Suspense) | `starterIssues` (streamed, #29) | cards as today's `h-32` placeholders, which **become `<SkeletonCard>`** with title and meta lines | already exists; move it onto the primitive and add the crossfade |
| `/[owner]/[repo]` analysis running (client) | SSE progress | the existing `AnalysisProgress` panel, **plus a dimmed report skeleton below it** at 40% opacity with no shimmer, so the page doesn't jump when the report lands | the report crossfades in (§3.5) |
| `/find` `loading.tsx` | session; `find()` when searched | form (fieldsets as real sizes); when `?go=1`, 3 result cards | |
| `/find` results (SSE or cached) | `find` job | result card: repo line, headline pill, 2 stat lines, 2 issue rows | stagger on reveal (§3.6) |
| `/hacktoberfest` `loading.tsx` | session, tab data | page head, tab bar, 6 repo cards | |
| `/compare` `loading.tsx` / live | reports for 2–4 repos | N columns of the compare card (verdict, 4 stat rows) | columns keep the final widths |
| `/pricing` `loading.tsx` / plans (Suspense, once plans come from `/v1/plans`) | plans API | 3 plan cards (name, price 2.4 rem line, 3 feature lines, CTA 44 px) | |
| `/settings` `loading.tsx` | `me()` | account row, BYOK form (3 inputs at real heights), plan box | |
| `/me/history` `loading.tsx` | `history()` | 6 rows (repo, mode chip, verdict pill, date) | |
| `/how-it-works`, `/signin` | session only | page head + body lines | nearly instant |
| images: repo avatar (40 px), OG preview in the share row if shown | network | reserved box with `--panel-2` background (already sized 40×40); **no shimmer** (too small) | the OG image is server-generated and never shown in the app; nothing to add |
| **browser extension chip** (`extension/src/chip.ts`, `state: "loading"`) | the public report API | a pill sized by its own text ("Holt · checking…" in the chip's font), with the label and stat drawn as flat blocks and the same 1.8 s shimmer as `.sk` in `content.css`; invisible for the first 300 ms like every skeleton; the blocks crossfade into the verdict text over `--dur-base` (a CSS transition on the same elements, so the title row never moves); static and instant under reduced motion | the chip sits inside GitHub's page, so the shimmer is faint (4%) and takes the chip's text colour. The chip cannot read Holt's tokens, so `content.css` carries copies and a test checks they match `globals.css` |

---

## 5. The implementation, cheapest robust version

| need | use | why not something else |
|---|---|---|
| page and tab crossfades, skeleton reveals, list reveal | React `<ViewTransition>` (built into our Next/React) + CSS | zero bytes; works without configuration; falls back to an instant swap |
| menus | Popover API + `@starting-style` + `allow-discrete` | zero JS; fixes click-outside and Escape; the header stays a server component |
| hover, press, shimmer, stagger | CSS with tokens | — |
| pending feedback | `useLinkStatus` (Next) | built in |
| **Motion (motion.dev)** | **not needed** | 7.9–46.6 KB gzipped measured (LazyMotion to full) vs under 1 KB of CSS; nothing here needs springs or layout animation |
| GSAP / Lenis | stay desktop-only on the landing cat, as now | — |
| cross-document `@view-transition` | **no** | Holt is a single app with client navigation; Firefox lacks it |

**Performance:**
- Lighthouse measures a cold load. View transitions only run on client navigations, and `sk-appear` and the shimmer are compositor-only. So calibrated performance (currently 95–99) should hold; re-measure with `e2e/lighthouse.mjs --calibrate`.
- **Never** put an entrance animation that starts at opacity 0 on the LCP text on phones.

---

## 6. Reduced motion
- **Tokens:** `--shift: 0`, `--pop-scale: 1`, `--stagger: 0` (§2). Movement disappears; menus and crossfades become short fades. Linear and GitHub keep hover and colour changes, and so should Holt.
- **View transitions:** keep opacity only.

```css
@media (prefers-reduced-motion: reduce) {
  ::view-transition-group(*) { animation-duration: 0s !important; }
  ::view-transition-new(*), ::view-transition-old(*) { animation-duration: var(--dur-fast) !important; translate: none !important; }
}
```

- **Shimmer:** off (it's inside `no-preference`). The skeleton is a flat block.
- **Infinite animations** (the `scan` progress sweep, the blink): run once, or stop.
- **Test:** Playwright with `reducedMotion: "reduce"`. No `getAnimations()` entry should have a transform keyframe (§8, step 12).

---

## 7. Timings at a glance
| thing | in | out | easing |
|---|---|---|---|
| hover and colour | 120 ms | 120 ms | ease-out |
| press | 80 ms | 80 ms | ease-out |
| menu | 180 ms, scale .97 + 4 px | 120 ms | ease-out / ease-in |
| mobile sheet | 240 ms, 8 px + backdrop | 120 ms | ease-out / ease-in |
| page | 240 ms, fade + 6 px | 240 ms, fade (§4.1 rule 2) | ease-out / ease-in |
| tab content | 180 ms crossfade | 120 ms | ease-out |
| tab pill | 200 ms slide | — | ease-move |
| skeleton appears | after 300 ms, 120 ms fade | — | ease-out |
| skeleton → content | 180 ms, fade + 6 px | 120 ms | ease-out / ease-in |
| shimmer | 1.2 s sweep + 0.6 s rest | — | ease-move |
| list stagger | 50 ms steps, max 6 | — | — |
| progress bar (not at launch) | shows after 300 ms | fade 150 ms | — |

---

## 8. File-by-file checklist
After the mobile-fixes PR lands. One PR, or two: tokens, menus and skeletons first, then view transitions.

1. **`web/src/app/globals.css`:**
   - add the §2 tokens and their reduced-motion overrides;
   - convert hard-coded transitions to tokens;
   - add the `::view-transition` rules (§3.1, §6), the header anchor, `.menu[popover]` (§3.3), `.sk` and the shimmer (§4.2), `sk-appear`, the `.btn` press, and `@media (hover: hover)`;
   - replace the blanket `0.01ms` reduced-motion rule.
2. **`web/src/components/skeleton.tsx` (new):** `Skeleton`, `SkeletonText`, `SkeletonCard`, and a `SkeletonRegion` wrapper with `aria-busy` and "Loading…".
3. **`web/src/components/motion/page-transition.tsx` (new):** `<PageTransition>` (§3.1); **`reveal.tsx`**: an `<SkeletonReveal fallback={…}>` wrapper around `Suspense` with the two `<ViewTransition>`s (§4.1 rule 4).
4. **Every `web/src/app/**/page.tsx`:** wrap the body in `<PageTransition>`.
5. **`web/src/app/**/loading.tsx` (new, one per route):** `/`, `/[owner]/[repo]`, `/find`, `/hacktoberfest`, `/compare`, `/pricing`, `/settings`, `/me/history`, `/how-it-works`, `/signin`. Each renders its page skeleton inside `<PageTransition>`.
6. **Per-page skeletons, next to their components:**
   - `components/report/report-skeleton.tsx`
   - `components/find/find-skeleton.tsx` (form + result cards)
   - `components/compare/compare-skeleton.tsx`
   - `components/sample-report-skeleton.tsx` (Fig. 01)
   - `components/report/starter-issues.tsx`: replace the `h-32 animate-pulse` placeholders with `SkeletonCard`
   - pricing, settings and history skeletons, inline in their `loading.tsx`
7. **`web/src/app/page.tsx`:** the Fig. 01 `Suspense` fallback becomes `<SampleReportSkeleton>` inside `<SkeletonReveal>`.
8. **`web/src/app/[owner]/[repo]/page.tsx`:**
   - the starter-issues `Suspense` goes through `<SkeletonReveal>`;
   - the report body gets `<ViewTransition key={mode} …>` (§3.4);
   - the tab pill;
   - a `useLinkStatus` hint on both tabs (a small client component).
9. **`components/report/analysis-runner.tsx` and `use-analysis.ts`:**
   - on `done`, set the report inside `startTransition`;
   - dim the report skeleton under the progress panel;
   - the verdict and stats stagger (§3.5), keeping the verdict text free of opacity-from-0 on phones.
10. **`components/header.tsx`:**
    - account menu and mobile nav: `<details>` → `button[popovertarget]` + `div[popover].menu`;
    - `viewTransitionName: "site-header"` on `<header>`;
    - the chevron rotation.
11. **`components/find/find-runner.tsx` and `find-results.tsx`:**
    - `startTransition` on results;
    - `<ViewTransition>` around progress → list;
    - `--i` on each card for the stagger.
12. **Tests (`e2e/tests/motion.spec.ts`, new):**
    - CLS stays 0 on `/pallets/flask` (cold and cached), `/find?go=1…`, `/` and `/pricing`. Use a `PerformanceObserver` on `layout-shift` over the whole load and swap.
    - The skeleton is present for slow responses: route the API with a 600 ms delay; the skeleton becomes visible, and the swap happens at least 300 ms later.
    - No skeleton flash for fast responses (under 100 ms).
    - The menu opens and closes: popover state, Escape, click outside.
    - Under `reducedMotion: "reduce"`, no running animation has transform keyframes.
    - Add these to the staging smoke run.
13. **`extension/src/chip.ts` and its stylesheet:** the skeleton loading pill, the shimmer rule (reduced-motion aware) and the crossfade to the verdict (§4.4, last row).
14. **Re-measure:** `node e2e/lighthouse.mjs --runs 3 --calibrate`, which must stay ≥ 90 on `/`, `/pallets/flask` and `/find`, plus a phone and desktop `shot` of the menu open for the PR.

---

## Sources
- **Measured (25 Sep 2026, Playwright + Chromium 1243):** linear.app, v0.app, vercel.com, stripe.com, github.com, apple.com, raycast.com.
- **Next.js 16.3.6 bundled docs:**
  - `node_modules/next/dist/docs/01-app/02-guides/view-transitions.md`
  - `03-api-reference/02-components/link.md` (`transitionTypes`)
  - `03-api-reference/04-functions/use-link-status.md`
- **React internals:** `FALLBACK_THROTTLE_MS = 300` in the bundled `next/dist/compiled/react-dom/cjs/react-dom-client.development.js`; the `ViewTransition` export in `next/dist/compiled/react`.
- **React docs:** https://react.dev/reference/react/ViewTransition
- **Guidance:**
  - NN/g: https://www.nngroup.com/articles/animation-duration/
  - Material 3 tokens: material-web `tokens/versions/v0_192/_md-sys-motion.scss`
  - Carbon: `carbon/packages/motion/src/dtcg/motion.json`
  - Apple HIG Motion: https://developer.apple.com/design/human-interface-guidelines/motion
- **Progress bars:** nprogress source; Inertia https://inertiajs.com/progress-indicators; Turbo https://turbo.hotwired.dev/handbook/drive
- **Browser support:** caniuse `view-transitions.json` and `cross-document-view-transitions.json` (updated 2026-09-24); MDN BCD `view-transition-group.json`
- **Motion bundle size:** https://motion.dev/docs/react-reduce-bundle-size, plus our own esbuild measurement of motion 13.4.4
