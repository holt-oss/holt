import { fetchLookup } from "../src/background";

const res = (status: number, body: unknown) =>
  Promise.resolve(new Response(typeof body === "string" ? body : JSON.stringify(body), { status }));

describe("fetchLookup", () => {
  it("maps 200, 404, 5xx, bad JSON and network errors", async () => {
    expect(await fetchLookup("u", () => res(200, { verdict: "viable" }))).toEqual({
      state: "found",
      data: { verdict: "viable" },
    });
    expect(await fetchLookup("u", () => res(404, { error: {} }))).toEqual({ state: "missing" });
    expect(await fetchLookup("u", () => res(503, "down"))).toEqual({ state: "error" });
    expect(await fetchLookup("u", () => res(200, "not json"))).toEqual({ state: "error" });
    expect(await fetchLookup("u", () => Promise.reject(new TypeError("offline")))).toEqual({ state: "error" });
  });

  it("sends no cookies", async () => {
    let init: RequestInit | undefined;
    await fetchLookup("u", (_u, i) => {
      init = i;
      return res(404, {});
    });
    expect(init?.credentials).toBe("omit");
  });
});
