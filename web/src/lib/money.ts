import type { Price } from "./types";

/** 9900 INR -> "₹99", 29950 INR -> "₹299.50", 500 USD -> "$5". */
export function formatMoney(amount: number, currency: string): string {
  const major = amount / 100;
  return new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: Number.isInteger(major) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(major);
}

export function priceIn(prices: Price[], currency: string): Price | undefined {
  return prices.find((p) => p.currency === currency);
}

export function perInterval(p: Price): string {
  return p.interval ? `/ ${p.interval}` : "one-time";
}
