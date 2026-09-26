import { defineConfig } from "vitest/config";

export default defineConfig({
  // `css: true` lets `?raw` imports of stylesheets return their text.
  test: { environment: "jsdom", globals: true, css: true },
  // test/content-css.test.ts reads web/src/app/globals.css from the repo root.
  server: { fs: { allow: [".."] } },
});
