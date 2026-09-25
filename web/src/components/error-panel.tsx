import Link from "next/link";
import type { ApiError } from "@/lib/types";
import { CatFace } from "./cat-face";

const HEAD: Record<string, string> = {
  not_found: "We couldn't find that repository",
  invalid_repo: "That doesn't look like a repository",
  invalid_request: "That request didn't make sense to us",
  not_implemented: "Coming soon",
  rate_limited: "Too many checks at once",
  quota_exceeded: "You've used this month's free AI reports",
  needs_key: "AI reports need a plan or your own key",
  unauthorized: "Sign in first",
  upstream: "GitHub or the AI model didn't answer",
  internal: "Something broke on our side",
};

export function ErrorPanel({ error, repo, onRetry, retryHref }: { error: ApiError; repo?: string; onRetry?: () => void; retryHref?: string }) {
  const account = error.code === "needs_key" || error.code === "quota_exceeded";
  return (
    <div role="alert" className="border border-line-strong bg-panel p-6 shadow-soft sm:p-8">
      <CatFace mood={account ? "determined" : "startled"} className="text-[1.6rem]" />
      <h2 className="mt-4 text-[1.4rem] font-semibold tracking-tight">{HEAD[error.code] ?? "Something went wrong"}</h2>
      <p className="mt-2 max-w-xl font-sans text-muted">
        {error.message}
        {error.code === "rate_limited" && error.retry_after ? ` Try again in about ${Math.ceil(error.retry_after / 60)} minute${error.retry_after > 60 ? "s" : ""}.` : ""}
      </p>
      <div className="mt-5 flex flex-wrap gap-3">
        {account && (
          <>
            <Link href="/settings" className="btn-primary">add your own key (free)</Link>
            <Link href="/pricing" className="btn-ghost">see plans</Link>
            {repo && <Link href={`/${repo}`} className="btn-ghost">back to the free report</Link>}
          </>
        )}
        {error.code === "unauthorized" && (
          <Link href={`/signin${repo ? `?callbackUrl=${encodeURIComponent(`/${repo}?mode=ai`)}` : ""}`} className="btn-primary">sign in</Link>
        )}
        {(error.code === "upstream" || error.code === "internal" || error.code === "rate_limited") &&
          (onRetry ? (
            <button type="button" onClick={onRetry} className="btn-primary">try again</button>
          ) : (
            <a href={retryHref ?? (repo ? `/${repo}` : "/")} className="btn-primary">try again</a>
          ))}
        {(error.code === "not_found" || error.code === "invalid_repo") && (
          <Link href="/" className="btn-primary">check a different repo</Link>
        )}
      </div>
    </div>
  );
}
