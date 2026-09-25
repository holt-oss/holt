"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { parseRepoInput } from "@/lib/repo";

const EXAMPLES = ["pallets/flask", "NixOS/nixpkgs", "pytorch/pytorch"];

export function PasteBox({ autoFocus = false, examples = true, size = "lg" }: { autoFocus?: boolean; examples?: boolean; size?: "lg" | "md" }) {
  const router = useRouter();
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function go(input: string) {
    const ref = parseRepoInput(input);
    if (!ref) {
      setError("Paste a GitHub repository, like pallets/flask or https://github.com/pallets/flask");
      return;
    }
    setError("");
    setBusy(true);
    router.push(`/${ref.owner}/${ref.repo}`);
  }

  return (
    <div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          go(value);
        }}
        className="group relative grid grid-cols-1 border border-line-strong bg-panel shadow-card transition-colors focus-within:border-blue sm:grid-cols-[auto_1fr_auto]"
      >
        <span aria-hidden="true" className="absolute inset-y-0 left-0 w-0.5 origin-top scale-y-0 bg-amber transition-transform group-focus-within:scale-y-100" />
        <label htmlFor="repo-input" className="sr-only">GitHub repository or URL</label>
        <span aria-hidden="true" className="hidden items-center pl-5 text-amber sm:flex">$</span>
        <input
          id="repo-input"
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
          placeholder="paste a repo: owner/name or github.com URL"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? "repo-error" : undefined}
          className={`min-w-0 bg-transparent px-4 text-ink outline-none placeholder:text-faint sm:px-3 ${size === "lg" ? "h-16 text-[1rem] sm:text-[1.05rem]" : "h-13 text-[0.95rem]"}`}
        />
        <button
          type="submit"
          disabled={busy}
          className={`btn-primary m-1.5 sm:m-2 ${size === "lg" ? "sm:min-h-12" : ""}`}
        >
          {busy ? "opening…" : "check this repo"} <span aria-hidden="true">→</span>
        </button>
      </form>
      {error && (
        <p id="repo-error" role="alert" className="mt-2 font-sans text-[0.85rem] text-orange">
          {error}
        </p>
      )}
      {examples && (
        <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-[0.75rem] text-faint">
          <span>try</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => go(ex)}
              className="min-h-8 border-b border-dashed border-line-strong text-muted transition-colors hover:border-blue hover:text-ink"
            >
              {ex}
            </button>
          ))}
        </p>
      )}
    </div>
  );
}
