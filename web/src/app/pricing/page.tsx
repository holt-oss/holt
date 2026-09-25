import type { Metadata } from "next";
import Link from "next/link";
import { FREE_AI_QUOTA } from "@/lib/site";

export const metadata: Metadata = {
  title: "Pricing",
  description: "Rules reports are free forever. A few AI reports a month are free too, and bringing your own key is always free.",
};

const PLANS = [
  {
    name: "Free",
    price: "$0",
    tag: "forever",
    body: "Everything you need to pick a project.",
    items: ["Unlimited rules reports", "Starter issues and evidence", "Find, compare, badges and share images"],
    cta: { href: "/", label: "check a repo" },
    accent: "border-line-strong",
  },
  {
    name: "Free AI",
    price: "$0",
    tag: `${FREE_AI_QUOTA} AI reports / month`,
    body: "Sign in and get plain-English explanations on us.",
    items: [`${FREE_AI_QUOTA} AI reports every month`, "Cited, mentor-style explanation", "Your report history"],
    cta: { href: "/signin", label: "sign in" },
    accent: "border-blue",
    featured: true,
  },
  {
    name: "Bring your own key",
    price: "$0",
    tag: "always free",
    body: "Use your OpenRouter, Anthropic, OpenAI or Gemini key.",
    items: ["Unlimited AI reports", "Pick your model", "Pay your provider directly, usually under $0.05 a report"],
    cta: { href: "/settings", label: "add a key" },
    accent: "border-green",
  },
];

const SOON = [
  { name: "Student Pro", body: "More AI reports without managing a key." },
  { name: "Clubs & classrooms", body: "Shared quota for a college club or a course." },
];

export default function PricingPage() {
  return (
    <div className="wrap py-10 sm:py-14">
      <p className="rail mb-4 flex gap-2"><strong className="m-0">pricing</strong><span>free where it matters</span></p>
      <h1 className="display max-w-3xl text-[clamp(2rem,6vw,3.4rem)]">
        Finding a project is free. <span className="text-green">It always will be.</span>
      </h1>
      <p className="prose-sans mt-5 max-w-2xl text-[1.05rem]">
        The verdict never depends on what you pay. AI only adds a written explanation on top of the same rules.
      </p>

      <ul className="mt-12 grid gap-4 lg:grid-cols-3">
        {PLANS.map((p) => (
          <li key={p.name} className={`relative flex flex-col border bg-panel p-6 ${p.accent} ${p.featured ? "shadow-card" : ""}`}>
            {p.featured && <span className="absolute -top-3 left-6 bg-blue px-2 py-0.5 text-[0.7rem] font-semibold text-on-accent">most students start here</span>}
            <p className="text-[0.78rem] uppercase tracking-[0.08em] text-faint">{p.name}</p>
            <p className="mt-3 text-[2.4rem] font-semibold leading-none tracking-tight">
              {p.price} <span className="text-[0.85rem] font-normal tracking-normal text-muted">{p.tag}</span>
            </p>
            <p className="mt-3 font-sans text-muted">{p.body}</p>
            <ul className="mt-5 flex-1 space-y-2 font-sans text-[0.92rem]">
              {p.items.map((i) => (
                <li key={i} className="flex gap-2"><span aria-hidden="true" className="text-green">✓</span>{i}</li>
              ))}
            </ul>
            <Link href={p.cta.href} className="btn-ghost mt-6 w-full">{p.cta.label} →</Link>
          </li>
        ))}
      </ul>

      <h2 className="mt-16 text-[1.2rem] font-semibold tracking-tight">Paid plans</h2>
      <ul className="mt-4 grid gap-4 sm:grid-cols-2">
        {SOON.map((s) => (
          <li key={s.name} className="border border-dashed border-line-strong p-5">
            <div className="flex items-center justify-between gap-3">
              <p className="font-semibold">{s.name}</p>
              <span className="chip border-amber/60 text-amber">coming soon</span>
            </div>
            <p className="mt-2 font-sans text-[0.92rem] text-muted">{s.body}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
