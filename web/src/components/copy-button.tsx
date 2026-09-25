"use client";

import { useState } from "react";

export function CopyButton({ text, label = "copy", className = "" }: { text: string; label?: string; className?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 1600);
  }
  return (
    <button type="button" onClick={copy} className={className}>
      {state === "copied" ? "copied ✓" : state === "failed" ? "press ctrl+c" : label}
      <span className="sr-only" aria-live="polite">{state === "copied" ? "Copied to clipboard" : ""}</span>
    </button>
  );
}
