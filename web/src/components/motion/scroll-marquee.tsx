"use client";

// The "OPEN / SOURCE" band that slides left as you scroll (from the original
// site). One engine per browser, so they never fight over the transform:
//   1. CSS scroll-driven animation where supported (no JS; desktop and phone),
//   2. otherwise GSAP ScrollTrigger on desktop (GSAP is already loaded there),
//   3. otherwise an IntersectionObserver + rAF fallback on phones.
// Reduced motion: static. The band is clipped by its own wrapper
// (overflow: clip), so it can never widen the page.
import { useEffect, useRef } from "react";

const SHIFT = 18; // percent of the band's width, as on the original site

export function ScrollMarquee({ text }: { text: string }) {
  const band = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = band.current;
    if (!el || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (typeof CSS !== "undefined" && CSS.supports("animation-timeline: view()")) {
      el.dataset.engine = "css";
      return;
    }
    const wrap = el.parentElement!;
    let cleanup: (() => void) | undefined;
    let cancelled = false;

    if (matchMedia("(min-width: 1024px)").matches) {
      el.dataset.engine = "gsap";
      (async () => {
        const [{ gsap }, { ScrollTrigger }] = await Promise.all([import("gsap"), import("gsap/ScrollTrigger")]);
        if (cancelled) return;
        gsap.registerPlugin(ScrollTrigger);
        const tween = gsap.to(el, {
          xPercent: -SHIFT,
          ease: "none",
          scrollTrigger: { trigger: wrap, start: "top bottom", end: "bottom top", scrub: true },
        });
        // Positions depend on layout; measure again once web fonts have settled.
        void document.fonts?.ready.then(() => !cancelled && ScrollTrigger.refresh());
        cleanup = () => {
          tween.scrollTrigger?.kill();
          tween.kill();
        };
      })();
    } else {
      el.dataset.engine = "raf";
      let frame = 0;
      const update = () => {
        frame = 0;
        const r = wrap.getBoundingClientRect();
        const p = Math.min(1, Math.max(0, (innerHeight - r.top) / (innerHeight + r.height)));
        el.style.transform = `translate3d(${-SHIFT * p}%,0,0)`;
      };
      const onScroll = () => {
        if (!frame) frame = requestAnimationFrame(update);
      };
      const io = new IntersectionObserver(([e]) => {
        if (e.isIntersecting) {
          addEventListener("scroll", onScroll, { passive: true });
          update();
        } else removeEventListener("scroll", onScroll);
      });
      io.observe(wrap);
      cleanup = () => {
        io.disconnect();
        removeEventListener("scroll", onScroll);
        cancelAnimationFrame(frame);
      };
    }
    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, []);

  return (
    // overflow: clip, not hidden: hidden would make this a scroll container, and
    // the band's view() timeline would then track this static box, not the page.
    <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-5 overflow-clip" data-marquee-wrap>
      {/* Generated content, so it isn't read or contrast-checked as text. */}
      <div
        ref={band}
        data-marquee
        data-text={text}
        className="marquee w-max whitespace-nowrap text-[clamp(2.2rem,7vw,7rem)] font-bold leading-none tracking-[-0.06em] text-blue opacity-[0.09] will-change-transform before:content-[attr(data-text)]"
      />
    </div>
  );
}
