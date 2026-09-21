import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";

const origin = "http://boxen.test:8174";
const outbound: string[] = [];
const browserErrors: string[] = [];

// The existing configuration deliberately tests anonymous viewer access. This
// suite has its own default-editor fixture and a genuinely insecure HTTP origin.
test.skip(
  ({ baseURL }) => baseURL !== origin,
  "Run with playwright.lan.config.ts",
);

test.beforeEach(async ({ page }) => {
  outbound.length = 0;
  browserErrors.length = 0;
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["blob:", "data:"].includes(url.protocol) && url.origin !== origin)
      outbound.push(request.url());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Find what you stored." }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => ({
      origin: location.origin,
      secure: window.isSecureContext,
      subtle: typeof crypto.subtle,
      uuid: typeof crypto.randomUUID,
      random: typeof crypto.getRandomValues,
      camera: typeof navigator.mediaDevices,
    })),
  ).toEqual({
    origin,
    secure: false,
    subtle: "undefined",
    uuid: "undefined",
    random: "function",
    camera: "undefined",
  });
  const session = await page.evaluate(() =>
    fetch("/api/v1/session").then((response) => response.json()),
  );
  expect(session.anonymous).toBe(true);
  expect(session.user.role).toBe("editor");
  expect(
    await page.evaluate(() =>
      fetch("/api/v1/setup/status").then((response) => response.json()),
    ),
  ).toEqual({ setup_required: true });
});

test.afterEach(() => {
  expect(browserErrors).toEqual([]);
  expect(outbound).toEqual([]);
});

async function createBox(page: Page, name: string) {
  await page.getByRole("link", { name: "New box", exact: true }).click();
  await page.getByLabel("Box name").fill(name);
  await page.getByRole("button", { name: "Create box", exact: true }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  return { url: page.url(), code: page.url().split("/").at(-1)! };
}

test("anonymous editor can create, edit, search, upload photos and render labels over HTTP", async ({
  page,
}) => {
  const { code } = await createBox(page, "HTTP cable shelf");
  await page.getByRole("button", { name: "Add item", exact: true }).click();
  await page.getByLabel("Item name", { exact: true }).fill("LAN adapter");
  await page.getByLabel("Quantity", { exact: true }).fill("3");
  await page.getByRole("button", { name: "Save item" }).click();
  await expect(
    page.getByRole("heading", { name: "LAN adapter 3", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Edit box", exact: true }).click();
  await page.getByLabel("Box name").fill("HTTP network shelf");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "HTTP network shelf", exact: true }),
  ).toBeVisible();
  await page.goto("/search?q=adapter");
  await expect(
    page.getByRole("heading", { name: "HTTP network shelf", exact: true }),
  ).toBeVisible();
  await page.goto("/boxes/" + code);
  await page.getByRole("button", { name: "Copy code", exact: true }).click();
  await expect(
    page.getByText("Code selected. Use your device’s Copy command."),
  ).toBeVisible();
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe(
    code,
  );
  const photo = execFileSync("../.venv/bin/python", [
    "-c",
    'from PIL import Image; import sys; Image.new("RGB",(80,60),(20,140,160)).save(sys.stdout.buffer,"PNG")',
  ]);
  await page.getByLabel("Choose files").setInputFiles({
    name: "http-photo.png",
    mimeType: "image/png",
    buffer: photo,
  });
  await page.getByLabel("Caption", { exact: true }).fill("Network cables");
  await page.getByRole("button", { name: "Upload / retry photos" }).click();
  await expect(page.getByText("Uploaded", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Dismiss", exact: true }).click();
  await expect(page.getByAltText("Network cables")).toBeVisible();
  await page.getByRole("link", { name: "Print label", exact: true }).click();
  await expect
    .poll(() =>
      page
        .locator(".pdf-preview canvas")
        .evaluate((canvas: HTMLCanvasElement) => canvas.width),
    )
    .toBeGreaterThan(100);
  await expect(page.getByText("Rendering the printable label…")).toHaveCount(0);
  // A canvas size alone passes even if embedded label text disappears. Check
  // name glyphs in the upper-right text area, separate from the QR and code.
  expect(
    await page
      .locator(".pdf-preview canvas")
      .evaluate((canvas: HTMLCanvasElement) => {
        const pixels = canvas
          .getContext("2d")!
          .getImageData(
            Math.round(canvas.width * 0.47),
            0,
            Math.round(canvas.width * 0.48),
            Math.round(canvas.height * 0.45),
          ).data;
        let ink = 0;
        for (let i = 0; i < pixels.length; i += 4)
          if (
            pixels[i] < 80 &&
            pixels[i + 1] < 80 &&
            pixels[i + 2] < 80 &&
            pixels[i + 3] > 200
          )
            ink++;
        return ink;
      }),
  ).toBeGreaterThan(100);
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download PDF", exact: true }).click();
  const label = await download;
  expect(label.suggestedFilename()).toContain(code);
  const text = execFileSync(
    "../.venv/bin/python",
    [
      "-c",
      "from pypdf import PdfReader; import sys; print(PdfReader(sys.argv[1]).pages[0].extract_text())",
      (await label.path())!,
    ],
    { encoding: "utf8" },
  );
  expect(text.replace(/\s+/g, " ")).toContain("HTTP network shelf");
  expect(text).toContain(code);
});

test("HTTP camera limitation offers working type and local QR-image alternatives with unchanged checksums", async ({
  page,
}) => {
  const { url, code } = await createBox(page, "HTTP scan fixture");
  await page.goto("/scan");
  await page.getByRole("tab", { name: "Live camera" }).click();
  await expect(page.getByRole("note")).toHaveText(
    "Live camera scanning requires HTTPS on your local network. Upload a QR image or type the printed code; both work over HTTP.",
  );
  await expect(
    page.getByRole("button", { name: "Start camera" }),
  ).toBeDisabled();
  await page.getByRole("tab", { name: "Type code" }).click();
  let lookups = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/v1/codes/resolve")) lookups += 1;
  });
  await page
    .getByLabel("Printed box code")
    .fill(code.slice(0, -1) + (code.endsWith("0") ? "1" : "0"));
  await page.getByRole("button", { name: "Find box", exact: true }).click();
  await expect(
    page.getByText(
      "The check character does not match. Check the printed code.",
    ),
  ).toBeVisible();
  expect(lookups).toBe(0);
  await page.getByLabel("Printed box code").fill(code.toLowerCase());
  await page.getByRole("button", { name: "Find box", exact: true }).click();
  await expect(page).toHaveURL(url);
  expect(lookups).toBe(1);

  for (const payload of ["boxen:v1:" + code, url]) {
    const qr = execFileSync("../.venv/bin/python", [
      "-c",
      'import segno,sys; segno.make_qr(sys.argv[1],error="q").save(sys.stdout.buffer,kind="png",scale=8,border=4)',
      payload,
    ]);
    await page.goto("/scan");
    await page.getByRole("tab", { name: "Upload QR image" }).click();
    await page
      .locator("input[type=file]")
      .setInputFiles({ name: "label.png", mimeType: "image/png", buffer: qr });
    await expect(page).toHaveURL(url);
  }
  expect(lookups).toBe(3);
  // Fixed regression: this valid symbol mask defeats the general photographic
  // finder, but must decode using the upload-only pure-symbol fallback.
  const knownCode = "BX-SXSB-3DDA";
  const knownQr = execFileSync("../.venv/bin/python", [
    "-c",
    'import segno,sys; segno.make_qr(sys.argv[1],error="q").save(sys.stdout.buffer,kind="png",scale=8,border=4)',
    "boxen:v1:" + knownCode,
  ]);
  await page.goto("/scan");
  await page.getByRole("tab", { name: "Upload QR image" }).click();
  const resolved = page.waitForRequest((request) =>
    request.url().endsWith("/codes/resolve"),
  );
  await page.locator("input[type=file]").setInputFiles({
    name: "fixed-mask.png",
    mimeType: "image/png",
    buffer: knownQr,
  });
  expect((await resolved).postDataJSON().input).toBe(knownCode);
});

test("HTTP anonymous access keeps CSRF and administration protected before owner setup", async ({
  page,
}) => {
  await page.goto("/system/users");
  await expect(
    page.getByRole("button", { name: "Create user", exact: true }),
  ).toHaveCount(0);
  const statuses = await page.evaluate(async () => {
    const session = await fetch("/api/v1/session").then((response) =>
      response.json(),
    );
    return {
      users: (await fetch("/api/v1/users")).status,
      backups: (await fetch("/api/v1/backups")).status,
      missingCsrf: (
        await fetch("/api/v1/boxes", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": "http-test-no-csrf",
          },
          body: JSON.stringify({ name: "Must not save" }),
        })
      ).status,
      createUser: (
        await fetch("/api/v1/users", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": session.csrf_token,
            "Idempotency-Key": "http-test-not-admin",
          },
          body: JSON.stringify({
            username: "forbidden",
            display_name: "Forbidden",
            role: "owner",
            password: "test-only-long-passphrase",
          }),
        })
      ).status,
    };
  });
  expect(statuses).toEqual({
    users: 403,
    backups: 403,
    missingCsrf: 403,
    createUser: 403,
  });
  const session = await page.evaluate(() =>
    fetch("/api/v1/session").then((response) => response.json()),
  );
  expect(session.anonymous).toBe(true);
  expect(session.user.role).toBe("editor");
});

function collectionPhoto(name: string, color: [number, number, number]) {
  return {
    name,
    mimeType: "image/png",
    buffer: execFileSync("../.venv/bin/python", [
      "-c",
      'from PIL import Image; import sys; Image.new("RGB",(120,100),tuple(map(int,sys.argv[1:]))).save(sys.stdout.buffer,"PNG")',
      ...color.map(String),
    ]),
  };
}

async function uploadCollection(
  page: Page,
  photos: ReturnType<typeof collectionPhoto>[],
) {
  await page.getByLabel("Choose files").setInputFiles(photos);
  for (let i = 0; i < photos.length; i++) {
    await page
      .getByLabel("Caption", { exact: true })
      .nth(i)
      .fill(photos[i].name);
  }
  await page.getByRole("button", { name: "Upload / retry photos" }).click();
  await expect(page.getByText("Uploaded", { exact: true })).toHaveCount(
    photos.length,
  );
  for (const _photo of photos)
    await page
      .getByRole("button", { name: "Dismiss", exact: true })
      .first()
      .click();
}

test("chip acceptance retries a lost success response without creating duplicate items", async ({
  page,
}) => {
  const { code } = await createBox(page, "Retry chip set");
  await page.goto("/review?box=" + code);
  await page.getByLabel("Add an item", { exact: true }).fill("Extra charger");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const submissions: { key: string | undefined; body: unknown }[] = [];
  await page.route("**/observations/review", async (route) => {
    submissions.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postDataJSON(),
    });
    if (submissions.length === 1) {
      // route.fetch runs in Node, outside Chromium's local DNS override.
      const result = await route.fetch({
        url: route.request().url().replace("boxen.test", "127.0.0.1"),
        headers: { ...route.request().headers(), host: "boxen.test:8174" },
      });
      expect(result.status()).toBe(200);
      await route.abort("failed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Accept items", exact: true }).click();
  await expect(page.getByLabel("Add an item", { exact: true })).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Accept items", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Accept items", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Review complete", exact: true }),
  ).toBeVisible();
  expect(submissions).toHaveLength(2);
  expect(submissions[0].key).toBeTruthy();
  expect(submissions[1]).toEqual(submissions[0]);
  const box = await page.evaluate(
    (boxCode) => fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
    code,
  );
  expect(box.items).toHaveLength(1);
  expect(box.items[0]).toMatchObject({
    name: "Extra charger",
    quantity: null,
    provenance: "manual",
  });
});

test("removing every AI chip commits rejections only and manual additions can be accepted afterward", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { code } = await createBox(page, "Remove chip set");
  await uploadCollection(page, [
    collectionPhoto("Empty the draft", [90, 90, 90]),
  ]);
  await page
    .getByRole("button", { name: "Analyze all photos (1)", exact: true })
    .click();
  await expect(page.getByText(/1 of 1 photos analyzed/)).toBeVisible({
    timeout: 20_000,
  });
  await page.goto("/review?box=" + code);
  await page
    .getByRole("button", { name: "Remove Adjustable wrench", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Edit Adjustable wrench", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Accept items", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Review complete", exact: true }),
  ).toBeVisible();
  const result = await page.evaluate(
    async (boxCode) => ({
      box: await fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
      observations: await fetch(
        `/api/v1/boxes/${boxCode}/observations?decision=all`,
      ).then((r) => r.json()),
    }),
    code,
  );
  expect(result.box.items).toEqual([]);
  expect(result.observations.items).toHaveLength(1);
  expect(result.observations.items[0].decision).toBe("rejected");
  await page
    .getByLabel("Add an item", { exact: true })
    .fill("Replacement filter");
  await page.getByLabel("Add an item", { exact: true }).press("Enter");
  await page.getByRole("button", { name: "Accept items", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Review complete", exact: true }),
  ).toBeVisible();
  const box = await page.evaluate(
    (boxCode) => fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
    code,
  );
  expect(box.items).toHaveLength(1);
  expect(box.items[0].name).toBe("Replacement filter");
});

test("anonymous photos contribute to one reviewed inventory without duplicate quantities", async ({
  page,
  browser,
}) => {
  test.setTimeout(90_000);
  const { code, url } = await createBox(page, "Collective contents");
  const photoStatus = (number: number) =>
    page
      .getByRole("article", { name: `Photo ${number}`, exact: true })
      .getByRole("status");
  const reviewed =
    "Analysis: succeeded · Complete. No suggestions left to review.";
  const pending =
    "Analysis: succeeded · Complete. 1 suggestion to review in the shared inventory.";
  await uploadCollection(page, [
    collectionPhoto("Items staged on a bench", [90, 90, 90]),
    collectionPhoto("Close-up of the same wrench", [30, 100, 190]),
    collectionPhoto("Reference view with no detections", [0, 240, 0]),
  ]);
  await expect(
    page.getByText(/the container does not need to appear/),
  ).toBeVisible();
  const submitted: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/analyses"))
      submitted.push(request.url());
  });
  await page
    .getByRole("button", { name: "Analyze all photos (3)", exact: true })
    .click();
  await expect(
    page.getByText(/Queue requests finished: 3\/3 checked · 3 queued/),
  ).toBeVisible();
  await expect(
    page
      .getByRole("button", { name: "Analysis in progress", exact: true })
      .first(),
  ).toBeDisabled();
  await expect(page.getByText(/3 of 3 photos analyzed/)).toBeVisible({
    timeout: 20_000,
  });
  expect(new Set(submitted).size).toBe(3);
  expect(submitted).toHaveLength(3);
  const initial = await page.evaluate(
    (boxCode) => fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
    code,
  );
  expect(initial.items).toEqual([]);
  expect(initial.pending_observation_count).toBe(2);
  await expect(photoStatus(1)).toHaveText(pending);
  await expect(photoStatus(2)).toHaveText(pending);
  await expect(photoStatus(3)).toHaveText(reviewed);
  const jobIds = initial.images.map(
    (image: { latest_analysis: { id: string; state: string } }) => {
      expect(image.latest_analysis.state).toBe("succeeded");
      return image.latest_analysis.id;
    },
  );

  // State comes from the server, not browser memory: another anonymous browser
  // must also skip all three, including the successful zero-observation photo.
  const other = await browser.newContext({ baseURL: origin });
  try {
    const anotherPage = await other.newPage();
    await anotherPage.goto(url);
    await expect(anotherPage.getByText(/3 of 3 photos analyzed/)).toBeVisible();
    await expect(
      anotherPage.getByRole("button", { name: "Analyze remaining photos (0)" }),
    ).toBeDisabled();
  } finally {
    await other.close();
  }
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Analyze remaining photos (0)" }),
  ).toBeDisabled();
  await page
    .getByRole("link", { name: "Review all photo suggestions", exact: true })
    .click();
  const chips = page.getByRole("button", {
    name: "Edit Adjustable wrench",
    exact: true,
  });
  await expect(chips).toHaveCount(2);
  await page
    .getByRole("button", { name: "Remove Adjustable wrench", exact: true })
    .last()
    .click();
  await expect(chips).toHaveCount(1);
  await page.getByLabel("Add an item", { exact: true }).fill("Work gloves");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Edit Work gloves", exact: true }),
  ).toBeVisible();
  // Neither removal nor addition writes anything before the set is accepted.
  const draft = await page.evaluate(
    (boxCode) => fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
    code,
  );
  expect(draft.items).toEqual([]);
  expect(draft.pending_observation_count).toBe(2);
  await page.waitForResponse(
    (r) => r.url().includes("/observations?") && r.request().method() === "GET",
  );
  await expect(chips).toHaveCount(1);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page.screenshot({
    path: "test-results-lan/collective-review-phone.png",
    fullPage: true,
  });
  const decision = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/observations/review"),
  );
  await page.getByRole("button", { name: "Accept items", exact: true }).click();
  const body = (await decision).postDataJSON();
  expect(body.accept).toHaveLength(1);
  expect(body.reject).toHaveLength(1);
  expect(body.add).toHaveLength(1);
  await expect(
    page.getByRole("heading", { name: "Review complete", exact: true }),
  ).toBeVisible();
  const result = await page.evaluate(
    async (boxCode) => ({
      box: await fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
      observations: await fetch(
        `/api/v1/boxes/${boxCode}/observations?decision=all`,
      ).then((r) => r.json()),
    }),
    code,
  );
  expect(result.box.items).toHaveLength(2);
  const wrench = result.box.items.find(
    (item: { name: string }) => item.name === "Adjustable wrench",
  );
  expect(wrench).toMatchObject({
    name: "Adjustable wrench",
    quantity: "1",
    unit: "piece",
  });
  expect(
    result.box.items.find(
      (item: { name: string }) => item.name === "Work gloves",
    ),
  ).toMatchObject({
    name: "Work gloves",
    quantity: null,
    provenance: "manual",
  });
  expect(result.observations.items).toHaveLength(2);
  expect(
    result.observations.items.filter(
      (o: { decision: string }) => o.decision === "accepted",
    ),
  ).toHaveLength(1);
  expect(
    result.observations.items.filter(
      (o: { decision: string }) => o.decision === "rejected",
    ),
  ).toHaveLength(1);

  // A newly added photo is the only eligible request; the existing successful
  // jobs must stay unchanged even after reviewing their observations.
  await page.goto(url);
  for (const number of [1, 2, 3])
    await expect(photoStatus(number)).toHaveText(reviewed);
  await expect(
    page.getByRole("link", {
      name: "Review all photo suggestions",
      exact: true,
    }),
  ).toHaveCount(0);
  await uploadCollection(page, [
    collectionPhoto("Additional contents", [150, 130, 50]),
  ]);
  await page
    .getByRole("button", { name: "Analyze remaining photos (1)", exact: true })
    .click();
  await expect(page.getByText(/4 of 4 photos analyzed/)).toBeVisible({
    timeout: 20_000,
  });
  expect(submitted).toHaveLength(4);
  for (const number of [1, 2, 3])
    await expect(photoStatus(number)).toHaveText(reviewed);
  await expect(photoStatus(4)).toHaveText(pending);
  const updated = await page.evaluate(
    (boxCode) => fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
    code,
  );
  expect(
    updated.images
      .slice(0, 3)
      .map(
        (image: { latest_analysis: { id: string } }) =>
          image.latest_analysis.id,
      ),
  ).toEqual(jobIds);
  await page.goto("/review?box=" + code);
  await page
    .getByRole("button", { name: "Edit Adjustable wrench", exact: true })
    .click();
  await page
    .getByLabel("How to keep this item", { exact: true })
    .selectOption("merge");
  await expect(
    page.getByRole("button", { name: "Save changes", exact: true }),
  ).toBeDisabled();
  await page
    .getByLabel("Confirmed item", { exact: true })
    .selectOption(wrench.id);
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  const linkedRequest = page.waitForRequest(
    (request) =>
      request.method() === "POST" &&
      request.url().endsWith("/observations/review"),
  );
  await page.getByRole("button", { name: "Accept items", exact: true }).click();
  const linkedBody = (await linkedRequest).postDataJSON();
  expect(linkedBody.accept[0].decision).toMatchObject({
    mode: "merge",
    item_id: wrench.id,
  });
  expect(linkedBody.accept[0].decision.item_patch).toBeUndefined();
  await expect(
    page.getByRole("heading", { name: "Review complete", exact: true }),
  ).toBeVisible();
  const linkedBox = await page.evaluate(
    (boxCode) => fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
    code,
  );
  expect(linkedBox.items).toHaveLength(2);
  expect(
    linkedBox.items.find((item: { id: string }) => item.id === wrench.id)
      .quantity,
  ).toBe("1");
  await page.goto(url);
  const firstPhoto = page.getByRole("article", {
    name: "Photo 1",
    exact: true,
  });
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("duplicate pending evidence");
    await dialog.dismiss();
  });
  await firstPhoto
    .getByRole("button", { name: "Analyze again", exact: true })
    .click();
  expect(submitted).toHaveLength(4);
  page.once("dialog", (dialog) => dialog.accept());
  await firstPhoto
    .getByRole("button", { name: "Analyze again", exact: true })
    .click();
  await expect(
    firstPhoto.getByRole("button", {
      name: "Analysis in progress",
      exact: true,
    }),
  ).toBeDisabled();
  await expect(
    firstPhoto.getByRole("button", { name: "Analyze again", exact: true }),
  ).toBeEnabled({ timeout: 20_000 });
  expect(submitted).toHaveLength(5);
  const repeated = await page.evaluate(
    (boxCode) => fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
    code,
  );
  expect(repeated.images[0].latest_analysis.id).not.toBe(jobIds[0]);
  expect(
    repeated.images
      .slice(1, 3)
      .map(
        (image: { latest_analysis: { id: string } }) =>
          image.latest_analysis.id,
      ),
  ).toEqual(jobIds.slice(1));
  expect(repeated.items).toHaveLength(2);
  expect(
    repeated.items.find((item: { id: string }) => item.id === wrench.id)
      .quantity,
  ).toBe("1");
  expect(repeated.pending_observation_count).toBe(1);
  await expect(photoStatus(1)).toHaveText(pending);
  for (const number of [2, 3, 4])
    await expect(photoStatus(number)).toHaveText(reviewed);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results-lan/collective-photos-phone.png",
    fullPage: true,
  });

  // Another device removes the last chip. The open photo page must update
  // without a reload or another analysis request.
  const reviewer = await browser.newContext({ baseURL: origin });
  try {
    const reviewPage = await reviewer.newPage();
    await reviewPage.goto("/review?box=" + code);
    await reviewPage
      .getByRole("button", { name: "Remove Adjustable wrench", exact: true })
      .click();
    await reviewPage
      .getByRole("button", { name: "Accept items", exact: true })
      .click();
    await expect(
      reviewPage.getByRole("heading", { name: "Review complete", exact: true }),
    ).toBeVisible();
    await page.bringToFront();
    for (const number of [1, 2, 3, 4])
      await expect(photoStatus(number)).toHaveText(reviewed, {
        timeout: 12_000,
      });
    await expect(
      page.getByRole("link", {
        name: "Review all photo suggestions",
        exact: true,
      }),
    ).toHaveCount(0);
  } finally {
    await reviewer.close();
  }
  expect(submitted).toHaveLength(5);

  // A failed status refresh must not reuse a cached zero as proof of review.
  await page.route("**/observations?*", (route) =>
    route.fulfill({
      status: 403,
      contentType: "application/problem+json",
      body: JSON.stringify({ title: "Review status unavailable", status: 403 }),
    }),
  );
  await expect(photoStatus(1)).toHaveText(
    "Analysis: succeeded · Complete. Review status unavailable.",
    { timeout: 12_000 },
  );
  await page.unroute("**/observations?*");
  await expect(photoStatus(1)).toHaveText(reviewed, { timeout: 12_000 });
  await page.reload();
  for (const number of [1, 2, 3, 4])
    await expect(photoStatus(number)).toHaveText(reviewed);
});

test("batch errors stay on their photo and both queue failures and model failures can be retried", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const { code } = await createBox(page, "Collective retry");
  await uploadCollection(page, [
    collectionPhoto("Successful staged photo", [110, 110, 110]),
    collectionPhoto("Queue failure then retry", [30, 30, 160]),
    collectionPhoto("Model failure then retry", [240, 0, 0]),
  ]);
  const snapshot = await page.evaluate(
    (boxCode) => fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
    code,
  );
  const queueFailure = `/api/v1/images/${snapshot.images[1].id}/analyses`;
  await page.route(
    `**${queueFailure}`,
    (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/problem+json",
        body: JSON.stringify({
          code: "fixture.queue",
          detail: "Test queue unavailable; retry this photo.",
        }),
      }),
    { times: 1 },
  );
  await page.getByRole("button", { name: "Analyze all photos (3)" }).click();
  await expect(
    page.getByText(
      /Queue requests finished: 3\/3 checked · 2 queued · 0 skipped · 1 could not queue/,
    ),
  ).toBeVisible();
  const modelPhoto = page.getByRole("article", {
    name: "Photo 3",
    exact: true,
  });
  const queuePhoto = page.getByRole("article", {
    name: "Photo 2",
    exact: true,
  });
  await expect(
    queuePhoto.getByText("Test queue unavailable; retry this photo."),
  ).toBeVisible();
  await expect(
    modelPhoto.getByText("Fixture model reached its token limit."),
  ).toBeVisible({ timeout: 20_000 });
  await expect(
    modelPhoto.getByRole("button", { name: "Retry analysis", exact: true }),
  ).toBeEnabled();
  const failed = await page.evaluate(
    (boxCode) => fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
    code,
  );
  expect(failed.images[0].latest_analysis.state).toBe("succeeded");
  expect(failed.images[2].latest_analysis.state).toBe("failed");
  expect(failed.images[1].latest_analysis).toBeNull();
  await modelPhoto
    .getByRole("button", { name: "Retry analysis", exact: true })
    .click();
  await expect(
    modelPhoto.getByRole("button", { name: "Analyze again", exact: true }),
  ).toBeEnabled({ timeout: 20_000 });
  await queuePhoto
    .getByRole("button", { name: "Retry analysis", exact: true })
    .click();
  await expect(page.getByText(/3 of 3 photos analyzed/)).toBeVisible({
    timeout: 20_000,
  });
  await expect(
    queuePhoto.getByText("Test queue unavailable; retry this photo."),
  ).toHaveCount(0);
  const retried = await page.evaluate(
    (boxCode) => fetch(`/api/v1/boxes/${boxCode}`).then((r) => r.json()),
    code,
  );
  expect(retried.images[0].latest_analysis.id).toBe(
    failed.images[0].latest_analysis.id,
  );
  expect(retried.images[2].latest_analysis.id).not.toBe(
    failed.images[2].latest_analysis.id,
  );
  expect(retried.items).toEqual([]);
  expect(retried.pending_observation_count).toBe(3);
});
