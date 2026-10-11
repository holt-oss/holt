import type { Metadata } from "next";
import Link from "next/link";
import { ComingSoon } from "@/components/coming-soon";
import { mergePlansAvailable, passes } from "@/lib/api";
import { EXAMPLE_PATH } from "@/lib/example-report";
import { formatPrice, passToBuy, perMonth } from "@/lib/payments";
import { currentUser } from "@/lib/session";
import { BuyPass } from "@/components/buy-pass";
import { PageHead } from "@/components/page-head";
import { PageTransition } from "@/components/motion/page-transition";
import { FREE, proItems, type PlanItem } from "./copy";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Checking a repo on Holt is free: unlimited reports, starter issues, Find and Compare. Pro watches your PRs, repos and issues and tells you when to act. One payment, no renewal.",
  alternates: { canonical: "/pricing" },
};

/** A plan's lines: what you get, then what it does for you. */
/** The merge plan lines, in Free and in Pro: marked "coming soon" while none can be made. */
const MERGE_PLAN_ITEMS = new Set(["plans", "merge_plan"]);

const Items = ({ items, mergePlans }: { items: PlanItem[]; mergePlans: boolean }) => (
  <ul className="mt-5 flex-1 space-y-3.5 font-sans text-[0.92rem]">
    {items.map((i) => (
      <li key={i.id} className="flex gap-2.5">
        <span aria-hidden="true" className="text-ink">✓</span>
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-medium text-ink">
            {i.title}
            {!mergePlans && MERGE_PLAN_ITEMS.has(i.id) && <ComingSoon small />}
          </p>
          {i.line && <p className="mt-0.5 leading-relaxed text-muted">{i.line}</p>}
        </div>
      </li>
    ))}
  </ul>
);

export default async function PricingPage({ searchParams }: PageProps<"/pricing">) {
  // Passes appear only while the server has them on sale (payments switched
  // on, a price set); until then Pro shows as coming, with no price.
  const [sale, user, sp, mergePlans] = await Promise.all([passes(), currentUser(), searchParams, mergePlansAvailable()]);
  const onSale = sale.ok && sale.data.on_sale ? sale.data.passes : [];
  const selling = onSale.length > 0;
  const pro = proItems(selling && sale.ok ? sale.data.features : []);
  const buy = passToBuy(sp.buy, onSale);
  const featured = onSale.find((p) => p.days === 90)?.id ?? onSale[0]?.id;
  return (
    <PageTransition>
      <>
      <PageHead>
        <p className="rail mb-4 flex gap-2"><strong className="m-0">pricing</strong></p>
        <h1 className="display max-w-3xl text-[clamp(1.9rem,4.5vw,3rem)]">
          Finding a project is free. <span className="text-blue">Pro keeps watch for you.</span>
        </h1>
        <p className="prose-sans mt-5 max-w-2xl text-[0.98rem]">
          Holt checks whether a repo merges outsiders&apos; pull requests before you write one. Pro watches your PRs, repos and
          issues afterwards, and tells you when to act.
        </p>
      </PageHead>

      <div className="wrap py-8 sm:py-10">
        <ul className="grid gap-4 md:grid-cols-2">
          <li className="relative flex flex-col border border-blue bg-panel p-6 shadow-card">
            <p className="text-[0.85rem] uppercase tracking-[0.08em] text-faint">Free</p>
            <p className="mt-3 text-[2rem] font-semibold leading-none tracking-tight">
              {formatPrice(0, onSale[0]?.currency ?? "USD")}{" "}
              <span className="text-[0.89rem] font-normal tracking-normal text-muted">with a free account</span>
            </p>
            <p className="mt-3 font-sans text-muted">Everything you need to pick a project.</p>
            <Items items={FREE} mergePlans={mergePlans} />
            <Link href="/" className="btn-primary mt-6 w-full">check a repo →</Link>
          </li>

          <li className={`flex flex-col p-6 ${selling ? "border border-ink bg-panel shadow-card" : "border border-dashed border-line-strong bg-panel/60"}`}>
            <div className="flex items-center justify-between gap-3">
              <p className="text-[0.85rem] uppercase tracking-[0.08em] text-faint">Pro</p>
              {!selling && <span className="chip border-amber/60 text-amber">coming soon</span>}
            </div>
            <p className="mt-3 text-[1.3rem] font-semibold leading-tight tracking-tight">Holt watches for you.</p>
            <p className="mt-3 font-sans text-muted">Everything in Free. Alerts reach you on the bell in Holt and by email.</p>
            <Items items={pro} mergePlans={mergePlans} />
            {selling ? (
              <a href="#passes" className="btn-ghost mt-6 w-full">choose a pass →</a>
            ) : (
              <p className="mt-6 font-sans text-[0.89rem] text-muted">Pro will come as a pass: one payment for 1, 3 or 12 months.</p>
            )}
          </li>
        </ul>

        {selling && (
          <section id="passes" aria-labelledby="passes-h" className="mt-10 scroll-mt-24">
            <h2 id="passes-h" className="text-[1.2rem] font-semibold tracking-tight">Pro comes as a pass</h2>
            <p className="mt-2 max-w-2xl font-sans text-[0.95rem] text-muted">
              A pass gives you Pro for a set time. You pay once, and every pass is the same Pro.
            </p>
            <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {onSale.map((p) => {
                const monthly = perMonth(p.amount, p.days, p.currency);
                const top = p.id === featured;
                return (
                  <li key={p.id} className={`relative flex flex-col border bg-panel p-6 ${top ? "border-ink shadow-card" : "border-line-strong shadow-soft"}`}>
                    {top && <span className="absolute -top-3 left-6 bg-ink px-2 py-0.5 text-[0.78rem] font-semibold text-on-accent">recommended</span>}
                    <p className="text-[0.85rem] uppercase tracking-[0.08em] text-faint">{p.name}</p>
                    <p className="mt-3 text-[2rem] font-semibold leading-none tracking-tight">{formatPrice(p.amount, p.currency)}</p>
                    <p className="mt-2 min-h-[1.4rem] font-sans text-[0.9rem] text-muted">{monthly}</p>
                    <BuyPass
                      pass={p.id}
                      label={`get Pro for ${p.name} →`}
                      signedIn={Boolean(user)}
                      prefill={{ name: user?.name, email: user?.email }}
                      autoStart={buy === p.id}
                      primary={top}
                    />
                  </li>
                );
              })}
            </ul>
            <p className="mt-4 max-w-2xl font-sans text-[0.89rem] text-muted">
              A pass doesn&apos;t renew. When it ends, your account goes back to Free. Paid in INR through Razorpay (UPI, cards,
              netbanking), billed as <span className="text-ink">Githolt</span>. See the{" "}
              <Link href="/refunds" className="text-link">refund policy</Link>.
            </p>
          </section>
        )}

        <p className="mt-10 border-t border-line pt-8">
          <Link href={EXAMPLE_PATH} className="bracket-link">[ see a merge plan → ]</Link>
        </p>
      </div>
      </>
    </PageTransition>
  );
}
