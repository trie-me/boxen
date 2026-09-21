import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8173",
    browserName: "chromium",
    launchOptions: { executablePath: process.env.CHROME_BIN },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "../.venv/bin/python ../backend/tests/browser_server.py",
    url: "http://127.0.0.1:8173/api/v1/health/ready",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
