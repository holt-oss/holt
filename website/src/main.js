import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import productImage from "../../assets/holt.png";
import "./styles.css";

gsap.registerPlugin(ScrollTrigger);

const product = document.querySelector("[data-product-image]");
const cat = document.querySelector("[data-cat-companion]");
const catCharacter = document.querySelector(".cat-character");
const catFace = document.querySelector("[data-cat-face]");
const catEyes = [...document.querySelectorAll("[data-cat-eye]")];
const catMouth = document.querySelector("[data-cat-mouth]");
const catEars = [...document.querySelectorAll(".cat-ear")];
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

if (product) {
  product.src = productImage;
  product.addEventListener("load", () => ScrollTrigger.refresh(), { once: true });
}

const catStates = {
  ready: { eyes: ["•", "•"], mouth: "ω", ears: ["^", "^"], color: "#83a9ff", pose: "curious" },
  "observing interface": { eyes: ["◉", "◉"], mouth: "o", ears: ["^", "^"], color: "#83a9ff", pose: "startled" },
  "reading outcomes": { eyes: ["╥", "╥"], mouth: "︵", ears: ["˘", "˘"], color: "#ee925d", pose: "heartbroken" },
  "checking evidence": { eyes: ["¬", "¬"], mouth: "_", ears: ["^", "^"], color: "#83a9ff", pose: "determined" },
  "verdict stable": { eyes: ["˘", "˘"], mouth: "ᴗ", ears: ["^", "^"], color: "#69c7a6", pose: "celebrating" },
  "open source": { eyes: ["♥", "♥"], mouth: "ᴗ", ears: ["^", "^"], color: "#69c7a6", pose: "adoring" },
};

let currentCatState = "ready";
let catIsHovered = false;
let catReactionTimeout;

const applyCatGlyphs = (stateName) => {
  const state = catStates[stateName] ?? catStates.ready;
  catEyes.forEach((eye, index) => { eye.textContent = state.eyes[index]; });
  catEars.forEach((ear, index) => { ear.textContent = state.ears[index]; });
  if (catMouth) catMouth.textContent = state.mouth;
};

const resetCatParts = () => {
  gsap.set([catFace, catEyes, catMouth, catEars], {
    clearProps: "x,y,rotation,scale,scaleX,scaleY",
  });
};

const animateCatPose = (pose) => {
  if (reduceMotion || !catFace) return;
  gsap.killTweensOf([catFace, catEars, catEyes, catMouth]);
  resetCatParts();

  const poses = {
    curious: () => gsap.timeline()
      .fromTo(catFace, { rotation: -4, y: 2 }, { rotation: 3, y: 0, duration: 0.38, ease: "power2.out" }),
    startled: () => gsap.timeline()
      .fromTo(catFace, { y: 5, scale: 0.94 }, { y: -5, scale: 1.04, duration: 0.22, ease: "power2.out" })
      .to(catFace, { y: 0, scale: 1, duration: 0.3, ease: "power2.out" }),
    heartbroken: () => gsap.timeline()
      .to(catEars, { y: 3, rotation: (index) => index ? -8 : 8, duration: 0.3, ease: "power2.out" })
      .to(catFace, { y: 5, rotation: -3, duration: 0.4, ease: "power2.out" }, 0),
    determined: () => gsap.timeline()
      .fromTo(catFace, { x: -3 }, { x: 3, duration: 0.12, yoyo: true, repeat: 1, ease: "power2.inOut" })
      .to(catFace, { x: 0, duration: 0.2 }),
    celebrating: () => gsap.timeline()
      .fromTo(catFace, { y: 3, scaleY: 0.92 }, { y: -7, scaleY: 1.04, duration: 0.22, ease: "power2.out" })
      .to(catFace, { y: 0, scaleY: 1, duration: 0.3, ease: "power2.out" }),
    adoring: () => gsap.timeline()
      .fromTo(catFace, { scale: 0.96, rotation: -3 }, { scale: 1.03, rotation: 3, duration: 0.28, yoyo: true, repeat: 1, ease: "sine.inOut" }),
  };

  poses[pose]?.();
};

const setCatState = (stateName, animate = true) => {
  const next = catStates[stateName] ? stateName : "ready";
  currentCatState = next;
  const state = catStates[next];

  if (!animate || reduceMotion || !cat) {
    applyCatGlyphs(next);
    if (cat) cat.style.color = state.color;
    return;
  }

  gsap.killTweensOf([catFace, catEyes, catMouth, catEars]);
  gsap.timeline()
    .to(catFace, { scaleX: 1.14, scaleY: 0.62, y: 5, duration: 0.12, ease: "power2.in" })
    .add(() => applyCatGlyphs(next))
    .to(cat, { color: state.color, duration: 0.28 }, 0)
    .to(catFace, { scaleX: 1, scaleY: 1, y: 0, duration: 0.3, ease: "power2.out" })
    .add(() => animateCatPose(state.pose));
};

applyCatGlyphs("ready");

const copyButton = document.querySelector("[data-copy]");
const copyStatus = document.querySelector("#copy-status");

copyButton?.addEventListener("click", async () => {
  const original = copyButton.textContent;
  const command = copyButton.dataset.copy;

  try {
    await navigator.clipboard.writeText(command);
    copyButton.textContent = "copied";
    if (copyStatus) copyStatus.textContent = "Install command copied to clipboard.";
    if (catMouth) catMouth.textContent = "ᴗ";
    catEyes.forEach((eye) => { eye.textContent = "^"; });
    if (!reduceMotion) {
      gsap.timeline()
        .fromTo(catCharacter, { scale: 0.94, rotation: -2 }, { scale: 1.04, rotation: 2, duration: 0.2, ease: "power2.out" })
        .to(catCharacter, { scale: 1, rotation: 0, duration: 0.25, ease: "power2.out" });
    }
  } catch {
    copyButton.textContent = "select";
    const commandNode = document.querySelector("#install-command");
    if (commandNode) window.getSelection()?.selectAllChildren(commandNode);
    if (copyStatus) copyStatus.textContent = "Clipboard unavailable; install command selected.";
  }

  window.setTimeout(() => {
    copyButton.textContent = original;
    applyCatGlyphs(currentCatState);
  }, 1500);
});

if (!reduceMotion) {
  const lenis = new Lenis({
    duration: 1.15,
    smoothWheel: true,
    wheelMultiplier: 0.9,
    anchors: true,
  });

  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((time) => lenis.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);

  const intro = gsap.timeline({ defaults: { ease: "power3.out" } });
  intro
    .from("[data-header]", { yPercent: -100, duration: 0.62 })
    .from(".hero__rail", { x: -18, autoAlpha: 0, duration: 0.5 }, 0.22)
    .from("[data-intro]", { y: 16, autoAlpha: 0, duration: 0.55, stagger: 0.08 }, 0.28)
    .from(".headline-line > span", { yPercent: 110, duration: 0.75, stagger: 0.075 }, 0.31)
    .from("[data-cat-companion] .cat-face span", {
      y: 10,
      autoAlpha: 0,
      duration: 0.42,
      stagger: 0.035,
      ease: "power2.out",
    }, 0.46);

  const blink = () => {
    gsap.to(catEyes, {
      scaleY: 0.08,
      duration: 0.07,
      yoyo: true,
      repeat: 1,
      ease: "power2.inOut",
    });
  };

  const idleEmotion = () => {
    if (catIsHovered) {
      gsap.delayedCall(1.4, idleEmotion);
      return;
    }

    const choice = gsap.utils.random(0, 1, 1);

    if (choice === 0) {
      blink();
    } else {
      gsap.timeline()
        .to(catEars, { y: -3, rotation: (index) => index === 0 ? -6 : 6, duration: 0.15, ease: "power2.out" })
        .to(catEars, { y: 0, rotation: 0, duration: 0.25, ease: "power2.out" });
    }

    gsap.delayedCall(gsap.utils.random(2.4, 4), idleEmotion);
  };

  gsap.delayedCall(1.5, idleEmotion);

  if (window.matchMedia("(pointer: fine)").matches && cat) {
    const characterX = gsap.quickTo(catCharacter, "x", { duration: 0.55, ease: "power3.out" });
    const characterY = gsap.quickTo(catCharacter, "y", { duration: 0.55, ease: "power3.out" });
    const eyeX = gsap.quickTo(catEyes, "x", { duration: 0.16, ease: "power2.out" });
    const eyeY = gsap.quickTo(catEyes, "y", { duration: 0.16, ease: "power2.out" });

    window.addEventListener("pointermove", (event) => {
      const rect = cat.getBoundingClientRect();
      const x = gsap.utils.clamp(-1, 1, (event.clientX - (rect.left + rect.width / 2)) / (window.innerWidth * 0.3));
      const y = gsap.utils.clamp(-1, 1, (event.clientY - (rect.top + rect.height / 2)) / (window.innerHeight * 0.3));
      characterX(x * 10);
      characterY(y * 7);
      eyeX(x * 5.5);
      eyeY(y * 3.5);
    });
  }

  const restoreCat = () => {
    window.clearTimeout(catReactionTimeout);
    applyCatGlyphs(currentCatState);
    gsap.to(catCharacter, { scale: 1, x: 0, y: 0, rotation: 0, duration: 0.28, ease: "power2.out" });
    resetCatParts();
  };

  cat?.addEventListener("pointerenter", () => {
    catIsHovered = true;
    gsap.killTweensOf([catCharacter, catFace, catEars]);
    catEyes.forEach((eye) => { eye.textContent = "^"; });
    if (catMouth) catMouth.textContent = "ᴗ";
    gsap.timeline()
      .to(catCharacter, { scale: 1.04, duration: 0.2, ease: "power2.out" })
      .to(catEars, { y: -3, rotation: (index) => index ? 6 : -6, duration: 0.2, ease: "power2.out" }, 0);
  });

  cat?.addEventListener("pointerleave", () => {
    catIsHovered = false;
    restoreCat();
  });

  cat?.addEventListener("click", () => {
    window.clearTimeout(catReactionTimeout);
    gsap.killTweensOf([catCharacter, catFace, catEars, catEyes, catMouth]);
    catEyes.forEach((eye) => { eye.textContent = "♥"; });
    if (catMouth) catMouth.textContent = "ᴗ";

    gsap.timeline()
      .fromTo(catCharacter, { scaleX: 1.06, scaleY: 0.9 }, { scaleX: 0.98, scaleY: 1.06, y: -6, duration: 0.18, ease: "power2.out" })
      .to(catCharacter, { scaleX: 1.04, scaleY: 1.04, y: 0, duration: 0.26, ease: "power2.out" });

    catReactionTimeout = window.setTimeout(restoreCat, 850);
  });

  ScrollTrigger.create({
    start: 20,
    end: "max",
    onUpdate: (self) => document.querySelector("[data-header]")?.classList.toggle("is-scrolled", self.scroll() > 20),
  });

  gsap.to(".scroll-progress span", {
    scaleX: 1,
    ease: "none",
    scrollTrigger: { start: 0, end: "max", scrub: 0.15 },
  });

  const createCatJourney = (mobile = false) => {
    if (!cat) return;
    const startRect = cat.getBoundingClientRect();
    const compactDesktop = window.innerWidth < 1180;
    const targetLeft = mobile
      ? window.innerWidth - 88
      : window.innerWidth - (compactDesktop ? 118 : 156);
    const targetTop = mobile ? 76 : window.innerHeight * 0.5 - 62;
    const targetScale = mobile ? 0.42 : compactDesktop ? 0.36 : 0.43;

    gsap.timeline({
      scrollTrigger: {
        trigger: ".hero",
        start: "top top",
        end: "bottom 58%",
        scrub: 0.65,
        onUpdate: (self) => cat.classList.toggle("is-docked", self.progress > 0.82),
        onLeaveBack: () => cat.classList.remove("is-docked"),
      },
    })
      .to(cat, {
        x: targetLeft - startRect.left,
        y: targetTop - startRect.top,
        scale: targetScale,
        opacity: mobile ? 0.62 : 0.92,
        ease: "power2.inOut",
      }, 0)
      .to(".cat-face--hero", { textShadow: "0 0 0 rgba(0,0,0,0)", ease: "none" }, 0);
  };

  const motionMedia = gsap.matchMedia();
  motionMedia.add("(max-width: 780px)", () => createCatJourney(true));
  motionMedia.add("(min-width: 781px)", () => createCatJourney(false));

  gsap.to(cat, {
    autoAlpha: 0,
    ease: "power2.out",
    scrollTrigger: {
      trigger: "footer",
      start: "top 94%",
      end: "top 75%",
      scrub: true,
    },
  });

  gsap.utils.toArray("[data-cat-section]").forEach((section) => {
    ScrollTrigger.create({
      trigger: section,
      start: "top 56%",
      end: "bottom 56%",
      onEnter: () => setCatState(section.dataset.catSection),
      onEnterBack: () => setCatState(section.dataset.catSection),
    });
  });

  gsap.from("[data-screen]", {
    clipPath: "inset(0 0 100% 0)",
    y: 45,
    duration: 1.15,
    ease: "power3.out",
    scrollTrigger: { trigger: "[data-screen]", start: "top 82%", once: true },
  });

  gsap.from("[data-screen] figcaption", {
    autoAlpha: 0,
    y: -8,
    duration: 0.55,
    delay: 0.35,
    scrollTrigger: { trigger: "[data-screen]", start: "top 82%", once: true },
  });

  gsap.fromTo(".screen__scan", { top: "0%", opacity: 0 }, {
    top: "100%",
    opacity: 0.72,
    duration: 1.25,
    ease: "power1.inOut",
    scrollTrigger: { trigger: "[data-screen]", start: "top 76%", once: true },
  });

  gsap.to("[data-product-image]", {
    yPercent: -3,
    ease: "none",
    scrollTrigger: { trigger: "[data-screen]", start: "top bottom", end: "bottom top", scrub: true },
  });

  gsap.utils.toArray("[data-rail]").forEach((rail) => {
    gsap.from(rail, {
      x: -18,
      autoAlpha: 0,
      duration: 0.65,
      ease: "power3.out",
      scrollTrigger: { trigger: rail, start: "top 86%", once: true },
    });
  });

  gsap.utils.toArray("[data-reveal]").forEach((element) => {
    gsap.from(element, {
      y: 28,
      autoAlpha: 0,
      duration: 0.8,
      ease: "power3.out",
      scrollTrigger: { trigger: element, start: "top 84%", once: true },
    });
  });

  gsap.utils.toArray("[data-thread]").forEach((thread, index) => {
    gsap.from(thread.children, {
      y: 16,
      autoAlpha: 0,
      duration: 0.6,
      stagger: 0.08,
      delay: index * 0.08,
      ease: "power3.out",
      scrollTrigger: {
        trigger: thread,
        start: "top 84%",
        once: true,
        onEnter: () => thread.classList.add("is-visible"),
      },
    });
  });

  gsap.from("[data-trace-row]", {
    x: 18,
    autoAlpha: 0,
    duration: 0.55,
    stagger: 0.1,
    ease: "power3.out",
    scrollTrigger: { trigger: ".trace", start: "top 78%", once: true },
  });

  gsap.to(".trace__cursor", {
    scaleY: 1,
    duration: 0.9,
    ease: "power2.out",
    scrollTrigger: { trigger: ".trace", start: "top 78%", once: true },
  });

  gsap.utils.toArray("[data-score]").forEach((row, index) => {
    const score = Number(row.dataset.score);
    gsap.to(row.querySelector(".score__fill"), {
      scaleX: score,
      duration: 1.05,
      delay: index * 0.12,
      ease: "power3.out",
      scrollTrigger: { trigger: row, start: "top 86%", once: true },
    });
  });

  gsap.from("[data-measure]", {
    y: 18,
    autoAlpha: 0,
    duration: 0.65,
    stagger: 0.12,
    ease: "power3.out",
    scrollTrigger: { trigger: ".measurements", start: "top 86%", once: true },
  });

  const count = document.querySelector("[data-count]");
  if (count) {
    const counter = { value: 0 };
    gsap.to(counter, {
      value: Number(count.dataset.count),
      duration: 1.15,
      ease: "power2.out",
      onUpdate: () => { count.textContent = String(Math.round(counter.value)); },
      scrollTrigger: { trigger: count, start: "top 90%", once: true },
    });
  }

  gsap.to(".opensource__signal", {
    xPercent: -18,
    ease: "none",
    scrollTrigger: { trigger: ".opensource", start: "top bottom", end: "bottom top", scrub: true },
  });
} else {
  setCatState("ready", false);
  document.querySelectorAll(".score__fill").forEach((fill) => {
    const row = fill.closest("[data-score]");
    fill.style.transform = `scaleX(${row?.dataset.score ?? "0"})`;
  });
}
