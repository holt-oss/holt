import type { Metadata } from "next";
import Link from "next/link";
import { ContactEmail, LegalPage } from "@/components/legal-page";
import { CONTACT_CITY, CONTACT_EMAIL, GITHUB_REPO_URL, PAYMENT_BRAND } from "@/lib/site";

export const metadata: Metadata = {
  title: "Contact",
  description: "How to reach the person who runs Holt: refunds, account deletion, privacy questions, problems with a report, and security issues.",
};

const REASONS = [
  { what: "Refund or cancellation", how: "You can cancel from your account settings, or by email. For a refund, include the payment ID from your Razorpay or Dodo Payments receipt and the email on your account.", href: "/refunds", label: "refund policy" },
  { what: "Delete your account", how: "Email from the address on your account. We remove the account, your history and any stored AI key.", href: "/privacy", label: "privacy policy" },
  { what: "A question about your data", how: "Ask what we hold, or ask for a correction. We'll answer in plain English." },
  { what: "A report looks wrong", how: "Send the repository link. Every finding links to its source, so tell us which one doesn't hold up." },
  { what: "A security problem", how: "Please email before posting publicly. We'll confirm receipt and fix it as fast as we can." },
];

export default function ContactPage() {
  return (
    <LegalPage
      rail="contact"
      title={<>Contact</>}
      lede="Holt is run by one person. Email is the fastest way to reach them, and every message gets a reply."
    >
      <h2>Email</h2>
      <p className="text-[1.15rem]">
        <ContactEmail />
      </p>
      <p>We aim to reply within 3 business days, usually sooner.</p>

      <h2>What to write about</h2>
      <ul>
        {REASONS.map((r) => (
          <li key={r.what}>
            <strong>{r.what}.</strong> {r.how}
            {r.href && (
              <>
                {" "}See the <Link href={r.href} className="text-link">{r.label}</Link>.
              </>
            )}
          </li>
        ))}
      </ul>

      <h2>Bugs and ideas</h2>
      <p>
        Holt is open source. Bugs and feature ideas are best as an issue at{" "}
        <a href={`${GITHUB_REPO_URL}/issues`} className="text-link">github.com/holt-oss/holt/issues</a>, where others can see and add to them.
      </p>

      <h2>Who you&rsquo;re writing to</h2>
      <ul>
        <li><strong>Business name:</strong> Holt. Payments appear as <strong>{PAYMENT_BRAND}</strong> on statements and receipts.</li>
        <li><strong>Run by:</strong> an individual in {CONTACT_CITY}, India, as a sole proprietorship.</li>
        <li><strong>Email:</strong> {CONTACT_EMAIL}</li>
        <li><strong>Website:</strong> githolt.com</li>
      </ul>
      <p>
        Holt is not affiliated with GitHub. Questions about a GitHub account or repository itself should go to GitHub or the project&rsquo;s maintainers.
      </p>
    </LegalPage>
  );
}
