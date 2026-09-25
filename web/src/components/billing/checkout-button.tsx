"use client";

// Sign in → POST checkout → Razorpay Checkout → POST verify → success, or
// "activating…" while the webhook lands (poll /api/me for ~30 s).
// Nothing here grants access: the server checks Razorpay's signature.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { shortDate } from "@/lib/format";
import type { ApiError, BillingItem, Checkout, Me, RazorpaySuccess } from "@/lib/types";
import { CatFace } from "../cat-face";
import { FakeCheckout, type FakeOutcome } from "./fake-checkout";

type Phase =
  | { t: "idle" }
  | { t: "starting" }
  | { t: "paying"; order: Checkout }
  | { t: "verifying" }
  | { t: "pending"; waited: number }
  | { t: "slow" }
  | { t: "success"; me: Me }
  | { t: "failed"; message: string }
  | { t: "dismissed" };

const POLL_MS = 2000;
const POLL_FOR_MS = 30_000;

interface RazorpayInstance {
  open(): void;
  on(event: "payment.failed", cb: (r: { error?: { description?: string } }) => void): void;
}
declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => RazorpayInstance;
  }
}

let loader: Promise<void> | null = null;
function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  loader ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => {
      loader = null;
      reject(new Error("load"));
    };
    document.head.appendChild(s);
  });
  return loader;
}

const MESSAGES: Partial<Record<ApiError["code"], string>> = {
  already_subscribed: "You already have a plan that renews. Cancel it in Settings first, or wait for it to end.",
  not_implemented: "Payments aren't switched on yet. Bringing your own key works today, free.",
  invalid_signature: "We couldn't confirm that payment with Razorpay. If you were charged, it will show up in Settings once Razorpay confirms it.",
};

export interface CheckoutButtonProps {
  item: BillingItem;
  currency: string;
  label: string;
  /** What the buyer gets, for the success message ("Student", "10 AI reports"). */
  itemName: string;
  signedIn: boolean;
  mock: boolean;
  disabled?: string;
  autoStart?: boolean;
  prefill?: { name?: string | null; email?: string | null };
  primary?: boolean;
}

export function CheckoutButton(props: CheckoutButtonProps) {
  const { item, currency, label, itemName, signedIn, mock, disabled, autoStart, prefill, primary } = props;
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>({ t: "idle" });
  const started = useRef(false);
  const isPlan = "plan" in item;
  const target = "plan" in item ? item.plan : null;

  const poll = useCallback(async () => {
    const t0 = Date.now();
    while (Date.now() - t0 < POLL_FOR_MS) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      setPhase({ t: "pending", waited: Date.now() - t0 });
      try {
        const res = await fetch("/api/me", { cache: "no-store" });
        if (res.ok) {
          const me: Me = await res.json();
          if (me.plan === target) {
            setPhase({ t: "success", me });
            router.refresh();
            return;
          }
        }
      } catch {
        // keep polling
      }
    }
    setPhase({ t: "slow" });
  }, [router, target]);

  const verify = useCallback(
    async (data: RazorpaySuccess) => {
      setPhase({ t: "verifying" });
      try {
        const res = await fetch("/api/billing/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        });
        const body = await res.json().catch(() => null);
        if (!res.ok) {
          setPhase({ t: "failed", message: MESSAGES[body?.error?.code as ApiError["code"]] ?? body?.error?.message ?? "We couldn't confirm the payment." });
          return;
        }
        const me: Me = body.me;
        if (!isPlan || me.plan === target) {
          setPhase({ t: "success", me });
          router.refresh();
        } else {
          // "authenticated": mandate set, first charge not in yet; the webhook finishes it.
          setPhase({ t: "pending", waited: 0 });
          void poll();
        }
      } catch {
        setPhase({ t: "failed", message: "We lost the connection while confirming. If you were charged, it will show up in Settings shortly." });
      }
    },
    [isPlan, target, router, poll],
  );

  const start = useCallback(async () => {
    setPhase({ t: "starting" });
    let res: Response;
    try {
      res = await fetch("/api/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...item, currency }),
      });
    } catch {
      setPhase({ t: "failed", message: "Couldn't reach Holt. Check your connection and try again." });
      return;
    }
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      setPhase({ t: "failed", message: MESSAGES[body?.error?.code as ApiError["code"]] ?? body?.error?.message ?? "Couldn't start checkout." });
      return;
    }
    const order = body as Checkout;
    if (mock) {
      setPhase({ t: "paying", order });
      return;
    }
    try {
      await loadRazorpay();
    } catch {
      setPhase({ t: "failed", message: "Razorpay didn't load. An ad blocker may be stopping it; try allowing checkout.razorpay.com." });
      return;
    }
    setPhase({ t: "paying", order });
    const rzp = new window.Razorpay!({
      key: order.key_id,
      name: order.name,
      description: order.description,
      currency: order.currency,
      ...(order.kind === "order" ? { order_id: order.order_id, amount: order.amount } : { subscription_id: order.subscription_id }),
      prefill: { name: prefill?.name ?? undefined, email: prefill?.email ?? undefined },
      theme: { color: "#15755a" },
      handler: (r: RazorpaySuccess) => void verify(r),
      modal: { ondismiss: () => setPhase((p) => (p.t === "paying" ? { t: "dismissed" } : p)) },
    });
    rzp.on("payment.failed", (r) => setPhase({ t: "failed", message: r.error?.description || "The payment didn't go through." }));
    rzp.open();
  }, [item, currency, mock, prefill, verify]);

  // After signing in from /pricing?buy=…, pick up where they left off.
  useEffect(() => {
    if (autoStart && signedIn && !disabled && !started.current) {
      started.current = true;
      void start();
    }
  }, [autoStart, signedIn, disabled, start]);

  function onFake(o: FakeOutcome) {
    if (o.type === "success") void verify(o.data);
    else if (o.type === "failed") setPhase({ t: "failed", message: o.reason });
    else setPhase({ t: "dismissed" });
  }

  const cls = primary ? "btn-primary w-full" : "btn-ghost w-full";
  const busy = phase.t === "starting" || phase.t === "verifying" || phase.t === "paying";

  if (!signedIn) {
    const back = `/pricing?buy=${"plan" in item ? item.plan : item.pack}${currency !== "INR" ? `&currency=${currency}` : ""}`;
    return (
      <Link href={`/signin?callbackUrl=${encodeURIComponent(back)}`} className={cls}>
        sign in to {label.toLowerCase()} →
      </Link>
    );
  }

  return (
    <>
      <button type="button" className={cls} disabled={Boolean(disabled) || busy} onClick={() => void start()} title={disabled}>
        {busy ? (phase.t === "verifying" ? "confirming…" : "opening checkout…") : label}
      </button>
      {disabled && <p className="mt-2 font-sans text-[0.78rem] text-faint">{disabled}</p>}
      {phase.t === "dismissed" && (
        <p role="status" className="mt-2 font-sans text-[0.8rem] text-muted">Checkout closed. Nothing was charged.</p>
      )}
      {mock && phase.t === "paying" && <FakeCheckout order={phase.order} onDone={onFake} />}
      {(phase.t === "verifying" || phase.t === "pending" || phase.t === "slow" || phase.t === "success" || phase.t === "failed") && (
        <ResultDialog phase={phase} itemName={itemName} isPlan={isPlan} onClose={() => setPhase({ t: "idle" })} onRetry={() => void start()} />
      )}
    </>
  );
}

function ResultDialog({ phase, itemName, isPlan, onClose, onRetry }: { phase: Phase; itemName: string; isPlan: boolean; onClose: () => void; onRetry: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!ref.current?.open) ref.current?.showModal();
  }, []);
  const closable = phase.t === "success" || phase.t === "failed" || phase.t === "slow";

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        if (closable) onClose();
      }}
      className="m-auto w-[min(460px,calc(100vw-32px))] border border-line-strong bg-panel p-0 text-ink shadow-card backdrop:bg-black/60"
      aria-labelledby="billing-result-title"
      aria-live="polite"
      data-billing-result={phase.t}
    >
      <div className="p-6 sm:p-7">
        {phase.t === "verifying" && (
          <>
            <CatFace mood="determined" blink className="text-[1.6rem]" />
            <h2 id="billing-result-title" className="mt-4 text-[1.3rem] font-semibold tracking-tight">Confirming your payment…</h2>
            <p className="mt-2 font-sans text-muted">Checking with Razorpay. Don&apos;t close this tab.</p>
          </>
        )}
        {phase.t === "pending" && (
          <>
            <CatFace mood="thinking" blink className="text-[1.6rem]" />
            <h2 id="billing-result-title" className="mt-4 text-[1.3rem] font-semibold tracking-tight">Payment received. Activating…</h2>
            <p className="mt-2 font-sans text-muted">
              Razorpay has your payment and is finishing the subscription. This usually takes a few seconds.
            </p>
            <div className="mt-5 h-1.5 bg-panel-2" role="progressbar" aria-label="Activating" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((phase.waited / POLL_FOR_MS) * 100)}>
              <div className="h-full bg-blue transition-[width] duration-700" style={{ width: `${Math.max(6, Math.min(100, (phase.waited / POLL_FOR_MS) * 100))}%` }} />
            </div>
          </>
        )}
        {phase.t === "slow" && (
          <>
            <CatFace mood="thinking" className="text-[1.6rem]" />
            <h2 id="billing-result-title" className="mt-4 text-[1.3rem] font-semibold tracking-tight">Still activating</h2>
            <p className="mt-2 font-sans text-muted">
              Your payment went through, but Razorpay hasn&apos;t confirmed the subscription yet. It will show up in Settings
              within a few minutes. You won&apos;t be charged twice.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/settings" className="btn-primary">go to settings</Link>
              <button type="button" className="btn-ghost" onClick={onClose}>close</button>
            </div>
          </>
        )}
        {phase.t === "success" && (
          <>
            <CatFace mood="celebrating" className="text-[1.6rem]" />
            <h2 id="billing-result-title" className="mt-4 text-[1.4rem] font-semibold tracking-tight text-green">
              {isPlan ? `You're on ${phase.me.plan_name}.` : `${itemName} added.`}
            </h2>
            <p className="mt-2 font-sans text-muted">
              {isPlan
                ? `${phase.me.quota.ai_limit} AI reports this billing period${phase.me.renews_at ? `; renews ${shortDate(phase.me.renews_at)}` : ""}. Cancel anytime; you keep access until the period ends.`
                : `You now have ${phase.me.pack_credits} pack credit${phase.me.pack_credits === 1 ? "" : "s"}. They never expire and are used after your monthly allowance.`}
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/" className="btn-primary">check a repo →</Link>
              <Link href="/settings" className="btn-ghost">see your plan</Link>
              <button type="button" className="min-h-11 px-2 text-[0.82rem] text-muted underline" onClick={onClose}>close</button>
            </div>
          </>
        )}
        {phase.t === "failed" && (
          <>
            <CatFace mood="startled" className="text-[1.6rem]" />
            <h2 id="billing-result-title" className="mt-4 text-[1.3rem] font-semibold tracking-tight text-orange">That didn&apos;t go through</h2>
            <p className="mt-2 font-sans text-muted">{phase.message}</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <button type="button" className="btn-primary" onClick={onRetry}>try again</button>
              <button type="button" className="btn-ghost" onClick={onClose}>close</button>
            </div>
          </>
        )}
      </div>
    </dialog>
  );
}
