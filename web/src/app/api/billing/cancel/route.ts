import { cancelPlan } from "@/lib/api";
import { userRoute } from "@/lib/bff";

export const POST = userRoute((user) => cancelPlan(user.id));
