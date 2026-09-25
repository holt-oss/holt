import { verifyPayment } from "@/lib/api";
import { BAD_BODY, jsonBody, userRoute } from "@/lib/bff";
import type { RazorpaySuccess } from "@/lib/types";

const RZP = /^[A-Za-z0-9_-]{1,128}$/;
const str = (v: unknown) => (typeof v === "string" && RZP.test(v) ? v : undefined);

// Passes Razorpay's success payload through unchanged; the server checks the
// signature. Nothing the browser says grants anything here.
export const POST = userRoute(async (user, req) => {
  const b = await jsonBody(req);
  const body: RazorpaySuccess = {
    razorpay_payment_id: str(b.razorpay_payment_id) ?? "",
    razorpay_signature: str(b.razorpay_signature) ?? "",
  };
  const order = str(b.razorpay_order_id);
  const sub = str(b.razorpay_subscription_id);
  if (!body.razorpay_payment_id || !body.razorpay_signature || (!order && !sub)) return BAD_BODY;
  if (order) body.razorpay_order_id = order;
  if (sub) body.razorpay_subscription_id = sub;
  return verifyPayment(user.id, body);
});
