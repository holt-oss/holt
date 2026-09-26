import type { Metadata } from "next";
import Link from "next/link";
import { ContactEmail, LegalPage } from "@/components/legal-page";
import { CONTACT_CITY, FREE_AI_QUOTA, GITHUB_REPO_URL, PAYMENT_BRAND } from "@/lib/site";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "The rules for using Holt at githolt.com: what the service does, accounts, paid plans, and what we do and don't promise.",
};

export default function TermsPage() {
  return (
    <LegalPage
      rail="terms"
      title={<>Terms of Service</>}
      lede="These terms cover the Holt website and service at githolt.com. Using it means you agree to them. We've written them in plain English; if anything is unclear, ask."
    >
      <h2>1. Who we are</h2>
      <p>
        Holt is run by an individual based in {CONTACT_CITY}, India, as a sole proprietorship. It is not a registered company.
        &ldquo;Holt&rdquo;, &ldquo;we&rdquo; and &ldquo;us&rdquo; in these terms mean that person. On card statements and payment receipts the
        service appears as <strong>{PAYMENT_BRAND}</strong>.
      </p>
      <p>
        You can reach us at <ContactEmail />. Details are on the <Link href="/contact" className="text-link">contact page</Link>.
      </p>

      <h2>2. What Holt does</h2>
      <p>
        Holt reads the recent, public pull-request history of a GitHub repository and tells you whether outside contributors get
        replies and get their work merged. The verdict is computed by a fixed set of written rules from findings that were checked
        against the source. An AI model may add a written explanation of the evidence, but it never chooses the verdict.
      </p>
      <ul>
        <li>Holt only reads public GitHub data through GitHub&rsquo;s API. It never posts, comments, opens pull requests, or contacts anyone on your behalf.</li>
        <li>A verdict is a guide, not a promise. Maintainers change, projects change, and a rule can be wrong about a particular repository. Every finding links to the GitHub page it came from so you can check it yourself.</li>
        <li>Holt is not affiliated with, endorsed by, or connected to GitHub, Inc. or any repository it reports on.</li>
      </ul>

      <h2>3. Your account</h2>
      <p>
        You can use most of Holt without an account. Signing in with GitHub or Google gives you a monthly allowance of AI reports,
        a report history, and a place to store your own model key.
      </p>
      <ul>
        <li>You must be at least 13 years old to use Holt, and at least 18 (or have a parent or guardian&rsquo;s permission) to buy anything.</li>
        <li>You are responsible for what happens under your account. Keep your sign-in secure and tell us if you think someone else is using it.</li>
        <li>One person, one account. Don&rsquo;t create accounts to get around limits.</li>
      </ul>

      <h2>4. Fair use</h2>
      <p>Please don&rsquo;t:</p>
      <ul>
        <li>Send automated traffic, scrape the site, or work around rate limits. If you want reports in bulk, the open-source CLI runs the same engine on your own machine with your own GitHub token.</li>
        <li>Use Holt to harass, target, or pressure maintainers or contributors. Reports are about how a project handles outside work, not about people.</li>
        <li>Resell access to Holt, or present Holt&rsquo;s output as your own service without saying where it came from.</li>
        <li>Try to break, probe, or overload the service. If you find a security problem, please email us instead.</li>
      </ul>
      <p>We may slow down, limit, or suspend accounts and IP addresses that do these things.</p>

      <h2>5. Your own model key</h2>
      <p>
        You can add your own OpenRouter, OpenAI, Anthropic or Gemini API key so that AI reports run on your account with that
        provider. If you do:
      </p>
      <ul>
        <li>The key is yours, and your agreement with that provider governs its use and any charges. You pay the provider directly; Holt adds nothing on top.</li>
        <li>We store the key encrypted and use it only to request AI reports that you ask for. We never show it back, not even to you. You can delete it at any time from your settings.</li>
        <li>Keep the key scoped and budgeted at your provider. We can&rsquo;t refund charges a provider bills you.</li>
      </ul>

      <h2>6. Free and paid features</h2>
      <p>
        Rules reports, finding and comparing projects, badges and share images are free, and we intend to keep them free.
        Signed-in users also get {FREE_AI_QUOTA} AI reports a month on our key at no charge. Some features are paid, or will be:
        a subscription for more AI reports, or a pack of report credits.
      </p>
      <ul>
        <li>The price, currency and what you get are shown before you pay. Prices may include tax where the law requires it.</li>
        <li>Payments in Indian rupees are processed by <strong>Razorpay</strong>. Payments in US dollars are processed by <strong>Dodo Payments</strong>, which acts as the merchant of record for those purchases: Dodo Payments is the seller on your receipt and its terms also apply to the transaction.</li>
        <li>We never see or store your card, UPI or bank details. The payment processor handles them.</li>
        <li>Subscriptions renew automatically at the end of each period until you cancel. You can cancel at any time and keep access until the end of the period you paid for.</li>
        <li>Cancellations and refunds follow our <Link href="/refunds" className="text-link">Refund and Cancellation Policy</Link>, which is part of these terms.</li>
        <li>We may change prices or what a plan includes. Changes apply from your next renewal, and we&rsquo;ll tell you before they do.</li>
      </ul>

      <h2>7. Reports, badges and the code</h2>
      <ul>
        <li>Reports are generated from public data and are shown publicly at githolt.com. You may share, quote and link to them, including the badge for your own README. Please don&rsquo;t remove the link back to the evidence when you quote a finding.</li>
        <li>The Holt source code is open source under the Apache-2.0 licence at <a href={GITHUB_REPO_URL} className="text-link">github.com/holt-oss/holt</a>. That licence covers the code. These terms cover the hosted service at githolt.com.</li>
        <li>The Holt name and the cat mark are ours. You can use them to say that a report came from Holt; please don&rsquo;t use them to suggest we endorse you or your project.</li>
      </ul>

      <h2>8. No warranty</h2>
      <p>
        Holt is provided &ldquo;as is&rdquo; and &ldquo;as available&rdquo;. We work to keep it accurate and online, but we don&rsquo;t promise
        that it will be error-free, uninterrupted, or right about any particular repository. GitHub&rsquo;s data, the AI providers we use,
        and our hosting are outside our control and may be unavailable or change.
      </p>

      <h2>9. Limits on liability</h2>
      <p>
        To the extent the law allows, we are not liable for indirect or consequential losses, such as time spent on a project
        because of a Holt verdict, or costs your AI provider bills you. Our total liability to you for anything arising from Holt is
        limited to the amount you paid us in the twelve months before the claim, or ₹1,000 if you paid nothing. Nothing in these terms
        removes rights that Indian consumer law gives you and that cannot be excluded.
      </p>

      <h2>10. Ending things</h2>
      <ul>
        <li>You can stop using Holt at any time. To delete your account and its data, email us; see the <Link href="/privacy" className="text-link">privacy policy</Link>.</li>
        <li>We may suspend or close accounts that break these terms, and may stop offering the service or any feature. If we close a paid feature, we&rsquo;ll refund the unused part of what you paid for it.</li>
      </ul>

      <h2>11. Changes to these terms</h2>
      <p>
        We may update these terms. The date at the top always shows the current version. If a change is significant, we&rsquo;ll say so on
        the site or by email before it takes effect. Continuing to use Holt after that means you accept the change.
      </p>

      <h2>12. Governing law</h2>
      <p>
        These terms are governed by the laws of India. Any dispute will be handled by the courts at {CONTACT_CITY}, India. If you have a
        problem, please email us first: most things can be sorted out quickly without any of that.
      </p>

      <h2>13. Contact</h2>
      <p>
        Email <ContactEmail />. Everything else you need is on the <Link href="/contact" className="text-link">contact page</Link>.
      </p>
    </LegalPage>
  );
}
