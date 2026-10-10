"use client";
// The motion setting as three choices. It applies at once and is kept in a
// cookie on this browser (lib/motion.ts).
import { useState } from "react";
import { MOTION_OPTIONS, setMotion, type Motion } from "@/lib/motion";

export function MotionChoice({ initial }: { initial: Motion }) {
  const [value, setValue] = useState(initial);
  return (
    <fieldset>
      <legend className="sr-only">Motion</legend>
      <div className="flex flex-wrap gap-2">
        {MOTION_OPTIONS.map((o) => (
          <label
            key={o.value}
            className={`inline-flex min-h-11 cursor-pointer items-center border px-3 text-[0.87rem] transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-blue ${
              value === o.value ? "picked" : "border-line-strong text-muted hover:text-ink"
            }`}
          >
            <input
              type="radio"
              name="motion"
              value={o.value}
              checked={value === o.value}
              onChange={() => {
                setValue(o.value);
                setMotion(o.value);
              }}
              className="sr-only"
            />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
