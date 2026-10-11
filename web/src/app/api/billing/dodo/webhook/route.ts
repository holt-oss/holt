import { NextResponse, type NextRequest } from "next/server";
import { DODO_WEBHOOK_HEADERS, forwardDodoWebhook } from "@/lib/api";

// Dodo Payments' webhook URL. The body and the three headers it is signed
// with go to the server exactly as received; the server checks the signature
// before reading anything. Dodo retries on anything but 2xx.
const MAX_BYTES = 256 * 1024;
const NOT_DODO = { error: { code: "invalid_request", message: "Not a Dodo Payments webhook." } };

export async function POST(req: NextRequest) {
  const [id, timestamp, signature] = DODO_WEBHOOK_HEADERS.map((name) => req.headers.get(name));
  const declared = Number(req.headers.get("content-length") ?? 0);
  if (!id || !timestamp || !signature || declared > MAX_BYTES) return NextResponse.json(NOT_DODO, { status: 400 });
  const body = await req.arrayBuffer();
  if (body.byteLength > MAX_BYTES) return NextResponse.json(NOT_DODO, { status: 400 });
  const r = await forwardDodoWebhook(body, { "webhook-id": id, "webhook-timestamp": timestamp, "webhook-signature": signature });
  return NextResponse.json(r.body, { status: r.status });
}
