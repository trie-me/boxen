import { defineConfig } from "@playwright/test";
import lan from "./playwright.lan.config";

export default defineConfig({
  ...lan,
  testMatch: ["scanner.spec.ts"],
  outputDir: "test-results-scanner",
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
        process.env.BOXEN_TEST_FRONTEND_DIR ?? "../.local/scanner-check",
    },
  },
});
