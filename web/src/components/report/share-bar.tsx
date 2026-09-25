"use client";

import { useState } from "react";

export function ShareBar({ url, text }: { url: string; text: string }) {
  const [copied, setCopied] = useState(false);
  const enc = encodeURIComponent;

  async function share() {
    if (navigator.share) {
      try {
        await navigator.share({ title: "Holt", text, url });
        return;
      } catch {
        // cancelled: fall through to copy
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {}
  }

  const links = [
    { name: "WhatsApp", href: `https://wa.me/?text=${enc(`${text} ${url}`)}` },
    { name: "X", href: `https://x.com/intent/post?text=${enc(text)}&url=${enc(url)}` },
    { name: "LinkedIn", href: `https://www.linkedin.com/sharing/share-offsite/?url=${enc(url)}` },
  ];

  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" onClick={share} className="btn-ghost">
        <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M16 6l-4-4-4 4M12 2v13" />
        </svg>
        {copied ? "link copied ✓" : "share"}
        <span className="sr-only" aria-live="polite">{copied ? "Link copied" : ""}</span>
      </button>
      {links.map((l) => (
        <a key={l.name} href={l.href} target="_blank" rel="noopener noreferrer" className="btn-ghost px-3 text-muted">
          {l.name}
          <span className="sr-only"> (share in a new tab)</span>
        </a>
      ))}
    </div>
  );
}
