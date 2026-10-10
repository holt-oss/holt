// Pro passes: what the pricing page, the checkout and the thank-you page
// show. No prices live here; they come from the server (API.md, "Passes").
import type { Order, Pass, PassFeature } from "./types";

/** What a pass can be paid in: rupees through Razorpay, dollars through Dodo Payments. */
export type Currency = "INR" | "USD";
const CURRENCIES: Currency[] = ["INR", "USD"];

/** "usd", "USD" -> "USD"; anything else -> null. */
export function asCurrency(value: unknown): Currency | null {
  const c = typeof value === "string" ? value.toUpperCase() : "";
  return CURRENCIES.find((k) => k === c) ?? null;
}

/** A pass's prices. A server from before USD sends only `amount` and `currency`. */
function pricesOf(pass: Pass): { currency: string; amount: number }[] {
  return pass.prices?.length ? pass.prices : [{ currency: pass.currency, amount: pass.amount }];
}

/** The currencies any pass on sale can be bought in, ₹ first. */
export function currenciesOnSale(passes: Pass[]): Currency[] {
  return CURRENCIES.filter((c) => passes.some((p) => pricesOf(p).some((x) => x.currency === c)));
}

/** A pass's price in `currency`; null if it isn't sold in it. */
export function priceIn(pass: Pass, currency: Currency): number | null {
  return pricesOf(pass).find((x) => x.currency === currency)?.amount ?? null;
}

/** The currency shown first: ₹ in India (Cloudflare's country code), $ elsewhere, of those on sale. */
export function defaultCurrency(country: string | null | undefined, onSale: Currency[]): Currency {
  const wanted: Currency = country?.toUpperCase() === "IN" ? "INR" : "USD";
  return onSale.includes(wanted) ? wanted : (onSale[0] ?? "USD");
}

/** Who takes a payment, by the order's `provider` (or its currency, from an older server). */
export function processor(order: { provider?: string; currency?: string } | null | undefined): string {
  return order?.provider === "dodo" || (!order?.provider && order?.currency === "USD") ? "Dodo Payments" : "Razorpay";
}

/** 49900 INR (paise) -> "₹499"; 49950 -> "₹499.50"; 700 USD (cents) -> "$7". */
export function formatPrice(amount: number, currency: string): string {
  const major = amount / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    minimumFractionDigits: Number.isInteger(major) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(major);
}

/** Our order ids: 32 hex characters. */
export function isOrderId(id: unknown): id is string {
  return typeof id === "string" && /^[0-9a-f]{32}$/.test(id);
}

/**
 * The order in the thank-you page's address (`?order=`). Dodo Payments adds
 * its own parameters to that address on the way back; whatever lands after
 * the id is dropped, and nothing else Dodo adds is read.
 */
export function returnedOrder(value: unknown): string | null {
  const id = typeof value === "string" ? value.slice(0, 32) : null;
  return isOrderId(id) ? id : null;
}

export const STATUS_LABEL: Record<Order["status"], string> = {
  created: "Waiting for payment",
  paid: "Paid",
  failed: "Didn't go through",
  held: "Being checked",
};

/** A pass to buy straight after signing in (`/pricing?buy=pro_3m`), if it's on sale. */
export function passToBuy(buy: unknown, passes: { id: string }[]): string | null {
  return typeof buy === "string" && passes.some((p) => p.id === buy) ? buy : null;
}

/** What one Pro feature gives, in words. */
export function passFeatureLine(f: PassFeature): string {
  if (f.unlimited) return f.name;
  return `${f.name}: ${f.per_month} a month`;
}

/** A pass's price per month, when it's worth saying ("₹83 a month", "$3.25 a month"). */
export function perMonth(amount: number, days: number, currency: string): string | null {
  const months = Math.round(days / 30);
  if (months <= 1) return null;
  // Whole rupees; dollars to the cent.
  const each = currency === "INR" ? Math.round(amount / months / 100) * 100 : Math.round(amount / months);
  return `${formatPrice(each, currency)} a month`;
}
