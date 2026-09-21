import { test, expect } from "@playwright/test";

test("local inventory opens without an account and administration remains protected", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Find what you stored." }),
  ).toBeVisible();
  const session = await page.evaluate(() =>
    fetch("/api/v1/session").then((r) => r.json()),
  );
  expect(session.anonymous).toBe(true);
  expect(session.user.role).toBe("viewer");
  await expect(
    page.getByRole("link", { name: "New box", exact: true }),
  ).toHaveCount(0);
  await page.goto("/collections");
  await expect(
    page.getByRole("heading", { name: "Collections", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create collection", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Collection name", { exact: true })).toHaveCount(
    0,
  );
  await page.goto("/scan");
  await expect(page.getByLabel("Printed box code")).toBeVisible();
  await page.goto("/account");
  await expect(
    page.getByRole("heading", { name: "No account required" }),
  ).toBeVisible();
  await page.goto("/system/users");
  await expect(
    page.getByRole("button", { name: "Create user", exact: true }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(() => fetch("/api/v1/users").then((r) => r.status)),
  ).toBe(403);
});
