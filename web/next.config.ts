import type { NextConfig } from "next";

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
