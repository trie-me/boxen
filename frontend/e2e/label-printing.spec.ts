import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFile } from "node:fs/promises";
const origin = "http://boxen.test:8174";
test.skip(
  ({ baseURL }) => baseURL !== origin,
  "Use playwright.labels.config.ts",
);

async function mutate(page: Page, path: string, body?: unknown, etag?: string) {
  return page.evaluate(
    async ({ path, body, etag }) => {
      const session = await fetch("/api/v1/session").then((r) => r.json());
      const response = await fetch("/api/v1" + path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": session.csrf_token,
          "Idempotency-Key": Array.from(
            crypto.getRandomValues(new Uint8Array(16)),
            (n) => n.toString(16).padStart(2, "0"),
          ).join(""),
          ...(etag ? { "If-Match": etag } : {}),
        },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await response.text());
      return {
        body: response.status === 204 ? null : await response.json(),
        etag: response.headers.get("etag"),
      };
    },
    { path, body, etag },
  );
}

for (const width of [1280, 375]) {
  test(`pin list and collection produce a paginated printable PDF at ${width}px`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Find what you stored." }),
    ).toBeVisible();
    const a = (await mutate(page, "/boxes", { name: `Print camping ${width}` }))
      .body;
    const b = (
      await mutate(page, "/boxes", { name: `Print workshop ${width}` })
    ).body;
    const collection = (
      await mutate(page, "/collections", {
        name: `Print collection ${width}`,
        box_codes: [b.code, a.code],
      })
    ).body;
    await page.goto("/boxes");
    await page.getByLabel("Pin label for " + a.name, { exact: true }).check();
    await page.getByLabel("Pin label for " + b.name, { exact: true }).check();
    await page
      .getByRole("link", { name: "Print list (2)", exact: true })
      .first()
      .click();
    await expect(
      page.getByRole("heading", { name: "2 labels", exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole("heading", { name: "2 labels", exact: true }),
    ).toBeVisible();
    await page.getByLabel("First label position").selectOption("10");
    await expect(
      page.getByText("2 labels · 2 sheets", { exact: true }),
    ).toBeVisible();
    const request = page.waitForRequest((r) =>
      r.url().endsWith("/api/v1/labels.pdf"),
    );
    await page.getByRole("button", { name: "Prepare printable PDF" }).click();
    expect((await request).postDataJSON()).toMatchObject({
      box_codes: [a.code, b.code],
      start_position: 10,
    });
    await expect(page.getByText("Page 1 of 2", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Next page", exact: true }),
    ).toBeEnabled();
    await page.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(page.getByText("Page 2 of 2", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Previous page", exact: true }),
    ).toBeEnabled();
    const download = page.waitForEvent("download");
    await page.getByRole("link", { name: "Download PDF", exact: true }).click();
    const downloaded = await download;
    expect(downloaded.suggestedFilename()).toBe("boxen-labels-letter.pdf");
    expect(
      (await readFile((await downloaded.path())!)).subarray(0, 5).toString(),
    ).toBe("%PDF-");
    expect(
      (
        await new AxeBuilder({ page })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results-labels/print-list-${width}.png`,
      fullPage: true,
    });
    await page.getByLabel("First label position").selectOption("1");
    await expect(
      page.getByRole("link", { name: "Download PDF", exact: true }),
    ).toHaveCount(0);
    await page
      .getByRole("button", {
        name: "Remove " + a.name + " from print list",
        exact: true,
      })
      .click();
    await expect(
      page.getByRole("heading", { name: "1 label", exact: true }),
    ).toBeVisible();
    await page.goto("/collections/" + collection.id);
    await page
      .getByRole("link", { name: "Print collection labels", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "2 labels", exact: true }),
    ).toBeVisible();
    const collectionRequest = page.waitForRequest((r) =>
      r.url().endsWith("/api/v1/labels.pdf"),
    );
    await page.getByRole("button", { name: "Prepare printable PDF" }).click();
    expect((await collectionRequest).postDataJSON()).toMatchObject({
      collection_id: collection.id,
      start_position: 1,
    });
    await expect(
      page.getByRole("link", { name: "Download PDF", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Rendering the printable label…", { exact: true }),
    ).toHaveCount(0);
    await page.goto("/print-list");
    await page
      .getByRole("button", { name: "Clear print list", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Your print list is empty" }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test("empty collections and a failed PDF request preserve the list for retry", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Find what you stored." }),
  ).toBeVisible();
  const group = (
    await mutate(page, "/collections", { name: "Empty print collection" })
  ).body;
  await page.goto("/collections/" + group.id + "/labels");
  await expect(
    page.getByRole("heading", { name: "This collection has no labels" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Prepare printable PDF" }),
  ).toHaveCount(0);
  const box = (await mutate(page, "/boxes", { name: "Print retry" })).body;
  await page.goto("/boxes/" + box.code);
  await page.getByLabel("Pin label for Print retry", { exact: true }).check();
  await page.goto("/print-list");
  await page.route("**/api/v1/labels.pdf", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/problem+json",
      body: JSON.stringify({
        code: "host.unavailable",
        detail: "Try this print again.",
      }),
    }),
  );
  await page.getByRole("button", { name: "Prepare printable PDF" }).click();
  await expect(
    page.getByText("Try this print again.", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "1 label", exact: true }),
  ).toBeVisible();
  await page.unroute("**/api/v1/labels.pdf");
  await page.getByRole("button", { name: "Prepare printable PDF" }).click();
  await expect(
    page.getByRole("link", { name: "Download PDF", exact: true }),
  ).toBeVisible();
});
