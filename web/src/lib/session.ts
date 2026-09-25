import "server-only";
import { headers } from "next/headers";
import { unstable_rethrow } from "next/navigation";
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
    unstable_rethrow(e);
    console.error("[holt] session lookup failed:", (e as Error).message);
    return null;
  }
}

/** Who is asking, for API calls. Pass `user` when the page already looked it up. */
export async function caller(known?: SessionUser | null): Promise<Caller> {
  const [user, h] = await Promise.all([known !== undefined ? known : currentUser(), headers()]);
  // The server rate-limits anonymous work per client IP and never guesses it,
  // so always pass one on (Cloudflare tunnel first, then common proxy headers).
  const ip =
    h.get("cf-connecting-ip") ||
    h.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    h.get("x-real-ip") ||
    "127.0.0.1";
  return { userId: user?.id ?? null, ip };
}
