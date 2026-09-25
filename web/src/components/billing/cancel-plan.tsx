"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

export function CancelPlan({ planName, until }: { planName: string; until: string }) {
  const router = useRouter();
  const ref = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function cancel() {
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/billing/cancel", { method: "POST" });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.error?.message ?? "Couldn't cancel. Try again.");
      ref.current?.close();
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="btn-ghost text-orange" onClick={() => ref.current?.showModal()}>
        cancel plan
      </button>
      <dialog
        ref={ref}
        className="m-auto w-[min(440px,calc(100vw-32px))] border border-line-strong bg-panel p-0 text-ink shadow-card backdrop:bg-black/60"
        aria-labelledby="cancel-title"
        data-cancel-dialog
      >
        <div className="p-6">
          <h2 id="cancel-title" className="text-[1.25rem] font-semibold tracking-tight">Cancel your {planName} plan?</h2>
          <p className="mt-2 font-sans text-muted">
            You won&apos;t be charged again. You keep {planName} until <strong className="text-ink">{until}</strong>, then
            move to the free plan. Your own API key and any pack credits keep working.
          </p>
          {error && <p role="alert" className="mt-3 font-sans text-[0.88rem] text-orange">{error}</p>}
          <div className="mt-6 flex flex-wrap gap-3">
            <button type="button" className="btn-primary bg-orange" disabled={busy} onClick={() => void cancel()}>
              {busy ? "cancelling…" : "yes, cancel"}
            </button>
            <button type="button" className="btn-ghost" onClick={() => ref.current?.close()}>
              keep my plan
            </button>
          </div>
        </div>
      </dialog>
    </>
  );
}
