import type { NextConfig } from "next";

// The policy pages (/terms, /privacy, /refunds, /contact) render these, and
// they are prerendered at build time. A production build must not bake in
// the placeholders that src/lib/site.ts falls back to. Local builds without
// the real values: HOLT_ALLOW_PLACEHOLDER_CONTACT=1.
if (process.env.NODE_ENV === "production" && process.env.HOLT_ALLOW_PLACEHOLDER_CONTACT !== "1") {
  for (const k of ["CONTACT_EMAIL", "CONTACT_CITY"]) {
    const v = process.env[`NEXT_PUBLIC_${k}`];
    if (!v || v === k) {
      throw new Error(
        `NEXT_PUBLIC_${k} is unset or the placeholder "${k}": the policy pages would ship it. Set it for the build, or HOLT_ALLOW_PLACEHOLDER_CONTACT=1 for a local build.`,
      );
    }
  }
}

const nextConfig: NextConfig = {
  // The staging/production Docker image runs .next/standalone.
  output: "standalone",
  // OG images read these fonts from disk at runtime.
  outputFileTracingIncludes: {
    "/opengraph-image": ["./assets/fonts/**/*"],
    "/[owner]/[repo]/opengraph-image": ["./assets/fonts/**/*"],
  },
  devIndicators: false,
  poweredByHeader: false,
};

export default nextConfig;
