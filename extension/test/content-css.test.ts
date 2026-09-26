// The stylesheet is plain CSS copied into the build, so these tests read it as
// text: the skeleton chip must use the same shimmer timing as the web app and
// stay static under reduced motion.
import css from "../src/content.css?raw";
import webCss from "../../web/src/app/globals.css?raw";

/** The `@media (...)` block whose query contains `query`, or "" when absent. */
function mediaBlock(source: string, query: string): string {
  const start = source.indexOf(`@media (${query})`);
  if (start < 0) return "";
  let depth = 0;
  for (let i = source.indexOf("{", start); i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}" && --depth === 0) return source.slice(start, i + 1);
  }
  return "";
}

function token(source: string, name: string): string | undefined {
  return source.match(new RegExp(`${name}:\\s*([^;]+);`))?.[1].trim();
}

describe("the skeleton chip stylesheet", () => {
  it("draws the loading label and stat as blocks and reveals the chip after the delay", () => {
    expect(css).toMatch(/a\.holt-chip\[data-holt-state="loading"\] \.holt-chip__label,\s*a\.holt-chip\[data-holt-state="loading"\] \.holt-chip__stat \{[^}]*color: transparent;/);
    expect(css).toMatch(/a\.holt-chip\[data-holt-state="loading"\] \{[^}]*animation: holt-chip-appear [^;]*var\(--holt-sk-delay\) both;/);
    expect(token(css, "--holt-sk-delay")).toBe(token(webCss, "--sk-delay"));
  });

  it("uses the web app's shimmer timing", () => {
    expect(token(css, "--holt-sk-sweep")).toBe("1.8s");
    expect(webCss).toMatch(/animation: sk-sweep 1\.8s var\(--ease-move\) infinite/);
    expect(token(css, "--holt-ease-move")).toBe(token(webCss, "--ease-move"));
    expect(token(css, "--holt-dur-base")).toBe(token(webCss, "--dur-base"));
    expect(token(css, "--holt-dur-fast")).toBe(token(webCss, "--dur-fast"));
    expect(token(css, "--holt-ease-out")).toBe(token(webCss, "--ease-out"));
    // Same keyframe shape: a sweep to 66%, then a rest.
    expect(css).toMatch(/@keyframes holt-sk-sweep \{\s*66%,\s*100% \{/);
    expect(webCss).toMatch(/@keyframes sk-sweep \{\s*66%,\s*100% \{/);
  });

  it("only shimmers when motion is welcome, and swaps at once under reduced motion", () => {
    const shimmer = mediaBlock(css, "prefers-reduced-motion: no-preference");
    expect(shimmer).toContain('a.holt-chip[data-holt-state="loading"]::after');
    expect(shimmer).toContain("animation: holt-sk-sweep");
    // The ::after rule lives only inside that media block.
    expect(css.split('[data-holt-state="loading"]::after')).toHaveLength(2);

    const reduce = mediaBlock(css, "prefers-reduced-motion: reduce");
    expect(reduce).toContain("a.holt-chip,");
    expect(reduce).toContain("animation-duration: 0s;");
    expect(reduce).toContain("transition: none;");
  });
});
