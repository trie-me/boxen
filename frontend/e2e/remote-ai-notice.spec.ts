import { test, expect } from "@playwright/test";

test("remote AI configuration replaces local-only claims before analysis", async ({
  page,
}) => {
  // UI-only configuration fixture: no model endpoint or external photo transfer.
  await page.route("**/api/v1/system", async (route) => {
    const response = await route.fetch();
    const status = await response.json();
    await route.fulfill({
      response,
      json: { ...status, runtime_offline: false },
    });
  });
  await page.goto("/login");
  await page.getByLabel("Username", { exact: true }).fill("owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-only-long-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("link", { name: "New box", exact: true }).click();
  await page
    .getByLabel("Box name", { exact: true })
    .fill("Remote notice fixture");
  await page.getByRole("button", { name: "Create box", exact: true }).click();
  await expect(page.getByRole("note")).toContainText("Choosing Analyze sends");
  await page.goto("/system");
  await expect(
    page.getByText("REMOTE AI CONFIGURED", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Requested photo analyses use/)).toBeVisible();
  await expect(page.getByText(/All runtime resources are local/)).toHaveCount(
    0,
  );
});
