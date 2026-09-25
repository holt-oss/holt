"use client";

// Mock mode only: stands in for Razorpay Checkout so the whole flow can be
// tried and screenshotted without payment keys. Clearly labelled as a test.
import { useEffect, useRef } from "react";
import { formatMoney } from "@/lib/money";
import type { Checkout, RazorpaySuccess } from "@/lib/types";

export type FakeOutcome = { type: "success"; data: RazorpaySuccess } | { type: "failed"; reason: string } | { type: "dismissed" };

export function FakeCheckout({ order, onDone }: { order: Checkout; onDone: (o: FakeOutcome) => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  const id = order.kind === "order" ? { razorpay_order_id: order.order_id } : { razorpay_subscription_id: order.subscription_id };
  const pay = (signature: string) =>
    onDone({ type: "success", data: { razorpay_payment_id: `pay_mock_${Date.now()}`, razorpay_signature: signature, ...id } });

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onDone({ type: "dismissed" });
      }}
      className="m-auto w-[min(420px,calc(100vw-32px))] border border-line-strong bg-panel p-0 text-ink shadow-card backdrop:bg-black/60"
      aria-labelledby="fake-checkout-title"
      data-fake-checkout
    >
      <div className="border-b border-dashed border-amber/60 bg-amber/10 px-5 py-2 text-[0.72rem] text-amber">test checkout · mock mode · no real payment</div>
      <div className="p-5">
        <p id="fake-checkout-title" className="text-[0.72rem] uppercase tracking-[0.08em] text-faint">{order.name}</p>
        <p className="mt-1 text-[1.1rem] font-semibold">{order.description}</p>
        <p className="mt-3 text-[2rem] font-semibold tracking-tight">
          {formatMoney(order.amount, order.currency)}
          {order.kind === "subscription" && <span className="text-[0.9rem] font-normal text-muted"> / month</span>}
        </p>
        <div className="mt-5 grid gap-2">
          <button type="button" className="btn-primary" onClick={() => pay("mock_sig")} data-fake="pay">
            pay (succeeds)
          </button>
          {order.kind === "subscription" && (
            <button type="button" className="btn-ghost" onClick={() => pay("mock_sig_pending")} data-fake="pending">
              pay (webhook arrives late)
            </button>
          )}
          <button type="button" className="btn-ghost text-orange" onClick={() => onDone({ type: "failed", reason: "Your bank declined the payment." })} data-fake="fail">
            payment fails
          </button>
          <button type="button" className="min-h-11 text-[0.82rem] text-muted underline" onClick={() => onDone({ type: "dismissed" })} data-fake="close">
            close without paying
          </button>
        </div>
      </div>
    </dialog>
  );
}
