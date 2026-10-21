"use client";

// One pass's buy button: start an order on the server, then take the payment.
// In rupees: in Razorpay Checkout, handing what it returns back to the server
// before the thank-you page. In dollars: on Dodo Payments' own checkout page,
// which sends the buyer back to the thank-you page. Nothing here starts Pro:
// the server checks with the processor first. With payments off the server
// refuses the order and the page never renders this button.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Currency } from "@/lib/payments";
import type { ApiError, Checkout, OrderConfirmed, RazorpaySuccess } from "@/lib/types";

type Phase =
  | { t: "idle" }
  | { t: "starting" }
  | { t: "paying" }
  | { t: "confirming" }
  | { t: "failed"; message: string }
  | { t: "dismissed" };

interface RazorpayInstance {
  open(): void;
  on(event: "payment.failed", cb: (r: { error?: { description?: string } }) => void): void;
}
declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => RazorpayInstance;
  }
}

const SCRIPT = "https://checkout.razorpay.com/v1/checkout.js";
let loader: Promise<void> | null = null;
export function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  loader ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SCRIPT;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      loader = null;
      s.remove();
      reject(new Error("load"));
    };
    document.head.appendChild(s);
  });
  return loader;
}

const MESSAGES: Partial<Record<ApiError["code"], string>> = {
  payments_off: "Passes aren't on sale right now. Everything free in Holt keeps working.",
  payment_unconfirmed:
    "We couldn't confirm that payment with Razorpay. If money left your account, Pro will start in a few minutes, or it will be refunded.",
};

export async function post<T>(url: string, body: unknown): Promise<{ ok: true; data: T } | { ok: false; code?: string; message: string }> {
  try {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => null);
    if (res.ok) return { ok: true, data: data as T };
    const e = (data as { error?: ApiError } | null)?.error;
    return { ok: false, code: e?.code, message: (e && MESSAGES[e.code]) || e?.message || "That didn't work. Try again in a minute." };
  } catch {
    return { ok: false, message: "Couldn't reach Holt. Check your connection and try again." };
  }
}

export interface BuyPassProps {
  pass: string;
  /** INR pays in Razorpay Checkout on this page; USD goes to Dodo Payments' checkout. */
  currency: Currency;
  label: string;
  signedIn: boolean;
  prefill?: { name?: string | null; email?: string | null };
  /** Start straight away (back from signing in with `?buy=`). */
  autoStart?: boolean;
  primary?: boolean;
}

export function BuyPass({ pass, currency, label, signedIn, prefill, autoStart, primary }: BuyPassProps) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>({ t: "idle" });
  const started = useRef(false);

  const confirm = useCallback(
    async (orderId: string, paid: RazorpaySuccess) => {
      setPhase({ t: "confirming" });
      const r = await post<OrderConfirmed>("/api/orders/confirm", paid);
      // Unless the signature was refused, a failure here (Razorpay slow, a
      // dropped connection) may still be finished by Razorpay's webhook: the
      // thank-you page waits for it.
      if (!r.ok && r.code === "payment_unconfirmed") {
        setPhase({ t: "failed", message: r.message });
        return;
      }
      router.push(`/pricing/thanks?order=${orderId}`);
    },
    [router],
  );

  const start = useCallback(async () => {
    setPhase({ t: "starting" });
    const r = await post<Checkout>("/api/orders", { pass, currency });
    if (!r.ok) {
      setPhase({ t: "failed", message: r.message });
      return;
    }
    const order = r.data;
    if (order.provider === "dodo") {
      if (!order.checkout_url?.startsWith("https://")) {
        setPhase({ t: "failed", message: "That didn't work. Try again in a minute." });
        return;
      }
      window.location.assign(order.checkout_url);
      return;
    }
    try {
      await loadRazorpay();
    } catch {
      setPhase({ t: "failed", message: "Razorpay's payment window didn't load. If you use an ad blocker, allow checkout.razorpay.com and try again." });
      return;
    }
    setPhase({ t: "paying" });
    const rzp = new window.Razorpay!({
      key: order.key_id,
      order_id: order.provider_order_id,
      amount: order.amount,
      currency: order.currency,
      name: order.name,
      description: order.description,
      prefill: { name: prefill?.name ?? undefined, email: prefill?.email ?? undefined },
      notes: { holt_order: order.order_id },
      theme: { color: "#15755a" },
      handler: (paid: RazorpaySuccess) => void confirm(order.order_id, paid),
      modal: { ondismiss: () => setPhase((p) => (p.t === "paying" ? { t: "dismissed" } : p)) },
    });
    // Checkout shows the failure itself and lets them retry; this is for after it closes.
    rzp.on("payment.failed", (e) => setPhase({ t: "failed", message: e.error?.description || "The payment didn't go through. You haven't been charged." }));
    rzp.open();
  }, [pass, currency, prefill, confirm]);

  // Back from Dodo's page without paying: the browser may show this page as
  // it was left, still "opening checkout…".
  useEffect(() => {
    const back = (e: PageTransitionEvent) => {
      if (e.persisted) setPhase((p) => (p.t === "starting" ? { t: "idle" } : p));
    };
    window.addEventListener("pageshow", back);
    return () => window.removeEventListener("pageshow", back);
  }, []);

  useEffect(() => {
    if (autoStart && signedIn && !started.current) {
      started.current = true;
      void start();
    }
  }, [autoStart, signedIn, start]);

  const cls = `${primary ? "btn-primary" : "btn-ghost"} mt-6 w-full`;
  if (!signedIn) {
    return (
      <Link href={`/signin?callbackUrl=${encodeURIComponent(`/pricing?buy=${pass}&currency=${currency.toLowerCase()}`)}`} className={cls}>
        sign in to buy →
      </Link>
    );
  }
  const busy = phase.t === "starting" || phase.t === "paying" || phase.t === "confirming";
  return (
    <div>
      <button type="button" className={cls} onClick={() => void start()} disabled={busy} aria-busy={busy}>
        {phase.t === "starting" ? "opening checkout…" : phase.t === "paying" ? "paying in Razorpay…" : phase.t === "confirming" ? "confirming your payment…" : label}
      </button>
      <p aria-live="polite" className="mt-3 min-h-[1.25rem] font-sans text-[0.89rem]">
        {phase.t === "failed" && <span role="alert" className="text-orange">{phase.message}</span>}
        {phase.t === "dismissed" && <span className="text-muted">Checkout closed. You haven&apos;t been charged.</span>}
      </p>
    </div>
  );
}
