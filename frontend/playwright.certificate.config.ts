import { defineConfig } from "@playwright/test";

if (!process.env.BOXEN_CERTIFICATE_TEST_ORIGIN || !process.env.CHROME_BIN)
  throw new Error(
    "Set the local HTTPS test origin and an isolated browser with no Boxen CA installed.",
  );

export default defineConfig({
  testDir: "./e2e",
  testMatch: "certificate-acceptance.spec.ts",
  workers: 1,
  outputDir: "test-results-certificate",
  use: {
    baseURL: process.env.BOXEN_CERTIFICATE_TEST_ORIGIN,
    browserName: "chromium",
    ignoreHTTPSErrors: false,
    launchOptions: {
      executablePath: process.env.CHROME_BIN,
      // Fake media + automated Allow response, not a physical permission UI test.
      // Certificate acceptance itself uses the visible browser interstitial.
      args: [
        "--no-proxy-server",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
      ],
    },
  },
});
