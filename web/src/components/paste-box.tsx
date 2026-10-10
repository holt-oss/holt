"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { track } from "@/lib/analytics";
import { EXAMPLES, EXAMPLES_PATH } from "@/lib/examples";
import { NOT_A_REPO, pasteHref } from "@/lib/gate";
import { parseRepoInput } from "@/lib/repo";

/**
 * Opens a page from a repo box: [opening, open]. `opening` is true from the
 * submit until the next screen shows (the report's loading screen counts), and
 * drops by itself, so the button is never left stuck, the same page included.
 */
export function useOpen(): [boolean, (href: string) => void] {
  const router = useRouter();
  const [opening, start] = useTransition();
  return [opening, (href) => start(() => router.push(href))];
}

// `id` and `label` let a page hold a second box: ids stay unique, and the
// smoke test's getByLabel("GitHub repository or URL") still finds one input.
// A repo opens its report, signed in or not (pasteHref); the "try" row holds
// the example reports.
export function PasteBox({
  autoFocus = false,
  examples = true,
  size = "lg",
  id = "repo-input",
  label = "GitHub repository or URL",
  signedIn = true,
}: {
  autoFocus?: boolean;
  examples?: boolean;
  size?: "lg" | "md";
  id?: string;
  label?: string;
  /** From the server's session. Signed-in pages (/me) can leave it out. */
  signedIn?: boolean;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, open] = useOpen();

  function go(input: string) {
    const ref = parseRepoInput(input);
    if (!ref) {
      setError(NOT_A_REPO);
      return;
    }
    setError("");
    const repo = `${ref.owner}/${ref.repo}`;
    track("paste-submit", { repo, signedIn: signedIn ? "yes" : "no" });
    open(pasteHref(repo));
  }

  return (
    <div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          go(value);
        }}
        className="group relative grid grid-cols-1 border border-line-strong bg-panel transition-colors focus-within:border-blue sm:grid-cols-[1fr_auto]"
      >
        <label htmlFor={id} className="sr-only">{label}</label>
        <input
          id={id}
          name="repo"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            if (error) setError("");
          }}
          onPaste={(e) => {
            const text = e.clipboardData.getData("text");
            if (parseRepoInput(text)) {
              e.preventDefault();
              setValue(text.trim());
              go(text);
            }
          }}
          autoFocus={autoFocus}
          autoComplete="off"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="go"
          placeholder="owner/name or a GitHub URL"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          className={`min-w-0 bg-transparent px-4 text-ink outline-none placeholder:text-faint ${size === "lg" ? "h-16 text-[1rem] sm:text-[1.05rem]" : "h-13 text-[0.95rem]"}`}
        />
        <button
          type="submit"
          disabled={busy}
          className={`btn-primary m-1.5 sm:m-2 ${size === "lg" ? "sm:min-h-12" : ""}`}
        >
          {busy ? "opening…" : "Check this repo"}
        </button>
      </form>
      {error && (
        <p id={`${id}-error`} role="alert" className="mt-2 font-sans text-[0.89rem] text-orange">
          {error}
        </p>
      )}
      {examples && (
        <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-[0.82rem] text-faint">
          <span>try</span>
          {/* One of each verdict; /examples has the rest. */}
          {EXAMPLES.filter((e, i) => EXAMPLES.findIndex((x) => x.verdict === e.verdict) === i).map(({ repo }) => (
            <button
              key={repo}
              type="button"
              onClick={() => go(repo)}
              className="min-h-11 border-b border-dashed border-line-strong text-muted transition-colors hover:border-blue hover:text-ink"
            >
              {repo}
            </button>
          ))}
          {!signedIn && (
            <Link href={EXAMPLES_PATH} className="inline-flex min-h-11 items-center text-muted hover:text-ink">
              all examples →
            </Link>
          )}
        </p>
      )}
    </div>
  );
}
