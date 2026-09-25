// The URL trick: /https://github.com/o/r, /github.com/o/r and deep GitHub
// paths like /o/r/pulls all land on the report page /o/r.
import { NextResponse, type NextRequest } from "next/server";
import { redirectTargetForPath } from "@/lib/repo";

export function proxy(req: NextRequest) {
  const target = redirectTargetForPath(req.nextUrl.pathname, req.nextUrl.search);
  if (!target) return NextResponse.next();
  return NextResponse.redirect(new URL(target, req.url), 308);
}

export const config = {
  matcher: ["/((?!_next/|api/|badge/|favicon|icon|robots|sitemap).*)"],
};
