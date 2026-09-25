"use client";

// The site cat from the original landing page. Static HTML first; GSAP,
// ScrollTrigger and Lenis load after the page is idle, and never when the
// visitor prefers reduced motion.
import { useEffect, useRef } from "react";
import { CAT, type CatMood } from "@/lib/cat";

const TONE_VAR = { blue: "var(--blue)", green: "var(--green)", orange: "var(--orange)", amber: "var(--amber)" } as const;

export function CatCompanion() {
  const root = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || !matchMedia("(min-width: 1024px)").matches) return;
    let cleanup: (() => void) | undefined;
    let cancelled = false;
    const idle = (cb: () => void) =>
      "requestIdleCallback" in window ? requestIdleCallback(cb, { timeout: 2500 }) : setTimeout(cb, 1200);
    idle(async () => {
      const [{ gsap }, { ScrollTrigger }] = await Promise.all([import("gsap"), import("gsap/ScrollTrigger")]);
      if (cancelled || !root.current) return;
      cleanup = await start(gsap, ScrollTrigger, root.current);
    });
    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, []);

  const c = CAT.ready;
  return (
    <button
      ref={root}
      type="button"
      aria-label="Play with Holt, the site cat"
      data-cat-companion
      className="pointer-events-auto absolute right-0 top-0 z-0 hidden lg:block h-[84px] w-[150px] origin-top-left text-blue opacity-45 [touch-action:manipulation] lg:fixed lg:right-auto lg:left-[calc(50%+380px)] lg:top-[160px] lg:h-[172px] lg:w-[250px] lg:opacity-85"
    >
      <span className="cat-character grid size-full place-items-center">
        <span
          className="cat-face text-[1.5rem] lg:text-[clamp(2.4rem,3.4vw,3.4rem)]"
          data-cat-face
          style={{ textShadow: "0 0 28px color-mix(in oklab, var(--blue) 25%, transparent)" }}
        >
          <span>(=</span>
          <span className="cat-ear">{c.ears[0]}</span>
          <span className="cat-eye" data-cat-eye>{c.eyes[0]}</span>
          <span className="cat-mouth" data-cat-mouth>{c.mouth}</span>
          <span className="cat-eye" data-cat-eye>{c.eyes[1]}</span>
          <span className="cat-ear">{c.ears[1]}</span>
          <span>=)</span>
        </span>
      </span>
    </button>
  );
}

type Gsap = typeof import("gsap").gsap;
type ST = typeof import("gsap/ScrollTrigger").ScrollTrigger;

const POSE: Partial<Record<CatMood, string>> = {
  ready: "curious",
  startled: "startled",
  heartbroken: "heartbroken",
  determined: "determined",
  celebrating: "celebrating",
  adoring: "adoring",
};

async function start(gsap: Gsap, ScrollTrigger: ST, cat: HTMLButtonElement) {
  gsap.registerPlugin(ScrollTrigger);
  const character = cat.querySelector<HTMLElement>(".cat-character")!;
  const face = cat.querySelector<HTMLElement>("[data-cat-face]")!;
  const eyes = [...cat.querySelectorAll<HTMLElement>("[data-cat-eye]")];
  const mouth = cat.querySelector<HTMLElement>("[data-cat-mouth]")!;
  const ears = [...cat.querySelectorAll<HTMLElement>(".cat-ear")];
  const desktop = matchMedia("(min-width: 1024px)").matches;
  let current: CatMood = "ready";
  let hovered = false;
  let reaction: number | undefined;

  const glyphs = (m: CatMood) => {
    const s = CAT[m];
    eyes.forEach((e, i) => (e.textContent = s.eyes[i]));
    ears.forEach((e, i) => (e.textContent = s.ears[i]));
    mouth.textContent = s.mouth;
  };

  const pose = (name?: string) => {
    gsap.killTweensOf([face, ears, eyes, mouth]);
    gsap.set([face, eyes, mouth, ears], { clearProps: "x,y,rotation,scale,scaleX,scaleY" });
    const t = gsap.timeline();
    if (name === "curious") t.fromTo(face, { rotation: -4, y: 2 }, { rotation: 3, y: 0, duration: 0.38, ease: "power2.out" });
    if (name === "startled") t.fromTo(face, { y: 5, scale: 0.94 }, { y: -5, scale: 1.04, duration: 0.22 }).to(face, { y: 0, scale: 1, duration: 0.3 });
    if (name === "heartbroken")
      t.to(ears, { y: 3, rotation: (i: number) => (i ? -8 : 8), duration: 0.3 }).to(face, { y: 5, rotation: -3, duration: 0.4 }, 0);
    if (name === "determined") t.fromTo(face, { x: -3 }, { x: 3, duration: 0.12, yoyo: true, repeat: 1 }).to(face, { x: 0, duration: 0.2 });
    if (name === "celebrating") t.fromTo(face, { y: 3, scaleY: 0.92 }, { y: -7, scaleY: 1.04, duration: 0.22 }).to(face, { y: 0, scaleY: 1, duration: 0.3 });
    if (name === "adoring") t.fromTo(face, { scale: 0.96, rotation: -3 }, { scale: 1.03, rotation: 3, duration: 0.28, yoyo: true, repeat: 1, ease: "sine.inOut" });
  };

  const setMood = (m: CatMood) => {
    if (!CAT[m] || m === current) return;
    current = m;
    gsap.killTweensOf([face, eyes, mouth, ears]);
    gsap
      .timeline()
      .to(face, { scaleX: 1.14, scaleY: 0.62, y: 5, duration: 0.12, ease: "power2.in" })
      .add(() => glyphs(m))
      .to(cat, { color: TONE_VAR[CAT[m].tone], duration: 0.28 }, 0)
      .to(face, { scaleX: 1, scaleY: 1, y: 0, duration: 0.3, ease: "power2.out" })
      .add(() => pose(POSE[m]));
  };

  // Idle life: blink or twitch ears every few seconds.
  let idleCall: gsap.core.Tween | undefined;
  const idle = () => {
    if (!hovered) {
      if (Math.random() < 0.5) gsap.to(eyes, { scaleY: 0.08, duration: 0.07, yoyo: true, repeat: 1 });
      else
        gsap
          .timeline()
          .to(ears, { y: -3, rotation: (i: number) => (i === 0 ? -6 : 6), duration: 0.15 })
          .to(ears, { y: 0, rotation: 0, duration: 0.25 });
    }
    idleCall = gsap.delayedCall(gsap.utils.random(2.4, 4), idle);
  };
  idleCall = gsap.delayedCall(1.5, idle);

  const restore = () => {
    window.clearTimeout(reaction);
    glyphs(current);
    gsap.to(character, { scale: 1, x: 0, y: 0, rotation: 0, duration: 0.28 });
  };
  const onEnter = () => {
    hovered = true;
    eyes.forEach((e) => (e.textContent = "^"));
    mouth.textContent = "ᴗ";
    gsap.to(character, { scale: 1.04, duration: 0.2 });
    gsap.to(ears, { y: -3, rotation: (i: number) => (i ? 6 : -6), duration: 0.2 });
  };
  const onLeave = () => {
    hovered = false;
    restore();
    gsap.to(ears, { y: 0, rotation: 0, duration: 0.2 });
  };
  const onClick = () => {
    window.clearTimeout(reaction);
    eyes.forEach((e) => (e.textContent = "♥"));
    mouth.textContent = "ᴗ";
    gsap
      .timeline()
      .fromTo(character, { scaleX: 1.06, scaleY: 0.9 }, { scaleX: 0.98, scaleY: 1.06, y: -6, duration: 0.18 })
      .to(character, { scaleX: 1.04, scaleY: 1.04, y: 0, duration: 0.26 });
    reaction = window.setTimeout(restore, 850);
  };
  cat.addEventListener("pointerenter", onEnter);
  cat.addEventListener("pointerleave", onLeave);
  cat.addEventListener("click", onClick);

  // Eyes follow the pointer on desktop.
  let onMove: ((e: PointerEvent) => void) | undefined;
  if (matchMedia("(pointer: fine)").matches) {
    const cx = gsap.quickTo(character, "x", { duration: 0.55, ease: "power3.out" });
    const cy = gsap.quickTo(character, "y", { duration: 0.55, ease: "power3.out" });
    const ex = gsap.quickTo(eyes, "x", { duration: 0.16 });
    const ey = gsap.quickTo(eyes, "y", { duration: 0.16 });
    onMove = (e) => {
      const r = cat.getBoundingClientRect();
      const x = gsap.utils.clamp(-1, 1, (e.clientX - (r.left + r.width / 2)) / (innerWidth * 0.3));
      const y = gsap.utils.clamp(-1, 1, (e.clientY - (r.top + r.height / 2)) / (innerHeight * 0.3));
      cx(x * 10);
      cy(y * 7);
      ex(x * 5.5);
      ey(y * 3.5);
    };
    addEventListener("pointermove", onMove);
  }

  // Mood follows the section in view.
  const sections = gsap.utils.toArray<HTMLElement>("[data-cat-section]");
  const triggers = sections.map((s) =>
    ScrollTrigger.create({
      trigger: s,
      start: "top 56%",
      end: "bottom 56%",
      onEnter: () => setMood(s.dataset.catSection as CatMood),
      onEnterBack: () => setMood(s.dataset.catSection as CatMood),
    }),
  );

  // Desktop: the cat walks from the hero to the right edge and stays with you.
  let journey: gsap.core.Timeline | undefined;
  let lenis: import("lenis").default | undefined;
  if (desktop) {
    const r = cat.getBoundingClientRect();
    const compact = innerWidth < 1180;
    journey = gsap
      .timeline({ scrollTrigger: { trigger: "[data-hero]", start: "top top", end: "bottom 58%", scrub: 0.65 } })
      .to(cat, {
        x: innerWidth - (compact ? 118 : 156) - r.left,
        y: innerHeight * 0.5 - 62 - r.top,
        scale: compact ? 0.36 : 0.43,
        opacity: 0.92,
        ease: "power2.inOut",
      });
    gsap.to(cat, { autoAlpha: 0, scrollTrigger: { trigger: "footer", start: "top 94%", end: "top 75%", scrub: true } });

    if (matchMedia("(pointer: fine)").matches) {
      const { default: Lenis } = await import("lenis");
      lenis = new Lenis({ duration: 1.15, smoothWheel: true, wheelMultiplier: 0.9, anchors: true });
      lenis.on("scroll", ScrollTrigger.update);
      const raf = (time: number) => lenis!.raf(time * 1000);
      gsap.ticker.add(raf);
      gsap.ticker.lagSmoothing(0);
    }
  }

  // Scroll reveals for anything still below the fold.
  const reveals = gsap.utils
    .toArray<HTMLElement>("[data-reveal]")
    .filter((el) => el.getBoundingClientRect().top > innerHeight * 0.9)
    .map((el) =>
      gsap.from(el, { y: 28, autoAlpha: 0, duration: 0.8, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 88%", once: true } }),
    );

  return () => {
    idleCall?.kill();
    triggers.forEach((t) => t.kill());
    journey?.scrollTrigger?.kill();
    journey?.kill();
    reveals.forEach((r) => {
      r.scrollTrigger?.kill();
      r.revert();
    });
    lenis?.destroy();
    if (onMove) removeEventListener("pointermove", onMove);
    cat.removeEventListener("pointerenter", onEnter);
    cat.removeEventListener("pointerleave", onLeave);
    cat.removeEventListener("click", onClick);
    gsap.set(cat, { clearProps: "all" });
  };
}
