import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { checkOrder, me, orders } from "@/lib/api";
import { shortDate } from "@/lib/format";
import { formatPrice, processor, returnedOrder } from "@/lib/payments";
import { currentUser } from "@/lib/session";
import { PLAN_SETTINGS } from "@/lib/settings";
import { CONTACT_EMAIL } from "@/lib/site";
import { OrderWaiter } from "@/components/order-waiter";
import { PageHead } from "@/components/page-head";
import { PageTransition } from "@/components/motion/page-transition";

export const metadata: Metadata = { title: "Thank you", robots: { index: false } };

// After a pass checkout: paid (thank you), still being confirmed (wait
// here), declined, or held for a person to check. Only the buyer's own orders.
// Dodo Payments sends the buyer straight here from its checkout, so the
// server is asked to check the order with Dodo first; nothing Dodo adds to
// the address is read.
export default async function ThanksPage({ searchParams }: PageProps<"/pricing/thanks">) {
  const sp = await searchParams;
  const id = returnedOrder(sp.order);
  const user = await currentUser();
  if (!user) redirect(`/signin?callbackUrl=${encodeURIComponent(id ? `/pricing/thanks?order=${id}` : PLAN_SETTINGS)}`);
  if (!id) redirect(`${PLAN_SETTINGS}#purchases`);

  const checked = await checkOrder(user.id, id);
  const [list, account] = await Promise.all([orders(user.id), me(user.id)]);
  const order = (list.ok ? list.data.orders.find((o) => o.id === id) : undefined) ?? (checked.ok ? checked.data.order : undefined);
  const by = processor(order);
  const until = account.ok && account.data.plan === "pro" ? account.data.plan_expires_at : null;

  let heading: React.ReactNode;
  let body: React.ReactNode;
  if (order?.status === "paid") {
    heading = <>Thank you. <span className="text-green">{order.days ? "Pro is on." : "Paid."}</span></>;
    body = (
      <p className="prose-sans text-[1.05rem]">
        You paid {formatPrice(order.amount, order.currency)} for {order.name}. {by} emails you a receipt.
        {until && <> Pro runs until <strong className="text-ink">{shortDate(until)}</strong>.</>}
      </p>
    );
  } else if (order?.status === "failed") {
    heading = <>That payment didn&apos;t go through.</>;
    body = <p className="prose-sans text-[1.05rem]">You haven&apos;t been charged. Try again, or use another payment method.</p>;
  } else if (order?.status === "held") {
    heading = <>We&apos;re checking your payment.</>;
    body = (
      <p className="prose-sans text-[1.05rem]">
        {by} reported a payment that didn&apos;t match the order, so Pro hasn&apos;t started yet. We check these by hand. Not sorted
        within a day? Write to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`} className="text-link">{CONTACT_EMAIL}</a> and mention order <code className="text-[0.85em]">{id.slice(0, 12)}</code>.
      </p>
    );
  } else {
    heading = <>Almost there.</>;
    body = (
      <>
        <p className="prose-sans text-[1.05rem]">Confirming your payment. This usually takes a few seconds.</p>
        <OrderWaiter orderId={id} by={by} ask={order?.provider === "dodo"} />
      </>
    );
  }

  return (
    <PageTransition>
      <>
        <PageHead narrow>
          <p className="rail mb-4 flex gap-2"><strong className="m-0">pro</strong><span>your purchase</span></p>
          <h1 className="display text-[clamp(2rem,6vw,3rem)]">{heading}</h1>
        </PageHead>
        <div className="wrap max-w-3xl pb-14 pt-6 sm:pb-16">
          <section className="border border-line-strong bg-panel p-5 shadow-soft sm:p-8">{body}</section>
          <div className="mt-6 flex flex-wrap gap-3">
            {order?.status === "failed" ? (
              <Link href="/pricing#passes" className="btn-primary">try again →</Link>
            ) : (
              <Link href="/" className="btn-primary">check a repo →</Link>
            )}
            <Link href={`${PLAN_SETTINGS}#purchases`} className="btn-ghost">your purchases</Link>
          </div>
        </div>
      </>
    </PageTransition>
  );
}
