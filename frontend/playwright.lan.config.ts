import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: ["lan-http.spec.ts", "organization.spec.ts"],
  fullyParallel: false,
  workers: 1,
  outputDir: "test-results-lan",
  use: {
    baseURL: "http://boxen.test:8174",
    browserName: "chromium",
    launchOptions: {
      executablePath: process.env.CHROME_BIN,
      args: [
        "--host-resolver-rules=MAP boxen.test 127.0.0.1",
        "--no-proxy-server",
      ],
    },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "../.venv/bin/python ../backend/tests/lan_browser_server.py",
    // Readiness uses loopback TCP; application requests keep the exact configured
    // boxen.test Host and Origin via Chromium's process-local DNS override.
    port: 8174,
    reuseExistingServer: false,
    timeout: 30_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
  },
});
