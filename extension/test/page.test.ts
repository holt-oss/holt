import { createPageController, type LookupFn } from "../src/page";
import { report, repoHeader } from "./helpers";

function fakeLookup(answers: Record<string, unknown>) {
  const calls: string[] = [];
  const fn = ((kind, r) => {
    const key = `${kind} ${r.owner}/${r.repo}`.toLowerCase();
    calls.push(key);
    return Promise.resolve(answers[key] ?? { state: "missing" });
  }) as LookupFn;
  return { fn, calls };
}

beforeEach(() => {
  document.body.innerHTML = "";
});

describe("page controller", () => {
  it("shows loading, then the verdict", async () => {
    document.body.innerHTML = repoHeader();
    const { fn } = fakeLookup({ "report pallets/flask": { state: "found", data: report() } });
    const page = createPageController(document, fn);
    const done = page.sync("/pallets/flask");
    expect(document.querySelector<HTMLElement>(".holt-chip")!.dataset.holtState).toBe("loading");
    await done;
    expect(document.querySelector(".holt-chip")!.textContent).toContain("Holt: Worth your time");
  });

  it("follows client-side navigation to another repo and away from repos", async () => {
    document.body.innerHTML = repoHeader();
    const { fn } = fakeLookup({ "report pallets/flask": { state: "found", data: report() } });
    const page = createPageController(document, fn);
    await page.sync("/pallets/flask");

    // GitHub swaps the header when navigating to another repo.
    document.body.innerHTML = repoHeader("NixOS", "nixpkgs");
    await page.sync("/NixOS/nixpkgs");
    const chips = document.querySelectorAll<HTMLAnchorElement>(".holt-chip");
    expect(chips).toHaveLength(1);
    expect(chips[0].textContent).toBe("Check with Holt");
    expect(chips[0].href).toBe("https://holt.aahil-khan.xyz/NixOS/nixpkgs");

    await page.sync("/settings/profile");
    expect(document.querySelector(".holt-chip")).toBeNull();
  });

  it("looks each repo up once, and restores the chip if GitHub re-renders the header", async () => {
    document.body.innerHTML = repoHeader();
    const { fn, calls } = fakeLookup({ "report pallets/flask": { state: "found", data: report() } });
    const page = createPageController(document, fn);
    await page.sync("/pallets/flask");
    document.body.innerHTML = repoHeader(); // re-render drops our chip
    await page.sync("/pallets/flask/pulls");
    await page.sync("/Pallets/Flask");
    expect(calls).toEqual(["report pallets/flask"]);
    expect(document.querySelector(".holt-chip")!.textContent).toContain("Worth your time");
  });

  it("marks starter issues on the issue list only", async () => {
    document.body.innerHTML =
      repoHeader() + `<a data-testid="issue-pr-title-link" href="/pallets/flask/issues/7">Docs typo</a>`;
    const { fn, calls } = fakeLookup({
      "starter-issues pallets/flask": { state: "found", data: { repo: "pallets/flask", issues: [{ number: 7 }] } },
    });
    const page = createPageController(document, fn);
    await page.sync("/pallets/flask");
    expect(calls).not.toContain("starter-issues pallets/flask");
    await page.sync("/pallets/flask/issues");
    expect(document.querySelectorAll(".holt-starter")).toHaveLength(1);
    await page.sync("/pallets/flask/issues/7");
    expect(document.querySelector(".holt-starter")).toBeNull();
  });

  it("treats a failing lookup as 'Check with Holt'", async () => {
    document.body.innerHTML = repoHeader();
    const page = createPageController(document, (() => Promise.reject(new Error("offline"))) as LookupFn);
    await page.sync("/pallets/flask");
    expect(document.querySelector(".holt-chip")!.textContent).toBe("Check with Holt");
  });
});
