import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username", { exact: true }).fill("owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-only-long-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Find what you stored." }),
  ).toBeVisible();
}

test("expired authentication keeps the form mounted and allows saving after sign-in", async ({
  page,
  context,
}) => {
  await login(page);
  await page.goto("/boxes/new");
  await page.getByLabel("Box name").fill("Preserved draft");
  await page
    .getByLabel("Description", { exact: true })
    .fill("## Still here\nDo not lose this note.");
  await context.clearCookies();
  await page.getByRole("button", { name: "Create box", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Sign in and continue" }).click();
  await expect(dialog.getByLabel("Password", { exact: true })).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(
    dialog.getByText("Enter your password.", { exact: true }),
  ).toBeVisible();
  await dialog
    .getByLabel("Password", { exact: true })
    .fill("test-only-long-passphrase");
  await dialog.getByRole("button", { name: "Sign in and continue" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByLabel("Box name")).toHaveValue("Preserved draft");
  await expect(page.getByLabel("Description", { exact: true })).toHaveValue(
    "## Still here\nDo not lose this note.",
  );
  await page.getByRole("button", { name: "Create box", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Preserved draft", exact: true }),
  ).toBeVisible();
});

test("concurrent edits do not silently overwrite newer server content", async ({
  page,
}) => {
  await login(page);
  await page.goto("/boxes/new");
  await page.getByLabel("Box name").fill("Conflict fixture");
  await page.getByRole("button", { name: "Create box", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Conflict fixture", exact: true }),
  ).toBeVisible();
  const code = page.url().split("/").at(-1)!;
  await page.getByRole("link", { name: "Edit box", exact: true }).click();
  await page.getByLabel("Box name").fill("My unsaved change");
  const status = await page.evaluate(async (code) => {
    const session = await fetch("/api/v1/session").then((r) => r.json());
    const box = await fetch("/api/v1/boxes/" + code).then((r) => r.json());
    const result = await fetch("/api/v1/boxes/" + code, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": session.csrf_token,
        "Idempotency-Key": crypto.randomUUID(),
        "If-Match": `"box:${code}:v${box.version}"`,
      },
      body: JSON.stringify({ name: "Saved by another editor" }),
    });
    // Exercise background refresh while the local draft remains open.
    window.dispatchEvent(new Event("focus"));
    return result.status;
  }, code);
  expect(status).toBe(200);
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "The server has a newer version" }),
  ).toBeVisible();
  await expect(page.getByLabel("Box name")).toHaveValue("My unsaved change");
  await expect(
    page.getByRole("heading", { name: "Saved by another editor" }),
  ).toBeVisible();
});

test("camera permission denial has an accessible manual fallback", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
      value: async () => {
        throw new DOMException("Test denial", "NotAllowedError");
      },
    });
  });
  await login(page);
  await page.goto("/scan");
  await page.getByRole("tab", { name: "Live camera" }).click();
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(
    page.getByText(/Camera access was blocked by your browser or phone/),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Type code" }).click();
  await expect(page.getByLabel("Printed box code")).toBeVisible();
});

test("camera tracks close on navigation and when permission resolves after leaving", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const fixture = window as unknown as {
      cameraStreams: MediaStream[];
      releaseCamera?: () => void;
      delayCamera: boolean;
    };
    fixture.cameraStreams = [];
    fixture.delayCamera = false;
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", {
      value: async () => {
        const canvas = document.createElement("canvas");
        canvas.width = 320;
        canvas.height = 240;
        canvas.getContext("2d")!.fillRect(0, 0, 320, 240);
        const stream = canvas.captureStream(5);
        fixture.cameraStreams.push(stream);
        if (fixture.delayCamera)
          await new Promise<void>(
            (resolve) => (fixture.releaseCamera = resolve),
          );
        return stream;
      },
    });
  });
  await login(page);
  await page.goto("/scan");
  await page.getByRole("tab", { name: "Live camera" }).click();
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.getByRole("button", { name: "Stop camera" })).toBeVisible();
  await page.getByRole("tab", { name: "Type code" }).click();
  await expect
    .poll(() =>
      page.evaluate(() =>
        (
          window as unknown as { cameraStreams: MediaStream[] }
        ).cameraStreams.every((s) =>
          s.getTracks().every((t) => t.readyState === "ended"),
        ),
      ),
    )
    .toBe(true);
  await page.evaluate(() => {
    (window as unknown as { delayCamera: boolean }).delayCamera = true;
  });
  await page.getByRole("tab", { name: "Live camera" }).click();
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(
    page.getByRole("button", { name: "Opening camera…" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Type code" }).click();
  await page.evaluate(() =>
    (window as unknown as { releaseCamera: () => void }).releaseCamera(),
  );
  await expect
    .poll(() =>
      page.evaluate(() =>
        (
          window as unknown as { cameraStreams: MediaStream[] }
        ).cameraStreams.every((s) =>
          s.getTracks().every((t) => t.readyState === "ended"),
        ),
      ),
    )
    .toBe(true);
});

test("main phone screens have no automated WCAG AA violations or horizontal overflow", async ({
  page,
}) => {
  await login(page);
  await page.setViewportSize({ width: 375, height: 812 });
  for (const route of [
    "/",
    "/boxes",
    "/boxes/new",
    "/scan",
    "/review",
    "/account",
    "/system",
    "/system/users",
    "/system/backups",
    "/system/maintenance",
  ]) {
    await page.goto(route);
    await expect(page.locator("main h1")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      route,
    ).toBe(true);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(results.violations, route).toEqual([]);
  }
});
