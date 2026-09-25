import "server-only";
import { headers } from "next/headers";
import { auth } from "@/auth";
import type { Caller } from "./api";

export interface SessionUser {
  id: string;
  name: string | null;
  email: string | null;
  image: string | null;
}

/** The signed-in user, or null. Never throws: a down database means "signed out". */
export async function currentUser(): Promise<SessionUser | null> {
  try {
    const s = await auth();
    if (!s?.user?.id) return null;
    return { id: s.user.id, name: s.user.name ?? null, email: s.user.email ?? null, image: s.user.image ?? null };
  } catch (e) {
    console.error("[holt] session lookup failed:", (e as Error).message);
    return null;
  }
}

export async function caller(): Promise<Caller> {
  const [user, h] = await Promise.all([currentUser(), headers()]);
  const ip = h.get("x-forwarded-for")?.split(",")[0]?.trim() || h.get("x-real-ip") || null;
  return { userId: user?.id ?? null, ip };
}
