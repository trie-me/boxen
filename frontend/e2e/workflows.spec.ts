import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";

test("local inventory: login, create, edit, find, label and responsive navigation", async ({
  page,
}) => {
  const outbound: string[] = [];
  page.on("request", (r) => {
    if (
      !r.url().startsWith("http://127.0.0.1:8173") &&
      !r.url().startsWith("blob:") &&
      !r.url().startsWith("data:")
    )
      outbound.push(r.url());
  });
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "Welcome back." }),
  ).toBeVisible();
  await page.getByLabel("Username", { exact: true }).fill("owner");
  await page
    .getByLabel("Password", { exact: true })
    .fill("test-only-long-passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Find what you stored." }),
  ).toBeVisible();
  await page.getByRole("link", { name: "New box", exact: true }).click();
  await page.getByLabel("Box name").fill("Workshop · Cables");
  await page
    .getByLabel("Description", { exact: true })
    .fill("## Spare parts\nBlue **cables**, adapters, and small tools.");
  await page.getByRole("button", { name: "Create box", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Workshop · Cables", exact: true }),
  ).toBeVisible();
  const boxURL = page.url();
  const code = boxURL.split("/").at(-1)!;
  await page.getByRole("button", { name: "Add item", exact: true }).click();
  await page.getByLabel("Item name", { exact: true }).fill("USB-C adapter");
  await page.getByLabel("Quantity", { exact: true }).fill("3");
  await page.getByLabel("Unit", { exact: true }).fill("pieces");
  await page.getByRole("button", { name: "Save item" }).click();
  await expect(
    page.getByRole("heading", { name: "USB-C adapter" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Edit box", exact: true }).click();
  await page.getByLabel("Box name").fill("Workshop · Electronics");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Workshop · Electronics", exact: true }),
  ).toBeVisible();
  await page.goto("/search?q=adapter");
  await expect(
    page.getByRole("heading", { name: "Workshop · Electronics", exact: true }),
  ).toBeVisible();
  await page.goto("/scan");
  await page.getByLabel("Printed box code").fill(code);
  await page.getByRole("button", { name: "Find box", exact: true }).click();
  await expect(page).toHaveURL(boxURL);
  const photo = execFileSync("../.venv/bin/python", [
    "-c",
    'from PIL import Image; import sys; Image.new("RGB",(80,60),(20,140,160)).save(sys.stdout.buffer,"PNG")',
  ]);
  await page.getByLabel("Choose files").setInputFiles({
    name: "inventory.png",
    mimeType: "image/png",
    buffer: photo,
  });
  await page
    .getByLabel("Caption", { exact: true })
    .fill("Top layer of cable tray");
  await page.getByRole("button", { name: "Upload / retry photos" }).click();
  await expect(page.getByText("Uploaded", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Dismiss", exact: true }).click();
  await expect(page.getByAltText("Top layer of cable tray")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Analyze", exact: true }),
  ).toBeDisabled();
  const qr = execFileSync("../.venv/bin/python", [
    "-c",
    'import segno,sys; segno.make_qr(sys.argv[1],error="q").save(sys.stdout.buffer,kind="png",scale=8,border=4)',
    "boxen:v1:" + code,
  ]);
  await page.goto("/scan");
  await page.getByRole("tab", { name: "Upload QR image" }).click();
  await page
    .locator("input[type=file]")
    .setInputFiles({ name: "label.png", mimeType: "image/png", buffer: qr });
  await expect(page).toHaveURL(boxURL);
  await page.getByRole("link", { name: "Print label", exact: true }).click();
  await expect(page.getByText("Rendering the printable label…")).toHaveCount(0);
  await expect
    .poll(() =>
      page
        .locator(".pdf-preview canvas")
        .evaluate((canvas: HTMLCanvasElement) => canvas.width),
    )
    .toBeGreaterThan(100);
  await page.screenshot({
    path: "test-results/label-preview.png",
    fullPage: true,
  });
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download PDF", exact: true }).click();
  expect((await download).suggestedFilename()).toContain(code);
  for (const width of [320, 375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Find what you stored." }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `test-results/home-${width}.png`,
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(boxURL);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "test-results/box-phone.png", fullPage: true });
  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  expect(accessibility.violations).toEqual([]);
  expect(outbound).toEqual([]);
});
