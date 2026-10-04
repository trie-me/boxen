import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "authentication-admin.spec.ts",
  workers: 1,
  outputDir: "test-results-admin",
  use: {
    baseURL: "http://127.0.0.1:8176",
    viewport: { width: 1280, height: 900 },
    launchOptions: {
      executablePath: process.env.CHROME_BIN,
      args: ["--no-proxy-server"],
    },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "../.venv/bin/python ../backend/tests/admin_browser_server.py",
    port: 8176,
    reuseExistingServer: false,
    timeout: 30000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5000 },
  },
});
