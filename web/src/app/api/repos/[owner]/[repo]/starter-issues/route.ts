import { NextResponse } from "next/server";
import { starterIssues } from "@/lib/api";
import { isValidRepo } from "@/lib/repo";

export async function GET(_req: Request, { params }: { params: Promise<{ owner: string; repo: string }> }) {
  const { owner, repo } = await params;
  if (!isValidRepo(owner, repo)) return NextResponse.json({ error: { code: "invalid_repo", message: "Not a repository." } }, { status: 400 });
  const r = await starterIssues(`${owner}/${repo}`, 6);
  if (!r.ok) return NextResponse.json({ error: r.error }, { status: r.status });
  return NextResponse.json(r.data);
}
