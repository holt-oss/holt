import Link from "next/link";
import { KeyOrPlan } from "../billing/key-or-plan";

export function UpgradeCard({ repo, signedIn }: { repo: string; signedIn: boolean }) {
  const aiHref = `/${repo}?mode=ai`;
  const href = signedIn ? aiHref : `/signin?callbackUrl=${encodeURIComponent(aiHref)}`;
  return (
    <div className="relative overflow-hidden border border-blue/50 bg-blue/[0.06] p-5 sm:p-6">
      <p className="text-[0.72rem] uppercase tracking-[0.08em] text-blue">AI report</p>
      <h3 className="mt-1 text-[1.15rem] font-semibold tracking-tight">Want it explained like a mentor would?</h3>
      <p className="mt-2 font-sans text-[0.92rem] text-muted">
        An AI reads the same evidence and writes a short, cited explanation: what to try first and what to avoid.
        It can&apos;t change the verdict.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Link href={href} className="btn-primary bg-blue">
          upgrade to AI report <span aria-hidden="true">→</span>
        </Link>
        <span className="text-[0.75rem] text-faint">
          {signedIn ? "uses your free monthly AI reports" : "sign in first; a few AI reports a month are free"}
        </span>
      </div>
      <p className="mb-2 mt-5 text-[0.72rem] uppercase tracking-[0.08em] text-faint">Need more than the free ones?</p>
      <KeyOrPlan />
    </div>
  );
}
