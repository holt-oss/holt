import { CAT, TONE_TEXT, type CatMood } from "@/lib/cat";

export function CatFace({ mood = "ready", className = "", blink = false }: { mood?: CatMood; className?: string; blink?: boolean }) {
  const c = CAT[mood];
  const eye = blink ? { animation: "blink 4.5s infinite" } : undefined;
  return (
    <span className={`cat-face ${TONE_TEXT[c.tone]} ${className}`} aria-hidden="true">
      <span>(=</span>
      <span className="cat-ear">{c.ears[0]}</span>
      <span className="cat-eye" style={eye}>{c.eyes[0]}</span>
      <span className="cat-mouth">{c.mouth}</span>
      <span className="cat-eye" style={eye}>{c.eyes[1]}</span>
      <span className="cat-ear">{c.ears[1]}</span>
      <span>=)</span>
    </span>
  );
}
