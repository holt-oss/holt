// Smoke tests against a deployed Holt. BASE_URL defaults to staging.
// Uses the server's cached Chromium (~/.cache/ms-playwright) instead of
// downloading browsers: set CHROMIUM_PATH to point somewhere else.
import { defineConfig, devices } from "@playwright/test";
import { chromiumPath } from "./chromium";

const executablePath = chromiumPath();

export default defineConfig({
  testDir: "./tests",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: process.env.CI ? "list" : [["list"]],
  use: {
    baseURL: process.env.BASE_URL || "https://holt-new.aahil-khan.xyz",
    // HOST_HEADER=githolt.com: test a stack on a local port as if it were
    // the public host (before the tunnel is up). Sent on API requests; the
    // browser's own navigations keep the URL's host.
    extraHTTPHeaders: process.env.HOST_HEADER ? { Host: process.env.HOST_HEADER } : {},
    launchOptions: executablePath ? { executablePath } : {},
    trace: "off",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "phone",
      use: { ...devices["iPhone 13"], browserName: "chromium", defaultBrowserType: "chromium", viewport: { width: 390, height: 844 } },
    },
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
});
