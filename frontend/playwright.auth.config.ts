import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "auth-validation.spec.ts",
  workers: 1,
  outputDir: "test-results-auth",
  use: {
    baseURL: "http://boxen-auth.test:8175",
    viewport: { width: 375, height: 812 },
    launchOptions: {
      executablePath: process.env.CHROME_BIN,
      args: [
        "--host-resolver-rules=MAP boxen-auth.test 127.0.0.1",
        "--no-proxy-server",
      ],
    },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "../.venv/bin/python ../backend/tests/auth_browser_server.py",
    port: 8175,
    reuseExistingServer: false,
    timeout: 30000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5000 },
  },
});
