import { NextResponse, type NextRequest } from "next/server";

// The visitor's country as Cloudflare sees it, for the pricing page's first
// currency. The page itself is the same for every signed-out visitor (a
// shared cache keeps it, lib/edge-cache.ts), so it asks here instead.
export function GET(req: NextRequest) {
  const code = req.headers.get("cf-ipcountry");
  const country = code && /^[A-Za-z]{2}$/.test(code) ? code.toUpperCase() : null;
  return NextResponse.json({ country }, { headers: { "Cache-Control": "private, no-store" } });
}
