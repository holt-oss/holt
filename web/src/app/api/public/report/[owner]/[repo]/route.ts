// GET /api/public/report/{owner}/{repo}: the cached rules report, or 404.
// For the browser extension; never starts an analysis.
import { NextResponse } from "next/server";
import { getReport } from "@/lib/api";
import { preflight, publicGet } from "@/lib/public-api";
import { isValidRepo } from "@/lib/repo";

export function OPTIONS() {
  return preflight();
}

export async function GET(req: Request, { params }: { params: Promise<{ owner: string; repo: string }> }) {
  const { owner, repo } = await params;
  if (!isValidRepo(owner, repo)) {
    return NextResponse.json({ error: { code: "invalid_repo", message: "That isn't a GitHub repository." } }, { status: 400 });
  }
  // The extension reads only the verdict and counts, so drop the evidence list.
  return publicGet(req, "report", async () => {
    const r = await getReport(`${owner}/${repo}`, "rules", 7);
    return r.ok ? { ok: true as const, data: { ...r.data, evidence: [] } } : r;
  });
}
