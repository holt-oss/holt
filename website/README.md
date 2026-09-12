# Holt website

Production landing page for Holt. This is separate from `website-mockup/`,
which remains the approved static design artifact.

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
