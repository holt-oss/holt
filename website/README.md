# Holt website (legacy)

**This is the old static landing page.** It still serves the live site until
the web app in [`web/`](../web/) launches in production, and then it goes.
Don't extend it: new pages, copy and features belong in `web/`.

```sh
cd website
npm install
npm run dev
```

`npm run build` writes the deployable site to `website/dist/`.

## Motion

GSAP and ScrollTrigger handle entrance, scroll-linked, and product-reveal
animation. Lenis supplies smooth scrolling and is synchronized with the GSAP
ticker. All non-essential motion is disabled when the browser reports
`prefers-reduced-motion: reduce`.
