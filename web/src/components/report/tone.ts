import type { Tone } from "@/lib/format";
import type { CatMood } from "@/lib/cat";
import type { Verdict } from "@/lib/types";

export const TONE: Record<Tone | "neutral", { text: string; bg: string; border: string; soft: string }> = {
  good: { text: "text-green", bg: "bg-green", border: "border-green", soft: "bg-green/10" },
  bad: { text: "text-orange", bg: "bg-orange", border: "border-orange", soft: "bg-orange/10" },
  warn: { text: "text-amber", bg: "bg-amber", border: "border-amber", soft: "bg-amber/10" },
  neutral: { text: "text-blue", bg: "bg-blue", border: "border-blue", soft: "bg-blue/10" },
};

export const VERDICT_MOOD: Record<Verdict, CatMood> = {
  viable: "celebrating",
  not_viable: "heartbroken",
  insufficient_evidence: "thinking",
};
