import { NextResponse, type NextRequest } from "next/server";
import { createOrder, orders, reportSignIn } from "@/lib/api";
import { asCurrency } from "@/lib/payments";
import { currentUser } from "@/lib/session";

const SIGN_IN = { error: { code: "unauthorized", message: "Please sign in first." } };

// Start a pass checkout. Only the pass's id and the currency go to the
// server: the price and the days come from its catalogue.
export async function POST(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json(SIGN_IN, { status: 401 });
  const body = (await req.json().catch(() => null)) as { pass?: unknown; currency?: unknown } | null;
  const pass = typeof body?.pass === "string" && /^[a-z0-9_]{1,40}$/.test(body.pass) ? body.pass : null;
  const currency = body?.currency === undefined ? "INR" : asCurrency(body.currency);
  if (!pass || !currency) {
    return NextResponse.json({ error: { code: "invalid_request", message: "That pass isn't on sale." } }, { status: 400 });
  }
  // A session from before account emails has no address on file yet, and the
  // pass's confirmation needs one. Alongside the order, so it adds no wait.
  const [r] = await Promise.all([createOrder(user.id, pass, currency), reportSignIn(user.id, user.email, false)]);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: r.status });
  return NextResponse.json(r.data);
}

// The purchase history, for the thank-you page while a payment is confirmed.
export async function GET() {
  const user = await currentUser();
  if (!user) return NextResponse.json(SIGN_IN, { status: 401 });
  const r = await orders(user.id);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: r.status });
  return NextResponse.json(r.data, { headers: { "Cache-Control": "no-store" } });
}
