// The Holt cat's moods, from the original site.
export type CatMood = "ready" | "startled" | "heartbroken" | "determined" | "celebrating" | "adoring" | "thinking";

export const CAT: Record<CatMood, { eyes: [string, string]; mouth: string; ears: [string, string]; tone: "blue" | "green" | "orange" | "amber" }> = {
  ready: { eyes: ["•", "•"], mouth: "ω", ears: ["^", "^"], tone: "blue" },
  startled: { eyes: ["◉", "◉"], mouth: "o", ears: ["^", "^"], tone: "blue" },
  heartbroken: { eyes: ["╥", "╥"], mouth: "_", ears: ["˘", "˘"], tone: "orange" },
  determined: { eyes: ["¬", "¬"], mouth: "_", ears: ["^", "^"], tone: "blue" },
  celebrating: { eyes: ["˘", "˘"], mouth: "ᴗ", ears: ["^", "^"], tone: "green" },
  adoring: { eyes: ["♥", "♥"], mouth: "ᴗ", ears: ["^", "^"], tone: "green" },
  thinking: { eyes: ["･", "･"], mouth: "_", ears: ["^", "^"], tone: "amber" },
};

export const TONE_TEXT = { blue: "text-blue", green: "text-green", orange: "text-orange", amber: "text-amber" } as const;
