import { test, expect } from "@playwright/test";

// Read-only check of an explicitly selected local HTTPS installation.
test.skip(
  ({ baseURL }) => baseURL !== process.env.BOXEN_CERTIFICATE_TEST_ORIGIN,
  "Run with playwright.certificate.config.ts and an empty isolated trust store",
);

test("normal certificate-warning acceptance permits camera access without CA installation", async ({
  page,
}) => {
  await expect(page.goto("/scan")).rejects.toThrow(
    "ERR_CERT_AUTHORITY_INVALID",
  );
  await page.getByRole("button", { name: "Advanced", exact: true }).click();
  await page.getByRole("link", { name: /^Proceed to .* \(unsafe\)$/ }).click();
  await page.getByRole("tab", { name: "Live camera", exact: true }).click();
  expect(await page.evaluate(() => isSecureContext)).toBe(true);
  await page.getByRole("button", { name: "Start camera", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Stop camera", exact: true }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const video = document.querySelector("video");
        return (
          !!(video?.srcObject as MediaStream | null)?.active &&
          !!video?.videoWidth
        );
      }),
    )
    .toBe(true);
  await page.getByRole("button", { name: "Stop camera", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Start camera", exact: true }),
  ).toBeEnabled();
});
