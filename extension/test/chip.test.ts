import { chipView, ensureChip, findAnchor, removeChips, statLine, updateChip } from "../src/chip";
import { legacyRepoHeader, report, repoHeader } from "./helpers";

const flask = { owner: "pallets", repo: "flask" };

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("chipView", () => {
  it("shows the verdict headline and one stat", () => {
    const v = chipView({ state: "found", data: report() }, flask);
    expect(v.label).toBe("Holt: Worth your time");
    expect(v.stat).toBe("15 of 100 newcomer PRs merged");
    expect(v.tone).toBe("viable");
  });

  it.each([
    ["not_viable", "Holt: Not worth your time"],
    ["insufficient_evidence", "Holt: Not enough evidence"],
  ] as const)("%s → %s", (verdict, label) => {
    expect(chipView({ state: "found", data: report({ verdict }) }, flask).label).toBe(label);
  });

  it("derives the headline from the verdict, not the free-text field", () => {
    const v = chipView({ state: "found", data: report({ verdict: "not_viable", headline: "Worth your time" }) }, flask);
    expect(v.label).toBe("Holt: Not worth your time");
  });

  it("says 'Check with Holt' when nothing is cached, on errors and on unknown verdicts", () => {
    expect(chipView({ state: "missing" }, flask).label).toBe("Check with Holt");
    expect(chipView({ state: "error" }, flask).label).toBe("Check with Holt");
    const odd = report({ verdict: "maybe" as never });
    expect(chipView({ state: "found", data: odd }, flask).label).toBe("Check with Holt");
  });
});

describe("statLine", () => {
  it("handles singular, zero and missing counts", () => {
    expect(statLine(report({ stats: { outsider_attempts: 1, outsider_merged: 0 } }))).toBe("0 of 1 newcomer PR merged");
    expect(statLine(report({ stats: { outsider_attempts: 0, outsider_merged: 0 } }))).toBeNull();
    expect(statLine(report({ stats: null }))).toBeNull();
    expect(statLine(report({ stats: { outsider_attempts: 3 } }))).toBeNull();
  });
});

describe("ensureChip", () => {
  it("appends to the repo title in the current layout", () => {
    document.body.innerHTML = repoHeader();
    const chip = ensureChip(document, flask, { state: "found", data: report() })!;
    expect(chip.parentElement!.id).toBe("repo-title-component");
    expect(chip.href).toBe("https://holt.aahil-khan.xyz/pallets/flask");
    expect(chip.target).toBe("_blank");
    expect(chip.rel).toContain("noopener");
    expect(chip.textContent).toBe("Holt: Worth your time15 of 100 newcomer PRs merged");
    expect(chip.getAttribute("aria-label")).toBe("Holt: Worth your time. 15 of 100 newcomer PRs merged.");
  });

  it("goes right after the repo name in the legacy layout", () => {
    document.body.innerHTML = legacyRepoHeader();
    const chip = ensureChip(document, flask, { state: "missing" })!;
    expect(chip.previousElementSibling!.getAttribute("itemprop")).toBe("name");
    expect(chip.textContent).toBe("Check with Holt");
    expect(chip.querySelector<HTMLElement>(".holt-chip__stat")!.hidden).toBe(true);
  });

  it("does nothing when the page has no repo title", () => {
    document.body.innerHTML = "<main><h1>Explore</h1></main>";
    expect(findAnchor(document)).toBeNull();
    expect(ensureChip(document, flask, { state: "loading" })).toBeNull();
    expect(document.querySelector(".holt-chip")).toBeNull();
  });

  it("is idempotent", () => {
    document.body.innerHTML = repoHeader();
    const a = ensureChip(document, flask, { state: "loading" });
    const b = ensureChip(document, { owner: "Pallets", repo: "Flask" }, { state: "loading" });
    expect(b).toBe(a);
    expect(document.querySelectorAll(".holt-chip")).toHaveLength(1);
  });

  it("replaces a chip left over from another repo", () => {
    document.body.innerHTML = repoHeader();
    ensureChip(document, flask, { state: "loading" });
    ensureChip(document, { owner: "NixOS", repo: "nixpkgs" }, { state: "loading" });
    const chips = document.querySelectorAll<HTMLElement>(".holt-chip");
    expect(chips).toHaveLength(1);
    expect(chips[0].dataset.holtRepo).toBe("nixos/nixpkgs");
  });

  it("never interprets report text as HTML", () => {
    document.body.innerHTML = repoHeader();
    const chip = ensureChip(document, flask, { state: "loading" })!;
    updateChip(chip, { owner: "pallets", repo: "<img src=x onerror=alert(1)>" }, { state: "missing" });
    expect(chip.querySelector("img")).toBeNull();
  });

  it("updates in place from loading to a verdict", () => {
    document.body.innerHTML = repoHeader();
    const chip = ensureChip(document, flask, { state: "loading" })!;
    expect(chip.dataset.holtState).toBe("loading");
    updateChip(chip, flask, { state: "found", data: report({ verdict: "insufficient_evidence" }) });
    expect(chip.dataset.holtTone).toBe("insufficient_evidence");
    expect(chip.textContent).toContain("Not enough evidence");
  });

  it("removeChips clears every chip", () => {
    document.body.innerHTML = repoHeader();
    ensureChip(document, flask, { state: "loading" });
    removeChips(document);
    expect(document.querySelector(".holt-chip")).toBeNull();
  });
});

describe("the loading skeleton", () => {
  it("keeps the real words, marks the chip busy, and clears it on a verdict", () => {
    document.body.innerHTML = repoHeader();
    const chip = ensureChip(document, flask, { state: "loading" })!;
    expect(chip.dataset.holtState).toBe("loading");
    expect(chip.getAttribute("aria-busy")).toBe("true");
    // The label and stat carry the text that sizes the pill; content.css draws
    // them as blocks, so the chip is as wide and tall as a real one.
    expect(chip.querySelector(".holt-chip__label")!.textContent).toBe("Holt");
    expect(chip.querySelector<HTMLElement>(".holt-chip__stat")!.hidden).toBe(false);
    expect(chip.querySelector(".holt-chip__stat")!.textContent).toBe("checking…");
    expect(chip.getAttribute("aria-label")).toBe("Holt. checking….");

    updateChip(chip, flask, { state: "found", data: report() });
    expect(chip.dataset.holtState).toBe("found");
    expect(chip.hasAttribute("aria-busy")).toBe(false);
    // Same elements, so the CSS transition on them crossfades block → text.
    expect(chip.querySelector(".holt-chip__label")!.textContent).toBe("Holt: Worth your time");
  });

  it("is not busy when the verdict is already known", () => {
    document.body.innerHTML = repoHeader();
    const chip = ensureChip(document, flask, { state: "missing" })!;
    expect(chip.hasAttribute("aria-busy")).toBe(false);
  });
});
