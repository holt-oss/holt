// Runs once when the server starts (not during `next build`).
export function register() {
  if (
    process.env.NODE_ENV === "production" &&
    process.env.MOCK_API === "1" &&
    process.env.ALLOW_MOCK_IN_PROD !== "1" &&
    process.env.NEXT_PHASE !== "phase-production-build"
  ) {
    throw new Error("MOCK_API=1 in production serves fake reports. Unset it, or set ALLOW_MOCK_IN_PROD=1 for a demo.");
  }
}
