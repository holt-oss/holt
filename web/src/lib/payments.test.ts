import assert from "node:assert/strict";
import { test } from "node:test";
import { asCurrency, currenciesOnSale, defaultCurrency, formatPrice, isOrderId, passFeatureLine, passToBuy, perMonth, priceIn, processor, returnedOrder } from "./payments.ts";

test("prices are shown in rupees from paise", () => {
  assert.equal(formatPrice(9900, "INR"), "₹99");
  assert.equal(formatPrice(49950, "INR"), "₹499.50");
  assert.equal(formatPrice(150000, "INR"), "₹1,500");
});

test("order ids and the pass to buy are checked", () => {
  assert.equal(isOrderId("0123456789abcdef0123456789abcdef"), true);
  assert.equal(isOrderId("../x"), false);
  assert.equal(isOrderId(undefined), false);
  const passes = [{ id: "pro_3m", name: "3 months", days: 90, amount: 24900, currency: "INR" }];
  assert.equal(passToBuy("pro_3m", passes), "pro_3m");
  assert.equal(passToBuy("pro_99m", passes), null);
  assert.equal(passToBuy(["pro_3m"], passes), null);
});

test("a longer pass says what it comes to a month", () => {
  assert.equal(perMonth(9900, 30, "INR"), null);
  assert.equal(perMonth(24900, 90, "INR"), "₹83 a month");
  assert.equal(perMonth(79900, 365, "INR"), "₹67 a month");
});

test("dollars are shown from cents, and a month to the cent", () => {
  assert.equal(formatPrice(700, "USD"), "$7");
  assert.equal(formatPrice(0, "USD"), "$0");
  assert.equal(formatPrice(1550, "USD"), "$15.50");
  assert.equal(perMonth(700, 30, "USD"), null);
  assert.equal(perMonth(1500, 90, "USD"), "$5 a month");
  assert.equal(perMonth(3900, 365, "USD"), "$3.25 a month");
});

test("a pass is shown in the currencies it is sold in", () => {
  const both = { id: "pro_1m", name: "1 month", days: 30, amount: 9900, currency: "INR", prices: [{ currency: "INR", amount: 9900 }, { currency: "USD", amount: 700 }] };
  const rupees = { id: "pro_3m", name: "3 months", days: 90, amount: 24900, currency: "INR", prices: [{ currency: "INR", amount: 24900 }] };
  // A server from before USD: no `prices`.
  const old = { id: "pro_12m", name: "12 months", days: 365, amount: 79900, currency: "INR" } as unknown as typeof rupees;
  assert.deepEqual(currenciesOnSale([both, rupees, old]), ["INR", "USD"]);
  assert.deepEqual(currenciesOnSale([rupees, old]), ["INR"]);
  assert.deepEqual(currenciesOnSale([]), []);
  assert.equal(priceIn(both, "USD"), 700);
  assert.equal(priceIn(rupees, "USD"), null);
  assert.equal(priceIn(old, "INR"), 79900);
});

test("rupees first in India, dollars elsewhere, of what is on sale", () => {
  assert.equal(defaultCurrency("IN", ["INR", "USD"]), "INR");
  assert.equal(defaultCurrency("in", ["INR", "USD"]), "INR");
  for (const country of ["US", "DE", "XX", "T1", "", null, undefined]) assert.equal(defaultCurrency(country, ["INR", "USD"]), "USD");
  assert.equal(defaultCurrency("US", ["INR"]), "INR");
  assert.equal(defaultCurrency("IN", ["USD"]), "USD");
  assert.equal(defaultCurrency("IN", []), "USD");
  assert.equal(asCurrency("usd"), "USD");
  assert.equal(asCurrency("INR"), "INR");
  assert.equal(asCurrency("eur"), null);
  assert.equal(asCurrency(["usd"]), null);
});

test("the order is read from the thank-you address whatever is added after it", () => {
  const id = "0123456789abcdef0123456789abcdef";
  assert.equal(returnedOrder(id), id);
  assert.equal(returnedOrder(`${id}?payment_id=pay_1&status=succeeded`), id);
  assert.equal(returnedOrder("pay_1"), null);
  assert.equal(returnedOrder([id]), null);
  assert.equal(returnedOrder(undefined), null);
});

test("the processor is named from the order", () => {
  assert.equal(processor({ provider: "dodo", currency: "USD" }), "Dodo Payments");
  assert.equal(processor({ provider: "razorpay", currency: "INR" }), "Razorpay");
  assert.equal(processor({ currency: "USD" }), "Dodo Payments");
  assert.equal(processor(undefined), "Razorpay");
});

test("Pro features in words", () => {
  assert.equal(passFeatureLine({ id: "merge_plan", name: "Merge plan", per_month: 30, unlimited: false }), "Merge plan: 30 a month");
  assert.equal(passFeatureLine({ id: "pr_watch", name: "PR watch", per_month: null, unlimited: true }), "PR watch");
});
