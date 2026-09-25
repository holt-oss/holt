// Development-only sign-in for when no OAuth app is configured. Creates a
// real database session, exactly like an OAuth sign-in would.
import { eq } from "drizzle-orm";
import { NextResponse, type NextRequest } from "next/server";
import { devSignInEnabled } from "@/auth";
import { db } from "@/db";
import { sessions, users } from "@/db/schema";
import { safeCallback } from "@/lib/safe-url";

export async function POST(req: NextRequest) {
  if (!devSignInEnabled) return new NextResponse("Not found", { status: 404 });
  const form = await req.formData();
  const name = String(form.get("name") || "Dev Student").slice(0, 60);
  const email = `${name.toLowerCase().replace(/[^a-z0-9]+/g, ".")}@dev.holt.local`;
  const safeBack = safeCallback(String(form.get("callbackUrl") || "/"));

  let [user] = await db.select().from(users).where(eq(users.email, email)).limit(1);
  if (!user) [user] = await db.insert(users).values({ name, email }).returning();
  const sessionToken = crypto.randomUUID();
  const expires = new Date(Date.now() + 30 * 86_400_000);
  await db.insert(sessions).values({ sessionToken, userId: user.id, expires });

  const res = NextResponse.redirect(new URL(safeBack, req.url), 303);
  res.cookies.set("authjs.session-token", sessionToken, { httpOnly: true, sameSite: "lax", path: "/", expires });
  return res;
}
