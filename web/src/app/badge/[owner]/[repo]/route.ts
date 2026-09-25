// /badge/{owner}/{repo}.svg: the README badge, proxied from the API server.
import { badge } from "@/lib/api";
import { isValidRepo } from "@/lib/repo";

export async function GET(_req: Request, { params }: { params: Promise<{ owner: string; repo: string }> }) {
  const { owner, repo: file } = await params;
  const repo = file.replace(/\.svg$/i, "");
  if (!isValidRepo(owner, repo)) return new Response("Not found", { status: 404 });
  return badge(owner, repo);
}
