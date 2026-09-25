import type { Metadata } from "next";
import Link from "next/link";
import { CheckoutButton } from "@/components/billing/checkout-button";
import { ErrorPanel } from "@/components/error-panel";
import { me as getMe, MOCK, plans as getPlans } from "@/lib/api";
import { formatMoney, perInterval, priceIn } from "@/lib/money";
import { shortDate } from "@/lib/format";
import { currentUser } from "@/lib/session";
import type { Me, Pack, Plan, Plans, Price } from "@/lib/types";

export const metadata: Metadata = {
  title: "Pricing",
  description: "Rules reports are free forever, a few AI reports a month are free too, and bringing your own key is always free and unlimited.",
};

const Check = ({ children }: { children: React.ReactNode }) => (
  <li className="flex gap-2">
    <span aria-hidden="true" className="text-green">✓</span>
    <span>{children}</span>
  </li>
);

function taxLine(p: Plans, prices: Price[]): string {
  return (
    prices.find((x) => x.tax_note)?.tax_note ??
    p.tax_note ??
    "Prices in ₹ INR (or $ USD where shown). Razorpay shows the final amount, including any taxes, before you pay."
  );
}

export default async function PricingPage({ searchParams }: PageProps<"/pricing">) {
  const sp = await searchParams;
  const user = await currentUser();
  const [catalog, account] = await Promise.all([getPlans(), user ? getMe(user.id) : Promise.resolve(null)]);
  const me: Me | null = account?.ok ? account.data : null;

  if (!catalog.ok) {
    return (
      <div className="wrap py-14">
        <ErrorPanel error={catalog.error} retryHref="/pricing" />
      </div>
    );
  }
  const p = catalog.data;
  const hasUsd = p.plans.some((x) => priceIn(x.prices, "USD")) || p.packs.some((x) => priceIn(x.prices, "USD"));
  const currency = hasUsd && sp.currency === "USD" ? "USD" : "INR";
  const buy = typeof sp.buy === "string" ? sp.buy : undefined;
  const free = p.plans.find((x) => x.id === "free");
  const paid = p.plans.filter((x) => x.prices.length > 0);
  const payments = p.provider !== null;
  const renewing = Boolean(me?.renews_at);
  const allPrices = [...paid.flatMap((x) => x.prices), ...p.packs.flatMap((x) => x.prices)];

  /** The price to show: the chosen currency if sold in it, else INR. */
  const shown = (prices: Price[]) => priceIn(prices, currency) ?? priceIn(prices, "INR") ?? prices[0];

  const planButton = (plan: Plan, price: Price) => {
    const current = me?.plan === plan.id;
    const disabled = !payments
      ? "Payments aren't switched on yet."
      : current
        ? me?.ends_at
          ? `Ends ${shortDate(me.ends_at)}. You can subscribe again after that.`
          : "This is your plan."
        : renewing
          ? "Cancel your current plan in Settings first."
          : undefined;
    return (
      <CheckoutButton
        item={{ plan: plan.id }}
        currency={price.currency}
        label={current ? "current plan" : `get ${plan.name}`}
        itemName={plan.name}
        signedIn={Boolean(user)}
        mock={MOCK}
        disabled={disabled}
        autoStart={buy === plan.id}
        prefill={{ name: user?.name, email: user?.email }}
        primary={plan.id === "student"}
      />
    );
  };

  const packButton = (pack: Pack, price: Price) => (
    <CheckoutButton
      item={{ pack: pack.id }}
      currency={price.currency}
      label={`buy ${pack.reports} reports`}
      itemName={pack.name}
      signedIn={Boolean(user)}
      mock={MOCK}
      disabled={payments ? undefined : "Payments aren't switched on yet."}
      autoStart={buy === pack.id}
      prefill={{ name: user?.name, email: user?.email }}
    />
  );

  return (
    <div className="wrap py-10 sm:py-14">
      <p className="rail mb-4 flex gap-2"><strong className="m-0">pricing</strong><span>free where it matters</span></p>
      <h1 className="display max-w-3xl text-[clamp(2rem,6vw,3.4rem)]">
        Finding a project is free. <span className="text-green">It always will be.</span>
      </h1>
      <p className="prose-sans mt-5 max-w-2xl text-[1.05rem]">
        Rules reports cost nothing, forever. You only pay if you want AI-written reports without using your own API key.
        What you pay never changes the verdict.
      </p>

      <div className="mt-8 flex flex-wrap items-center gap-4">
        {hasUsd && (
          <nav aria-label="Currency" className="flex border border-line-strong text-[0.8rem]">
            {(["INR", "USD"] as const).map((c) => (
              <Link
                key={c}
                href={c === "INR" ? "/pricing" : "/pricing?currency=USD"}
                aria-current={currency === c ? "true" : undefined}
                className={`px-3 py-2 ${currency === c ? "bg-ink text-bg" : "text-muted hover:text-ink"}`}
                scroll={false}
              >
                {c === "INR" ? "₹ INR" : "$ USD"}
              </Link>
            ))}
          </nav>
        )}
        {me && (
          <p className="text-[0.8rem] text-muted">
            You&apos;re on <strong className="text-ink">{me.plan_name}</strong>
            {me.renews_at ? ` · renews ${shortDate(me.renews_at)}` : me.ends_at ? ` · ends ${shortDate(me.ends_at)}` : ""}
            {me.pack_credits > 0 ? ` · ${me.pack_credits} pack credits` : ""}
          </p>
        )}
      </div>

      {!payments && (
        <p role="status" className="mt-6 border border-amber/50 bg-amber/10 px-4 py-3 font-sans text-[0.9rem] text-muted">
          Paid plans aren&apos;t switched on yet. Bringing your own key works today and is free.
        </p>
      )}

      <ul className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {free && (
          <li className="flex flex-col border border-line-strong bg-panel p-6">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[0.78rem] uppercase tracking-[0.08em] text-faint">{free.name}</p>
              {me?.plan === "free" && <span className="chip min-h-0 py-0.5 text-green">your plan</span>}
            </div>
            <p className="mt-3 text-[2.2rem] font-semibold leading-none tracking-tight">{formatMoney(0, currency)}</p>
            <p className="mt-1 text-[0.8rem] text-muted">forever</p>
            <ul className="mt-5 flex-1 space-y-2 font-sans text-[0.92rem]">
              <Check>Unlimited rules reports</Check>
              <Check>{free.ai_reports_per_month} AI reports a month</Check>
              <Check>Find, compare, badges, share images</Check>
            </ul>
            <Link href={me?.plan === "free" ? "/" : "/signin"} className="btn-ghost mt-6 w-full">
              {me ? "check a repo" : "sign in, free"}
            </Link>
          </li>
        )}
        <li className="flex flex-col border border-green bg-panel p-6">
          <p className="text-[0.78rem] uppercase tracking-[0.08em] text-faint">Bring your own key</p>
          <p className="mt-3 text-[2.2rem] font-semibold leading-none tracking-tight">{formatMoney(p.byok.price, currency)}</p>
          <p className="mt-1 text-[0.8rem] text-green">free · {p.byok.unlimited ? "unlimited" : "limited"}</p>
          <ul className="mt-5 flex-1 space-y-2 font-sans text-[0.92rem]">
            <Check>Unlimited AI reports</Check>
            <Check>OpenRouter, Anthropic, OpenAI or Gemini</Check>
            <Check>You pay your provider directly, usually a few cents a report</Check>
          </ul>
          <Link href={user ? "/settings#byok" : "/signin?callbackUrl=%2Fsettings"} className="btn-ghost mt-6 w-full">
            {me?.byok?.set ? "key saved · manage" : "add a key"}
          </Link>
        </li>
        {paid.map((plan) => {
          const price = shown(plan.prices)!;
          const other = currency === "USD" && price.currency !== "USD";
          return (
            <li key={plan.id} className={`relative flex flex-col border bg-panel p-6 ${plan.id === "student" ? "border-blue shadow-card" : "border-line-strong"}`}>
              {plan.id === "student" && (
                <span className="absolute -top-3 left-6 bg-blue px-2 py-0.5 text-[0.7rem] font-semibold text-on-accent">made for students</span>
              )}
              <p className="text-[0.78rem] uppercase tracking-[0.08em] text-faint">{plan.name}</p>
              <p className="mt-3 text-[2.2rem] font-semibold leading-none tracking-tight">
                {formatMoney(price.amount, price.currency)}
                <span className="ml-1 text-[0.85rem] font-normal tracking-normal text-muted">{perInterval(price)}</span>
              </p>
              <p className="mt-1 text-[0.8rem] text-muted">{other ? "only sold in ₹ INR" : "renews monthly · cancel anytime"}</p>
              <ul className="mt-5 flex-1 space-y-2 font-sans text-[0.92rem]">
                <Check>{plan.ai_reports_per_month} AI reports a month, no key needed</Check>
                {plan.features.map((f) => <Check key={f}>{f}</Check>)}
                <Check>Everything in Free</Check>
              </ul>
              <div className="mt-6">{planButton(plan, price)}</div>
            </li>
          );
        })}
      </ul>

      {p.packs.length > 0 && (
        <section aria-labelledby="packs" className="mt-12">
          <h2 id="packs" className="text-[1.2rem] font-semibold tracking-tight">Just need a few?</h2>
          <p className="mt-1 font-sans text-muted">One-time packs. Credits never expire and are used after your monthly allowance.</p>
          <ul className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {p.packs.map((pack) => {
              const price = shown(pack.prices)!;
              return (
                <li key={pack.id} className="flex flex-col border border-line-strong bg-panel p-5">
                  <p className="font-semibold">{pack.name}</p>
                  <p className="mt-2 text-[1.8rem] font-semibold leading-none tracking-tight">
                    {formatMoney(price.amount, price.currency)} <span className="text-[0.8rem] font-normal tracking-normal text-muted">one-time</span>
                  </p>
                  {currency === "USD" && price.currency !== "USD" && <p className="mt-1 text-[0.78rem] text-muted">only sold in ₹ INR</p>}
                  <div className="mt-4">{packButton(pack, price)}</div>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section id="compare" aria-labelledby="compare-title" className="mt-16 scroll-mt-24">
        <h2 id="compare-title" className="text-[1.2rem] font-semibold tracking-tight">Your own key or a plan?</h2>
        <p className="mt-1 max-w-2xl font-sans text-muted">
          Both get you the same AI reports. Your own key is free and unlimited; a plan means you don&apos;t have to set one up.
        </p>
        <div className="mt-5 overflow-x-auto border border-line-strong">
          <table className="w-full min-w-[560px] border-collapse text-left text-[0.85rem]">
            <thead className="bg-panel-2 text-[0.72rem] uppercase tracking-[0.06em] text-faint">
              <tr>
                <th scope="col" className="p-3 font-medium"><span className="sr-only">Feature</span></th>
                <th scope="col" className="p-3 font-medium text-green">Your own key</th>
                {free && <th scope="col" className="p-3 font-medium">{free.name}</th>}
                {paid.map((x) => <th key={x.id} scope="col" className="p-3 font-medium">{x.name}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-line bg-panel font-sans">
              <tr>
                <th scope="row" className="p-3 font-normal text-muted">Price</th>
                <td className="p-3 text-green">free</td>
                {free && <td className="p-3">free</td>}
                {paid.map((x) => {
                  const pr = shown(x.prices)!;
                  return <td key={x.id} className="p-3">{formatMoney(pr.amount, pr.currency)} {perInterval(pr)}</td>;
                })}
              </tr>
              <tr>
                <th scope="row" className="p-3 font-normal text-muted">AI reports</th>
                <td className="p-3 text-green">unlimited</td>
                {free && <td className="p-3">{free.ai_reports_per_month} / month</td>}
                {paid.map((x) => <td key={x.id} className="p-3">{x.ai_reports_per_month} / month</td>)}
              </tr>
              <tr>
                <th scope="row" className="p-3 font-normal text-muted">Needs an API key</th>
                <td className="p-3">yes, yours</td>
                {free && <td className="p-3">no</td>}
                {paid.map((x) => <td key={x.id} className="p-3">no</td>)}
              </tr>
              <tr>
                <th scope="row" className="p-3 font-normal text-muted">Priority queue</th>
                <td className="p-3">no</td>
                {free && <td className="p-3">{free.priority ? "yes" : "no"}</td>}
                {paid.map((x) => <td key={x.id} className="p-3">{x.priority ? "yes" : "no"}</td>)}
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <ul className="mt-10 max-w-3xl space-y-1.5 font-sans text-[0.85rem] text-faint">
        <li>{taxLine(p, allPrices)}</li>
        <li>Plans renew monthly. Cancel anytime; you keep access until the period ends.</li>
        <li>Payments are handled by Razorpay. Card, UPI and bank details go straight to Razorpay and never reach Holt&apos;s servers.</li>
        <li>Pack credits never expire.</li>
      </ul>
    </div>
  );
}
