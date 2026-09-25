import assert from "node:assert/strict";
import { test } from "node:test";
import { formatMoney } from "./money.ts";

test("formats minor units", () => {
  assert.equal(formatMoney(9900, "INR"), "₹99");
  assert.equal(formatMoney(29950, "INR"), "₹299.50");
  assert.equal(formatMoney(500, "USD"), "$5");
  assert.equal(formatMoney(0, "INR"), "₹0");
});
