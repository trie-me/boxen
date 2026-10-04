import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import type { Schema } from "../src/api";

test("box browsing downloads thumbnails; opening a photo fetches its larger view", async ({
  page,
  context,
  baseURL,
}) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 375, height: 700 });
  const headers = { Origin: baseURL! };
  const login = await page.request.post("/api/v1/auth/login", {
    headers,
    data: { username: "owner", password: "test-only-long-passphrase" },
  });
  expect(login.status()).toBe(200);
  const writeHeaders = {
    ...headers,
    "X-CSRF-Token": (await login.json()).csrf_token,
  };
  const name = `Thumbnail fixture ${randomUUID()}`;
  const created = await page.request.post("/api/v1/boxes", {
    headers: { ...writeHeaders, "Idempotency-Key": randomUUID() },
    data: { name },
  });
  expect(created.status()).toBe(201);
  const box: Schema<"BoxDetail"> = await created.json();
  const fixtures: string[] = JSON.parse(
    execFileSync(
      "../.venv/bin/python",
      [
        "-c",
        `import base64, io, json
from PIL import Image
photos = []
for index in range(20):
    image = Image.new("RGB", (2400, 1600), (30 + index * 10, 140, 160))
    output = io.BytesIO()
    image.save(output, "JPEG", quality=95)
    photos.append(base64.b64encode(output.getvalue()).decode())
print(json.dumps(photos))`,
      ],
      { maxBuffer: 4 * 1024 * 1024 },
    ).toString(),
  );
  const photos: Schema<"ImageView">[] = [];
  for (const [index, fixture] of fixtures.entries()) {
    const uploaded = await page.request.post(
      `/api/v1/boxes/${box.code}/images`,
      {
        headers: { ...writeHeaders, "Idempotency-Key": randomUUID() },
        multipart: {
          caption: `Thumbnail photo ${index + 1}`,
          file: {
            name: `photo-${index}.jpg`,
            mimeType: "image/jpeg",
            buffer: Buffer.from(fixture, "base64"),
          },
        },
      },
    );
    expect(uploaded.status()).toBe(201);
    photos.push(await uploaded.json());
  }
  const requests: URL[] = [];
  // Listen at context level so requests in the opened photo tab count too.
  context.on("request", (request) => {
    const url = new URL(request.url());
    if (/\/api\/v1\/images\/[^/]+\/content$/.test(url.pathname))
      requests.push(url);
  });

  await page.goto(`/boxes/${box.code}`);
  const tiles = page.locator(".photo-tile");
  await expect(tiles).toHaveCount(20);
  await tiles.first().scrollIntoViewIfNeeded();
  const firstImage = tiles.first().locator("img");
  await expect
    .poll(() =>
      firstImage.evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBe(480);
  expect(requests.length).toBeGreaterThan(0);
  // Photos far below the viewport must not all be downloaded upfront.
  expect(new Set(requests.map(String)).size).toBeLessThan(20);
  expect(
    requests.every((url) => url.searchParams.get("variant") === "thumbnail"),
  ).toBe(true);

  for (const tile of await tiles.all()) {
    await tile.scrollIntoViewIfNeeded();
    await expect
      .poll(() =>
        tile
          .locator("img")
          .evaluate((img: HTMLImageElement) => img.naturalWidth),
      )
      .toBe(480);
  }
  expect(new Set(requests.map(String)).size).toBe(20);
  expect(
    requests.every((url) => url.searchParams.get("variant") === "thumbnail"),
  ).toBe(true);

  await page.goto("/");
  const cardImage = page.locator(`.box-card a[href="/boxes/${box.code}"] img`);
  await cardImage.scrollIntoViewIfNeeded();
  await expect
    .poll(() => cardImage.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBe(480);
  await page.goto(`/search?q=${encodeURIComponent(name)}`);
  const searchImage = page.locator(
    `.search-result a[href="/boxes/${box.code}"] img`,
  );
  await expect(searchImage).toHaveAttribute("loading", "lazy");
  await expect
    .poll(() =>
      searchImage.evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBe(480);
  expect(
    requests.every((url) => url.searchParams.get("variant") === "thumbnail"),
  ).toBe(true);

  await page.goto(`/boxes/${box.code}`);
  const popupPromise = context.waitForEvent("page");
  await page.locator(".photo-tile").first().locator("a").click();
  const popup = await popupPromise;
  await popup.waitForLoadState();
  expect(popup.url()).toBe(new URL(photos[0].display_url!, baseURL).href);
  const largerRequests = requests.filter(
    (url) => url.searchParams.get("variant") !== "thumbnail",
  );
  expect(largerRequests.map(String)).toEqual([popup.url()]);
  await expect
    .poll(() =>
      popup
        .locator("img")
        .evaluate((img: HTMLImageElement) => img.naturalWidth),
    )
    .toBe(2048);
  await popup.close();
});
