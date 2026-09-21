import { defineConfig } from "@playwright/test";

if (!process.env.BOXEN_TEST_HTTPS_ORIGIN || !process.env.CHROME_BIN)
  throw new Error(
    "Set BOXEN_TEST_HTTPS_ORIGIN for a disposable TLS fixture and CHROME_BIN for an isolated trusted browser.",
  );

export default defineConfig({
  testDir: "./e2e",
  testMatch: "native-https.spec.ts",
  workers: 1,
  outputDir: "test-results-https",
  use: {
    baseURL: process.env.BOXEN_TEST_HTTPS_ORIGIN,
    browserName: "chromium",
    ignoreHTTPSErrors: false,
    viewport: { width: 375, height: 812 },
    launchOptions: {
      executablePath: process.env.CHROME_BIN,
      args: ["--no-proxy-server", "--use-fake-device-for-media-stream"],
    },
    trace: "retain-on-failure",
  },
});
