import "server-only";
import { NextResponse } from "next/server";
import { isSameOrigin } from "./same-origin";
import { currentUser, type SessionUser } from "./session";
import type { Result } from "./types";

type Handler = (user: SessionUser, req: Request) => Promise<Result<unknown>>;

/** A signed-in, same-origin JSON endpoint that forwards to the API. */
export function userRoute(handler: Handler, opts: { post?: boolean } = { post: true }) {
  return async (req: Request) => {
    if (opts.post && !isSameOrigin(req)) {
      return NextResponse.json({ error: { code: "unauthorized", message: "Cross-site request refused." } }, { status: 403 });
    }
    const user = await currentUser();
    if (!user) return NextResponse.json({ error: { code: "unauthorized", message: "Sign in first." } }, { status: 401 });
    const r = await handler(user, req);
    return r.ok
      ? NextResponse.json(r.data, { headers: { "Cache-Control": "no-store" } })
      : NextResponse.json({ error: r.error }, { status: r.status, headers: { "Cache-Control": "no-store" } });
  };
}

export async function jsonBody(req: Request): Promise<Record<string, unknown>> {
  const b = await req.json().catch(() => null);
  return b && typeof b === "object" && !Array.isArray(b) ? (b as Record<string, unknown>) : {};
}

export const BAD_BODY = { ok: false as const, status: 400, error: { code: "invalid_request" as const, message: "That request was missing something." } };
