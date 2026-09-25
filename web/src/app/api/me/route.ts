import { me } from "@/lib/api";
import { userRoute } from "@/lib/bff";

// Polled after a payment while the plan activates.
export const GET = userRoute((user) => me(user.id), { post: false });
