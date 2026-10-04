import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const origin = "http://127.0.0.1:8176";
test.skip(
  ({ baseURL }) => baseURL !== origin,
  "Run with playwright.admin.config.ts",
);

async function login(
  page: Page,
  username = "admin",
  password = "test-only-admin-password",
) {
  await page.goto("/login");
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Find what you stored." }),
  ).toBeVisible();
}

async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
}

test("owner manages users and revokes real browser sessions while core account remains protected", async ({
  page,
  browser,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page);
  await page.goto("/system/users");
  await expect(
    page.getByText("Core administrator", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Edit user admin", exact: true })
    .click();
  await expect(page.getByLabel("Role", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("Status", { exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Add user", exact: true }).click();
  await page.getByLabel("Username", { exact: true }).fill("team-member");
  await page.getByLabel("Display name", { exact: true }).fill("Team Member");
  await page.getByLabel("Role", { exact: true }).selectOption("editor");
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-only-member-password");
  await page.getByRole("button", { name: "Save user", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Team Member", exact: true }),
  ).toBeVisible();

  const memberContext = await browser.newContext({ baseURL: origin });
  const member = await memberContext.newPage();
  await login(member, "team-member", "test-only-member-password");
  await page
    .getByRole("link", { name: "Authentication & sign-ins", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Authentication & sign-ins",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText("This browser", { exact: true })).toBeVisible();
  const users = await page.evaluate(() =>
    fetch("/api/v1/users").then((response) => response.json()),
  );
  const memberUser = users.items.find(
    (user: { username: string }) => user.username === "team-member",
  );
  await page
    .getByLabel("Filter sessions and provider links by user")
    .selectOption(memberUser.id);
  await expect(
    page.getByRole("button", {
      name: "Revoke session for team-member",
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "Revoke session for team-member",
      exact: true,
    })
    .click();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  expect((await member.request.get("/api/v1/session")).status()).toBe(200);
  await page
    .getByRole("button", { name: "Revoke all sessions", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Every browser signed in as this user");
  await dialog
    .getByRole("button", { name: "Revoke all sessions", exact: true })
    .click();
  await expect(
    page.getByText("Selected sessions revoked.", { exact: true }),
  ).toBeVisible();
  expect((await member.request.get("/api/v1/session")).status()).toBe(401);
  await expect(
    page
      .locator("#auth-sessions")
      .getByText("Revoked", { exact: true })
      .first(),
  ).toBeVisible();
  await expect(page.locator("#auth-events")).toContainText("session");

  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({
    path: "test-results-admin/auth-admin-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 375, height: 812 });
  await noOverflow(page);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({
    path: "test-results-admin/auth-admin-mobile.png",
    fullPage: true,
  });

  await page.goto("/system/users");
  await login(member, "team-member", "test-only-member-password");
  await page
    .getByRole("button", { name: "Edit user team-member", exact: true })
    .click();
  await page
    .getByLabel("Reset password (optional)", { exact: true })
    .fill("test-only-reset-password");
  await page.getByRole("button", { name: "Save user", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect((await member.request.get("/api/v1/session")).status()).toBe(401);
  await login(member, "team-member", "test-only-reset-password");
  await page
    .getByRole("button", { name: "Edit user team-member", exact: true })
    .click();
  await page.getByLabel("Status", { exact: true }).selectOption("disabled");
  await page.getByRole("button", { name: "Save user", exact: true }).click();
  await expect(
    page.getByText("team-member · editor · disabled", { exact: true }),
  ).toBeVisible();
  expect((await member.request.get("/api/v1/session")).status()).toBe(401);
  await memberContext.close();
  expect(errors).toEqual([]);
});

test("revoking the current session returns to sign-in", async ({ page }) => {
  await login(page);
  await page.goto("/system/authentication");
  await page
    .getByRole("button", {
      name: "Revoke session for admin in this browser",
      exact: true,
    })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "You will be signed out immediately",
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Revoke session", exact: true })
    .click();
  await expect(page).toHaveURL(origin + "/login");
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  expect((await page.request.get("/api/v1/session")).status()).toBe(401);
});

test("owner links and unlinks verified provider subjects, excluding the core administrator", async ({
  page,
}) => {
  await login(page);
  await page.goto("/system/authentication");
  await expect(page.locator("#auth-providers")).toContainText(
    "https://identity.example.test",
  );
  await expect(page.locator("#auth-providers")).toContainText(
    origin + "/api/v1/auth/oidc/example/callback",
  );
  await page
    .getByRole("button", { name: "Link identity", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog
      .getByLabel("Local user")
      .locator("option")
      .filter({ hasText: "admin" }),
  ).toHaveCount(0);
  await dialog
    .getByLabel("Local user")
    .selectOption({ label: "reader · viewer" });
  await dialog
    .getByLabel("Provider subject", { exact: true })
    .fill("Oidc|Reader-01");
  await dialog
    .getByRole("button", { name: "Link identity", exact: true })
    .click();
  await expect(
    page.getByText("Provider identity linked.", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("#auth-identities")).toContainText(
    "Oidc|Reader-01",
  );
  await expect(page.locator("#auth-identities")).toContainText(
    "reader · Example ID",
  );
  await page
    .getByRole("button", {
      name: "Unlink identity for reader with Example ID",
      exact: true,
    })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  await expect(page.locator("#auth-identities")).toContainText(
    "Oidc|Reader-01",
  );
  await page
    .getByRole("button", {
      name: "Unlink identity for reader with Example ID",
      exact: true,
    })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Unlink identity", exact: true })
    .click();
  await expect(
    page.getByText("Provider identity unlinked.", { exact: true }),
  ).toBeVisible();
  await expect(page.locator("#auth-identities")).toContainText(
    "No linked identities for this selection.",
  );
});

test("viewers cannot use administration and public help remains accessible on mobile", async ({
  page,
}) => {
  await login(page, "reader", "test-only-reader-password");
  await page.goto("/system/authentication");
  await expect(
    page.getByRole("heading", { name: "Owner access required" }),
  ).toBeVisible();
  expect((await page.request.get("/api/v1/auth/sessions")).status()).toBe(403);
  await page.context().clearCookies();
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/help/authentication");
  await expect(page.locator("main h1")).toBeVisible();
  await expect(page.locator("main")).toContainText("password");
  await noOverflow(page);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({
    path: "test-results-admin/auth-help-mobile.png",
    fullPage: true,
  });
});

test("provider login uses returned authorization URL and callback errors never reflect untrusted input", async ({
  page,
}) => {
  await page.route("**/api/v1/auth/providers", (route) =>
    route.fulfill({ json: { items: [{ id: "work", label: "Work SSO" }] } }),
  );
  await page.route("**/api/v1/auth/oidc/work/start", (route) =>
    route.fulfill({
      json: { authorization_url: origin + "/test-provider-authorize" },
    }),
  );
  await page.route("**/test-provider-authorize", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>Provider authorization</h1>",
    }),
  );
  await page.goto(
    "/login?oauth_error=%3Cscript%3Eunsafe-marker%3C%2Fscript%3E",
  );
  await expect(page.getByRole("alert")).toContainText(
    "Provider sign-in could not be completed",
  );
  await expect(page.locator("body")).not.toContainText("unsafe-marker");
  await page
    .getByRole("button", { name: "Continue with Work SSO", exact: true })
    .click();
  await expect(page).toHaveURL(origin + "/test-provider-authorize");
});
