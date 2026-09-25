// GET /api/public/starter-issues/{owner}/{repo}: open newcomer issues.
// For the browser extension; read-only.
import { NextResponse } from "next/server";
import { starterIssues } from "@/lib/api";
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
  return publicGet(req, "issues", (ip) => starterIssues(`${owner}/${repo}`, 20, { ip }));
}
