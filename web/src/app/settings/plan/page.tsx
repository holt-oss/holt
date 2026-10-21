import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { ComingSoon } from "@/components/coming-soon";
import { entitlements, mergePlansAvailable, orders, passes } from "@/lib/api";
import { shortDate } from "@/lib/format";
import { formatPrice, STATUS_LABEL } from "@/lib/payments";
import { currentUser } from "@/lib/session";
import { PLAN_SETTINGS } from "@/lib/settings";
import { Block, SectionHead } from "@/components/settings/section-head";

export const metadata: Metadata = { title: "Plan · Settings", robots: { index: false } };

export default async function PlanSettings() {
  const user = await currentUser();
  if (!user) redirect(`/signin?callbackUrl=${PLAN_SETTINGS}`);
  const [covered, bought, sale, mergePlans] = await Promise.all([entitlements(user.id), orders(user.id), passes(), mergePlansAvailable()]);
  const e = covered.ok ? covered.data : null;
  const purchases = bought.ok ? bought.data.orders : [];
  const onSale = sale.ok && sale.data.on_sale;
  const pro = e?.plan === "pro";
  // The server's count: the free ones, or this month's on Pro (API.md, Account).
  const left = e?.features.find((f) => f.feature === "merge_plan")?.left ?? null;

  return (
    <section aria-labelledby="plan-h">
      <SectionHead id="plan" />

      {!covered.ok && <p role="alert" className="mb-6 border border-orange/50 px-4 py-3 font-sans text-[0.9rem] text-orange">{covered.error.message}</p>}

      {e && (
        <div className="grid gap-px border border-line bg-line sm:grid-cols-2">
          <div className="bg-panel p-5">
            <p className="text-[0.87rem] text-faint">Your plan</p>
            <p className="mt-1 text-[1.3rem] font-semibold leading-tight">{pro ? "Pro" : "Free"}</p>
            {pro ? (
              e.plan_expires_at && <p className="mt-1 text-[0.87rem] text-muted">until {shortDate(e.plan_expires_at)}</p>
            ) : (
              <p className="mt-1 text-[0.87rem]"><Link href="/pricing" className="text-link">see Pro →</Link></p>
            )}
          </div>
          {left != null && (
            <div className="bg-panel p-5">
              <p className="text-[0.87rem] text-faint">{!mergePlans ? "Merge plans" : pro ? "Merge plans left this month" : "Merge plans left"}</p>
              {mergePlans ? <p className="mt-1 text-[1.3rem] font-semibold leading-tight tabular-nums">{left}</p> : <p className="mt-2"><ComingSoon /></p>}
            </div>
          )}
        </div>
      )}

      {(purchases.length > 0 || onSale) && (
        <Block id="purchases" title="Purchases" className="mt-8">
          {purchases.length === 0 ? (
            <p className="prose-sans text-[0.95rem]">
              Nothing bought yet. <Link href="/pricing#passes" className="text-link">See Pro passes</Link>.
            </p>
          ) : (
            <ul className="divide-y divide-line border-b border-line">
              {purchases.map((o) => (
                <li key={o.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-3 text-[0.9rem]">
                  <span className="min-w-0">
                    <span className="font-semibold">{o.name}</span>
                    <span className="text-muted"> · {formatPrice(o.amount, o.currency)} · {shortDate(o.paid_at ?? o.created_at)}</span>
                  </span>
                  <span className={o.status === "paid" ? "text-ink" : o.status === "held" ? "text-amber" : "text-muted"}>
                    {STATUS_LABEL[o.status]}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {onSale && purchases.length > 0 && (
            <p className="mt-4 text-[0.89rem]"><Link href="/pricing#passes" className="text-link">add another pass →</Link></p>
          )}
        </Block>
      )}
    </section>
  );
}
