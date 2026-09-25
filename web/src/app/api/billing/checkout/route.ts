import { checkout } from "@/lib/api";
import { BAD_BODY, jsonBody, userRoute } from "@/lib/bff";

const ID = /^[a-z0-9_-]{1,32}$/;

export const POST = userRoute(async (user, req) => {
  const b = await jsonBody(req);
  const currency = b.currency === "USD" ? "USD" : "INR";
  if (typeof b.plan === "string" && ID.test(b.plan)) return checkout(user.id, { plan: b.plan }, currency);
  if (typeof b.pack === "string" && ID.test(b.pack)) return checkout(user.id, { pack: b.pack }, currency);
  return BAD_BODY;
});
