import type { Metadata } from "next";
import Link from "next/link";
import { ContactEmail, LegalPage } from "@/components/legal-page";
import { PAYMENT_BRAND } from "@/lib/site";

export const metadata: Metadata = {
  title: "Refund and Cancellation Policy",
  description: "How to cancel a Holt subscription, when a payment can be refunded, and how to ask for one.",
};

export default function RefundsPage() {
  return (
    <LegalPage
      rail="refunds"
      title={<>Refund and Cancellation Policy</>}
      lede="Most of Holt is free, so there's nothing to refund. This policy covers the paid parts: subscriptions and credit packs, billed as Githolt."
    >
      <div className="summary">
        <p><strong>The short version.</strong></p>
        <ul>
          <li>Cancel a subscription anytime, from your account settings or by email. You keep access until the end of the period you paid for.</li>
          <li>No refunds for the unused part of a month you&rsquo;ve started, except where the law requires it or a charge was failed or duplicated.</li>
          <li>Credit packs: full refund within 7 days if you haven&rsquo;t used any credit. Non-refundable once used.</li>
          <li>Approved refunds go back to the original payment method within 5 to 7 business days.</li>
        </ul>
      </div>

      <h2>1. What this covers</h2>
      <p>
        This policy applies to anything you pay Holt for. Payments appear as <strong>{PAYMENT_BRAND}</strong> on your statement.
        Rupee payments are processed by Razorpay; dollar payments are processed by Dodo Payments, which is the merchant of record
        for those purchases. Rules reports, finding and comparing projects, the free monthly AI reports, and bringing your own
        key are free and are not covered here.
      </p>

      <h2>2. Subscriptions</h2>
      <ul>
        <li><strong>Cancel at any time.</strong> Cancel from your account settings, or email <ContactEmail /> from the address on your account and say you want to cancel. Either way we&rsquo;ll confirm the cancellation and the date your access ends. Cancelling stops all future charges.</li>
        <li><strong>You keep what you paid for.</strong> Your access continues until the end of the current billing period. You won&rsquo;t be charged again after that.</li>
        <li><strong>No refunds for a partly used period.</strong> If you cancel part-way through a month or year, we don&rsquo;t refund the remainder. The exceptions are where the law requires a refund, and failed or duplicate charges (see section 4).</li>
        <li><strong>Price changes.</strong> If we raise the price of your plan, we&rsquo;ll tell you before it applies to your next renewal, so you can cancel first.</li>
      </ul>

      <h2>3. Credit packs</h2>
      <ul>
        <li><strong>Refundable within 7 days if unused.</strong> If you bought a pack of report credits by mistake or changed your mind, email us within 7 days of the purchase. As long as none of the credits has been used, we&rsquo;ll refund the full amount.</li>
        <li><strong>Non-refundable once used.</strong> Once any credit from a pack has been spent, the pack can&rsquo;t be refunded, in whole or in part.</li>
        <li>Credits don&rsquo;t have a cash value and can&rsquo;t be transferred to another account.</li>
      </ul>

      <h2>4. Failed and duplicate charges</h2>
      <p>
        If you were charged but didn&rsquo;t receive what you paid for, or were charged twice for the same thing, we&rsquo;ll refund the
        extra charge in full. Send us the payment IDs and we&rsquo;ll sort it out.
      </p>

      <h2>5. How to ask for a refund</h2>
      <ol>
        <li>Email <ContactEmail /> from the email address on your Holt account.</li>
        <li>Include the <strong>payment ID</strong>. It&rsquo;s on the receipt email from Razorpay or Dodo Payments (for Razorpay it starts with <code>pay_</code>).</li>
        <li>Say what you bought and why you&rsquo;re asking for a refund. A line is enough.</li>
      </ol>
      <p>We aim to reply within 3 business days. If we need anything else to check the payment, we&rsquo;ll ask.</p>

      <h2>6. How refunds are paid</h2>
      <ul>
        <li>Approved refunds go to the <strong>original payment method</strong>, in the currency you were charged in.</li>
        <li>We issue the refund through the processor within <strong>5 to 7 business days</strong> of approving it. Your bank or card issuer may take a few more days to show it.</li>
        <li>We refund the amount you paid us. Currency-conversion differences or fees charged by your bank aren&rsquo;t something we can return.</li>
      </ul>

      <h2>7. Disputes and chargebacks</h2>
      <p>
        If something is wrong, please email us first: a refund is faster than a dispute. If you do open a dispute or chargeback,
        it is handled under the rules of the processor that took the payment, Razorpay or Dodo Payments, and their decision is
        followed. We&rsquo;ll provide the payment records they ask for.
      </p>

      <h2>8. Changes to this policy</h2>
      <p>
        The date at the top shows the current version. Changes apply to purchases made after the change. This policy is part of the{" "}
        <Link href="/terms" className="text-link">terms of service</Link>.
      </p>
    </LegalPage>
  );
}
