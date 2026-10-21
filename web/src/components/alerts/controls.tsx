"use client";
// The alert settings' two controls: an on/off switch, and when to email (the
// Display tab's choice buttons).
import { EMAIL_MODES, type EmailMode } from "@/lib/alerts";

export function Switch({ on, onChange, label, disabled = false }: { on: boolean; onChange: (on: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)} className="grid min-h-11 place-items-center px-1 disabled:opacity-60">
      <span className={`relative block h-6 w-11 rounded-full border transition-colors ${on ? "border-sel bg-sel-bg" : "border-line-strong bg-panel-2"}`}>
        <span className={`absolute top-0.5 size-[18px] rounded-full transition-[left,background-color] ${on ? "left-[22px] bg-sel" : "left-0.5 bg-faint"}`} />
      </span>
    </button>
  );
}

export function EmailChoice({ value, onChange, name }: { value: EmailMode; onChange: (mode: EmailMode) => void; name: string }) {
  return (
    <fieldset>
      <legend className="sr-only">When to email</legend>
      <div className="flex flex-col items-start gap-2">
        {EMAIL_MODES.map((o) => (
          <label
            key={o.value}
            className={`inline-flex min-h-11 cursor-pointer items-center border px-3 text-[0.87rem] transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-blue ${
              value === o.value ? "picked" : "border-line-strong text-muted hover:text-ink"
            }`}
          >
            <input type="radio" name={name} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} className="sr-only" />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
