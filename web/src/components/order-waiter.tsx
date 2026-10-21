"use client";

// On the thank-you page while a payment is still being confirmed: ask every
// few seconds whether the order has settled, then re-render the page. A
// Razorpay order is settled by its webhook; for a Dodo order (`ask`) every
// other question has the server look the payment up at Dodo as well.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { Order } from "@/lib/types";

const EVERY_MS = 2500;
const FOR_MS = 60_000;

async function settled(orderId: string, ask: boolean): Promise<boolean> {
  if (ask) {
    const res = await fetch("/api/orders/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ order: orderId }) });
    const body = (await res.json().catch(() => null)) as { order?: Order } | null;
    return Boolean(body?.order && body.order.status !== "created");
  }
  const res = await fetch("/api/orders", { cache: "no-store" });
  const body = (await res.json().catch(() => null)) as { orders?: Order[] } | null;
  return Boolean(body?.orders?.some((o) => o.id === orderId));
}

export function OrderWaiter({ orderId, by, ask = false }: { orderId: string; by: string; ask?: boolean }) {
  const router = useRouter();
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const t0 = Date.now();
    let stop = false;
    let asked = 0;
    const tick = async () => {
      if (stop) return;
      if (Date.now() - t0 > FOR_MS) {
        setSlow(true);
        return;
      }
      try {
        asked += 1;
        if (await settled(orderId, ask && asked % 2 === 0)) {
          router.refresh();
          return;
        }
      } catch {
        // keep asking
      }
      setTimeout(tick, EVERY_MS);
    };
    const first = setTimeout(tick, EVERY_MS);
    return () => {
      stop = true;
      clearTimeout(first);
    };
  }, [orderId, ask, router]);

  return slow ? (
    <p className="prose-sans mt-4 text-[0.95rem]">
      This is taking longer than usual. You can leave this page: Pro starts as soon as {by} confirms the
      payment. If it doesn&apos;t go through, you won&apos;t be charged.
    </p>
  ) : (
    <p className="mt-4 flex items-center gap-2 text-[0.9rem] text-muted" role="status">
      <span aria-hidden="true" className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber" /> Waiting for {by} to confirm…
    </p>
  );
}
