import assert from "node:assert/strict";
import { test } from "node:test";
import { availability, DEFAULT_MODEL, initialModel, isKnownModel, MODELS } from "./models.ts";

const byId = (id: string) => MODELS.find((m) => m.id === id)!;

test("ids are unique and every model can be served somewhere", () => {
  assert.equal(new Set(MODELS.map((m) => m.id)).size, MODELS.length);
  for (const m of MODELS) assert.ok(Object.keys(m.providers).length > 0, m.id);
  assert.ok(isKnownModel(DEFAULT_MODEL));
});

test("free users get free models; pro models ask for an upgrade", () => {
  assert.deepEqual(availability(byId("gpt-5-mini"), { kind: "free" }), { ok: true });
  assert.deepEqual(availability(byId("claude-sonnet-5"), { kind: "free" }), { ok: false, reason: "upgrade" });
  assert.deepEqual(availability(byId("claude-sonnet-5"), { kind: "plan" }), { ok: true });
});

test("BYOK unlocks whatever the key's provider serves", () => {
  const anthropic = { kind: "byok" as const, provider: "anthropic" as const, model: null };
  assert.deepEqual(availability(byId("claude-opus-5-5"), anthropic), { ok: true });
  assert.deepEqual(availability(byId("gpt-5"), anthropic), { ok: false, reason: "not-on-your-key" });
  const openrouter = { kind: "byok" as const, provider: "openrouter" as const, model: null };
  assert.ok(MODELS.every((m) => availability(m, openrouter).ok));
});

test("preselection", () => {
  assert.equal(initialModel({ kind: "free" }), DEFAULT_MODEL);
  assert.equal(initialModel({ kind: "free" }, "claude-opus-5-5"), DEFAULT_MODEL); // locked: ignored
  assert.equal(initialModel({ kind: "plan" }, "claude-opus-5-5"), "claude-opus-5-5");
  assert.equal(initialModel({ kind: "byok", provider: "anthropic", model: "claude-sonnet-5" }), "claude-sonnet-5");
  assert.equal(initialModel({ kind: "byok", provider: "anthropic", model: null }), "claude-haiku-4-5");
  assert.equal(isKnownModel("../../etc"), false);
});
