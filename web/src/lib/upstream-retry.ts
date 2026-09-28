// One more try when the connection to the API server drops before it answers.
//
// A deploy swaps the server with no gap (deploy/swap.sh): the new one starts,
// then the old one gets SIGTERM and closes its idle keep-alive connections.
// A request that fetch sends on one of those at that moment fails with a
// reset ("other side closed"), and the page showed "Holt's analysis server
// isn't answering". The server never read that request, so sending it again,
// on a fresh connection to whichever server is up, is safe. Timeouts and
// real answers (any status) are never retried.

const DROPPED = new Set(["ECONNRESET", "ECONNREFUSED", "EPIPE", "UND_ERR_SOCKET", "UND_ERR_CLOSED"]);

export function droppedConnection(err: unknown): boolean {
  const code = (err as { cause?: { code?: unknown } } | null)?.cause?.code;
  return typeof code === "string" && DROPPED.has(code);
}

export async function retryDropped(send: () => Promise<Response>): Promise<Response> {
  try {
    return await send();
  } catch (err) {
    if (!droppedConnection(err)) throw err;
    return await send();
  }
}
