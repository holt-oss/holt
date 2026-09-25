import { proxyJobEvents } from "@/lib/sse-proxy";

export const dynamic = "force-dynamic";

export async function GET(req: Request, { params }: { params: Promise<{ job: string }> }) {
  const { job } = await params;
  return proxyJobEvents("analyses", job, req.signal);
}
