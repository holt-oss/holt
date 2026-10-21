"use client";

// The pricing page's currency: rupees (paid through Razorpay) or dollars
// (through Dodo Payments). The page is the same for every signed-out visitor,
// so a shared cache can keep it (lib/edge-cache.ts); which currency this
// visitor sees first is settled here, in the browser: the address
// (`?currency=usd`), else what they picked last time, else their country as
// Cloudflare sees it (₹ in India, $ elsewhere). Until then prices take up
// their space and show nothing, so nobody is shown the wrong one.
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { BuyPass } from "@/components/buy-pass";
import { asCurrency, defaultCurrency, formatPrice, perMonth, priceIn, type Currency } from "@/lib/payments";
import { PAYMENT_BRAND } from "@/lib/site";
import type { Pass } from "@/lib/types";

const STORE = "holt-currency";
const SIGN: Record<Currency, string> = { INR: "₹", USD: "$" };

interface Chosen {
  /** null while it is being worked out. */
  currency: Currency | null;
  onSale: Currency[];
  /** True once the visitor has used the switch on this page. */
  switched: boolean;
  choose: (c: Currency) => void;
}

const Ctx = createContext<Chosen>({ currency: "USD", onSale: [], switched: false, choose: () => {} });

async function settle(onSale: Currency[]): Promise<Currency> {
  try {
    const last = asCurrency(window.localStorage.getItem(STORE));
    if (last && onSale.includes(last)) return last;
  } catch {
    // no storage: ask
  }
  try {
    const res = await fetch("/api/billing/country", { cache: "no-store" });
    const body = (await res.json()) as { country?: string | null };
    return defaultCurrency(body.country, onSale);
  } catch {
    return defaultCurrency(null, onSale);
  }
}

export function CurrencyProvider({ onSale, asked, children }: { onSale: Currency[]; asked: Currency | null; children: React.ReactNode }) {
  // One currency on sale (or none: the Free plan's $0) needs no working out.
  const known = asked && onSale.includes(asked) ? asked : onSale.length < 2 ? (onSale[0] ?? "USD") : null;
  const [picked, setPicked] = useState<Currency | null>(known);
  const [switched, setSwitched] = useState(false);

  useEffect(() => {
    if (known) return;
    let stop = false;
    void settle(onSale).then((c) => {
      if (!stop) setPicked((now) => now ?? c);
    });
    return () => {
      stop = true;
    };
  }, [known, onSale]);

  const choose = useCallback((c: Currency) => {
    setPicked(c);
    setSwitched(true);
    try {
      window.localStorage.setItem(STORE, c);
    } catch {
      // not remembered, that's all
    }
  }, []);

  // The address wins until the visitor uses the switch.
  const currency = switched ? picked : (known ?? picked);
  const value = useMemo(() => ({ currency, onSale, switched, choose }), [currency, onSale, switched, choose]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** An amount that is the same number in every currency (the Free plan's 0). */
export function Money({ amount }: { amount: number }) {
  const { currency, onSale } = useContext(Ctx);
  if (!currency) return <span className="invisible" aria-hidden="true">{formatPrice(amount, onSale[0] ?? "USD")}</span>;
  return <>{formatPrice(amount, currency)}</>;
}

function Switch() {
  const { currency, onSale, choose } = useContext(Ctx);
  if (onSale.length < 2) return null;
  return (
    <div role="group" aria-label="Currency" className="inline-flex border border-line-strong font-sans text-[0.85rem]">
      {onSale.map((c) => (
        <button
          key={c}
          type="button"
          aria-pressed={c === currency}
          onClick={() => choose(c)}
          className={`min-h-9 border px-3 transition-colors ${c === currency ? "picked" : "border-transparent text-muted hover:text-ink"}`}
        >
          {SIGN[c]} {c}
        </button>
      ))}
    </div>
  );
}

export interface PassSectionProps {
  passes: Pass[];
  signedIn: boolean;
  prefill?: { name?: string | null; email?: string | null };
  /** A pass to start buying straight away (back from signing in). */
  buy: string | null;
}

export function PassSection({ passes, signedIn, prefill, buy }: PassSectionProps) {
  const { currency, onSale, switched } = useContext(Ctx);
  const shown = currency ?? onSale[0] ?? "INR";
  const sold = passes.flatMap((p) => {
    const amount = priceIn(p, shown);
    return amount === null ? [] : [{ ...p, amount }];
  });
  const featured = sold.find((p) => p.days === 90)?.id ?? sold[0]?.id;
  return (
    <section id="passes" aria-labelledby="passes-h" className="mt-10 scroll-mt-24">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="passes-h" className="text-[1.2rem] font-semibold tracking-tight">Pro comes as a pass</h2>
        <Switch />
      </div>
      <p className="mt-2 max-w-2xl font-sans text-[0.95rem] text-muted">
        A pass gives you Pro for a set time. You pay once, and every pass is the same Pro.
      </p>
      <div className={currency ? undefined : "invisible"} aria-hidden={currency ? undefined : true} inert={!currency}>
        <ul className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {sold.map((p) => {
            const top = p.id === featured;
            return (
              <li key={p.id} className={`relative flex flex-col border bg-panel p-6 ${top ? "border-ink shadow-card" : "border-line-strong shadow-soft"}`}>
                {top && <span className="absolute -top-3 left-6 bg-ink px-2 py-0.5 text-[0.78rem] font-semibold text-on-accent">recommended</span>}
                <p className="text-[0.85rem] uppercase tracking-[0.08em] text-faint">{p.name}</p>
                <p className="mt-3 text-[2rem] font-semibold leading-none tracking-tight">{formatPrice(p.amount, shown)}</p>
                <p className="mt-2 min-h-[1.4rem] font-sans text-[0.9rem] text-muted">{perMonth(p.amount, p.days, shown)}</p>
                <BuyPass
                  key={shown}
                  pass={p.id}
                  currency={shown}
                  label={`get Pro for ${p.name} →`}
                  signedIn={signedIn}
                  prefill={prefill}
                  autoStart={Boolean(currency) && !switched && buy === p.id}
                  primary={top}
                />
              </li>
            );
          })}
        </ul>
        <p className="mt-4 max-w-2xl font-sans text-[0.89rem] text-muted">
          A pass doesn&apos;t renew. When it ends, your account goes back to Free.{" "}
          {shown === "USD" ? (
            <>Paid in USD through Dodo Payments, the merchant of record. Tax may be added at checkout.</>
          ) : (
            <>Paid in INR through Razorpay (UPI, cards, netbanking), billed as <span className="text-ink">{PAYMENT_BRAND}</span>.</>
          )}{" "}
          See the <Link href="/refunds" className="text-link">refund policy</Link>.
        </p>
      </div>
    </section>
  );
}
