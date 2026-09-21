import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";
import lan from "./playwright.lan.config";

export default defineConfig({
  ...lan,
  testMatch: ["search-suggestions.spec.ts"],
  outputDir: "test-results-suggestions",
  use: {
    ...lan.use,
    launchOptions: {
      ...lan.use?.launchOptions,
      executablePath:
        process.env.CHROME_BIN ??
        "/usr/lib64/chromium-browser/chromium-browser",
    },
  },
  webServer: {
    ...lan.webServer,
    command: "../.venv/bin/python ../backend/tests/lan_browser_server.py",
    env: {
      BOXEN_TEST_FRONTEND_DIR:
        process.env.BOXEN_TEST_FRONTEND_DIR ??
        fileURLToPath(new URL("../.local/search-suggestions-build", import.meta.url)),
    },
  },
});
