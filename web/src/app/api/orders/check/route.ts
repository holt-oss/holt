import { NextResponse, type NextRequest } from "next/server";
import { checkOrder } from "@/lib/api";
import { isOrderId } from "@/lib/payments";
import { currentUser } from "@/lib/session";

// Where one of the buyer's orders stands, while the thank-you page waits.
// Only the order's id goes to the server, which asks the processor itself.
export async function POST(req: NextRequest) {
  const user = await currentUser();
  if (!user) return NextResponse.json({ error: { code: "unauthorized", message: "Please sign in first." } }, { status: 401 });
  const body = (await req.json().catch(() => null)) as { order?: unknown } | null;
  if (!isOrderId(body?.order)) {
    return NextResponse.json({ error: { code: "not_found", message: "We couldn't find that order." } }, { status: 404 });
  }
  const r = await checkOrder(user.id, body.order);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: r.status });
  return NextResponse.json(r.data, { headers: { "Cache-Control": "no-store" } });
}
