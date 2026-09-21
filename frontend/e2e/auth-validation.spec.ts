import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const origin = "http://boxen-auth.test:8175";
test.skip(
  ({ baseURL }) => baseURL !== origin,
  "Run with playwright.auth.config.ts",
);

test("first owner setup and sign-in expose actual field errors and complete over LAN HTTP", async ({
  page,
}) => {
  const errors: string[] = [];
  const outbound: string[] = [];
  let setupRequests = 0;
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["blob:", "data:"].includes(url.protocol) && url.origin !== origin)
      outbound.push(url.href);
    if (url.pathname === "/api/v1/setup/owner") setupRequests++;
  });
  await page.goto("/login");
  await expect(page).toHaveURL(origin + "/setup");
  await expect(
    page.getByRole("heading", { name: "Set up your local inventory" }),
  ).toBeVisible();
  await page.getByLabel("One-time setup token", { exact: true }).fill("short");
  await page.getByLabel("Username", { exact: true }).fill("owner@example.test");
  await page.getByLabel("Display name", { exact: true }).fill("   ");
  await page.getByLabel("Password", { exact: true }).fill("short");
  await page
    .getByRole("button", { name: "Create owner account", exact: true })
    .click();
  for (const label of [
    "One-time setup token",
    "Username",
    "Display name",
    "Password",
  ]) {
    const input = page.getByLabel(label, { exact: true });
    await expect(input).toHaveAttribute("aria-invalid", "true");
    expect(await input.getAttribute("aria-describedby")).toContain("-error");
  }
  await expect(
    page.getByLabel("One-time setup token", { exact: true }),
  ).toBeFocused();
  await expect(
    page.getByText(
      "Paste the complete one-time setup token (43–256 characters), not your password.",
      { exact: true },
    ),
  ).toBeVisible();
  expect(setupRequests).toBe(0);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({
    path: "test-results-auth/visible-setup-errors.png",
    fullPage: true,
  });

  const testToken = "boxen-test-token-only-" + "x".repeat(32);
  const password = "  test-password-with-spaces  ";
  await page
    .getByLabel("One-time setup token", { exact: true })
    .fill(" " + testToken + " ");
  await page.getByLabel("Username", { exact: true }).fill(" owner-validation ");
  await page
    .getByLabel("Display name", { exact: true })
    .fill(" Validation Owner ");
  await page.getByLabel("Password", { exact: true }).fill(password);

  // Force an actual server header validation failure beyond client validation.
  await page.route(
    "**/api/v1/setup/owner",
    async (route) => {
      await route.continue({
        headers: {
          ...route.request().headers(),
          "x-boxen-setup-token": "short",
        },
      });
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Create owner account", exact: true })
    .click();
  await expect(
    page.getByLabel("One-time setup token", { exact: true }),
  ).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("alert")).toContainText("One-time setup token");
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue(
    password,
  );
  await expect(page.getByLabel("Username", { exact: true })).toHaveValue(
    " owner-validation ",
  );
  const stillSetup = await page.evaluate(() =>
    fetch("/api/v1/setup/status").then((r) => r.json()),
  );
  expect(stillSetup).toEqual({ setup_required: true });

  // Correct-length but wrong token remains a token error, never a phantom field.
  await page
    .getByLabel("One-time setup token", { exact: true })
    .fill("y".repeat(53));
  await page
    .getByRole("button", { name: "Create owner account", exact: true })
    .click();
  await expect(
    page.getByLabel("One-time setup token", { exact: true }),
  ).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("alert")).toContainText(
    "host setup token was not accepted",
  );

  await page
    .getByLabel("One-time setup token", { exact: true })
    .fill(" " + testToken + " ");
  await page
    .getByRole("button", { name: "Create owner account", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Find what you stored." }),
  ).toBeVisible();
  expect(
    await page.evaluate(() =>
      fetch("/api/v1/setup/status").then((r) => r.json()),
    ),
  ).toEqual({ setup_required: false });
  expect(
    await page.evaluate(() =>
      fetch("/api/v1/session")
        .then((r) => r.json())
        .then((s) => ({
          role: s.user.role,
          anonymous: s.anonymous,
          username: s.user.username,
        })),
    ),
  ).toEqual({ role: "owner", anonymous: false, username: "owner-validation" });

  // Log out through the real session boundary, then exercise login validation.
  expect(
    await page.evaluate(async () => {
      const session = await fetch("/api/v1/session").then((r) => r.json());
      return (
        await fetch("/api/v1/auth/logout", {
          method: "POST",
          headers: { "X-CSRF-Token": session.csrf_token },
        })
      ).status;
    }),
  ).toBe(204);
  await page.goto("/setup");
  await expect(page).toHaveURL(origin + "/login");
  await page.getByLabel("Username", { exact: true }).fill("ow");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByLabel("Username", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(page.getByLabel("Password", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true",
  );

  await page.getByLabel("Username", { exact: true }).fill("owner-validation");
  await page.getByLabel("Password", { exact: true }).fill("incorrect-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Sign-in details were not accepted",
  );
  await expect(page.getByLabel("Username", { exact: true })).toHaveValue(
    "owner-validation",
  );

  // Direct input values model password-manager autofill without change events.
  await page
    .getByLabel("Username", { exact: true })
    .evaluate((input: HTMLInputElement) => {
      input.value = " owner-validation ";
    });
  await page
    .getByLabel("Password", { exact: true })
    .evaluate((input: HTMLInputElement, password) => {
      input.value = password;
    }, password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Find what you stored." }),
  ).toBeVisible();
  expect(
    await page.evaluate(() =>
      fetch("/api/v1/session")
        .then((r) => r.json())
        .then((s) => s.user.role),
    ),
  ).toBe("owner");
  expect(errors).toEqual([]);
  expect(outbound).toEqual([]);
});
