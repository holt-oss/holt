// GET /api/public/report/{owner}/{repo}: the cached rules report, or 404.
// For the browser extension; never starts an analysis.
import { NextResponse } from "next/server";
import { getReport } from "@/lib/api";
import { preflight, publicGet } from "@/lib/public-api";
import { isValidRepo } from "@/lib/repo";

export function OPTIONS(req: Request) {
  return preflight(req);
}

export async function GET(req: Request, { params }: { params: Promise<{ owner: string; repo: string }> }) {
  const { owner, repo } = await params;
  if (!isValidRepo(owner, repo)) {
    return NextResponse.json({ error: { code: "invalid_repo", message: "That isn't a GitHub repository." } }, { status: 400 });
  }
  return publicGet(req, "report", () => getReport(`${owner}/${repo}`, "rules", 7));
}
