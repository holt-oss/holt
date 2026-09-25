import { NextResponse, type NextRequest } from "next/server";
import { startAnalysis } from "@/lib/api";
import { isKnownModel } from "@/lib/models";
import { parseRepoInput } from "@/lib/repo";
import { caller } from "@/lib/session";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { repo?: string; mode?: string; days?: number; refresh?: boolean; model?: unknown } | null;
  const ref = parseRepoInput(String(body?.repo ?? ""));
  if (!ref) {
    return NextResponse.json(
      { error: { code: "invalid_repo", message: "That doesn't look like a GitHub repository. Try something like pallets/flask." } },
      { status: 400 },
    );
  }
  const mode = body?.mode === "ai" ? "ai" : "rules";
  const days = clampDays(body?.days);
  const who = await caller();
  if (mode === "ai" && !who.userId) {
    return NextResponse.json({ error: { code: "unauthorized", message: "Sign in to get an AI report." } }, { status: 401 });
  }
  // Only known model ids pass through; the server decides what the user may use.
  const model = mode === "ai" && isKnownModel(body?.model) ? body.model : undefined;
  const r = await startAnalysis(`${ref.owner}/${ref.repo}`, mode, days, Boolean(body?.refresh), who, model);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: r.status });
  return NextResponse.json(r.data, { status: r.data.status === "queued" ? 202 : 200 });
}

function clampDays(d: unknown): number {
  const n = Math.round(Number(d));
  return Number.isFinite(n) && n >= 1 && n <= 90 ? n : 7;
}
