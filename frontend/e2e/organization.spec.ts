import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const origin = "http://boxen.test:8174";
test.skip(
  ({ baseURL }) => baseURL !== origin,
  "Run with playwright.lan.config.ts",
);

let outbound: string[] = [];
let errors: string[] = [];
test.beforeEach(async ({ page }) => {
  outbound = [];
  errors = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["blob:", "data:"].includes(url.protocol) && url.origin !== origin)
      outbound.push(request.url());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Find what you stored." }),
  ).toBeVisible();
});
test.afterEach(() => {
  expect(outbound).toEqual([]);
  expect(errors).toEqual([]);
});

async function get(page: Page, path: string) {
  return page.evaluate(async (path) => {
    const response = await fetch("/api/v1" + path);
    if (!response.ok)
      throw new Error("Fixture read failed: " + response.status);
    return response.json();
  }, path);
}

async function mutate(
  page: Page,
  path: string,
  method: string,
  body?: unknown,
  etag?: string,
) {
  return page.evaluate(
    async ({ path, method, body, etag }) => {
      const session = await fetch("/api/v1/session").then((response) =>
        response.json(),
      );
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        "X-CSRF-Token": session.csrf_token,
        "Idempotency-Key": Array.from(
          crypto.getRandomValues(new Uint8Array(16)),
          (n) => n.toString(16).padStart(2, "0"),
        ).join(""),
      };
      if (etag) headers["If-Match"] = etag;
      const response = await fetch("/api/v1" + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!response.ok)
        throw new Error(
          "Fixture write failed: " +
            response.status +
            " " +
            (await response.text()),
        );
      return response.status === 204 ? null : response.json();
    },
    { path, method, body, etag },
  );
}

async function collection(page: Page, name: string) {
  await page.goto("/collections");
  await page.getByLabel("Collection name", { exact: true }).fill(name);
  await page
    .getByLabel("Description", { exact: true })
    .fill("Related boxes, original inventory preserved.");
  await page
    .getByRole("button", { name: "Create collection", exact: true })
    .click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  return page.url().split("/").at(-1)!;
}

async function box(page: Page, name: string, group: string, tag: string) {
  await page.goto("/boxes/new");
  await page.getByLabel("Box name", { exact: true }).fill(name);
  await page.getByRole("textbox", { name: "Tags", exact: true }).fill(tag);
  await page.getByRole("button", { name: "Add tag", exact: true }).click();
  await page.getByRole("checkbox", { name: group, exact: true }).check();
  if (page.viewportSize()!.width < 600) {
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
      path: "test-results-lan/organization-box-editor-mobile.png",
      fullPage: true,
    });
  }
  await page.getByRole("button", { name: "Create box", exact: true }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  return page.url().split("/").at(-1)!;
}

async function item(
  page: Page,
  name: string,
  quantity?: string,
  unit?: string,
) {
  await page.getByRole("button", { name: "Add item", exact: true }).click();
  await page.getByLabel("Item name", { exact: true }).fill(name);
  if (quantity)
    await page.getByLabel("Quantity", { exact: true }).fill(quantity);
  if (unit) await page.getByLabel("Unit", { exact: true }).fill(unit);
  await page.getByRole("button", { name: "Save item", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Save item", exact: true }),
  ).toHaveCount(0);
}

test("tags and overlapping collections preserve inventory and expose source boxes", async ({
  page,
}) => {
  const name = "Organization field kit";
  const id = await collection(page, name);
  const first = await box(page, "Organization tools", name, " Fragile ");
  await item(page, "Organization rope", "2", "m");
  const second = await box(page, "Organization spares", name, "fragile");
  await item(page, "Organization rope", "1", "roll");
  await item(page, "Organization adapter");
  const tags = (await get(page, "/tags")).items.filter(
    (tag: { name: string }) => tag.name.toLowerCase() === "fragile",
  );
  expect(tags).toHaveLength(1);
  expect(tags[0].name).toBe("Fragile");
  expect(tags[0].box_count).toBe(2);

  await page.goto("/boxes");
  await page
    .getByLabel("Filter by tag", { exact: true })
    .selectOption(tags[0].id);
  await page
    .getByLabel("Filter by collection", { exact: true })
    .selectOption(id);
  await expect(
    page.getByRole("heading", { name: "Organization tools", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Organization spares", exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).searchParams.get("tag_id")).toBe(tags[0].id);
  expect(new URL(page.url()).searchParams.get("collection_id")).toBe(id);

  await page.goto(
    "/search?q=field&tag_id=" + tags[0].id + "&collection_id=" + id,
  );
  await expect(
    page.getByRole("heading", { name: "Organization tools", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Organization spares", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("checkbox", { name: "Include archived boxes", exact: true })
    .click();
  await expect(
    page.getByRole("checkbox", { name: "Include archived boxes", exact: true }),
  ).toBeChecked();
  expect(new URL(page.url()).searchParams.get("collection_id")).toBe(id);
  expect(new URL(page.url()).searchParams.get("tag_id")).toBe(tags[0].id);

  await page.goto("/collections/" + id);
  await expect(
    page.getByRole("heading", { name: "Combined contents", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Organization rope", { exact: true }),
  ).toHaveCount(2);
  await expect(
    page.getByText("Organization adapter", { exact: true }),
  ).toBeVisible();
  expect(
    await page.locator(`a[href='/boxes/${first}']`).count(),
  ).toBeGreaterThan(0);
  expect(
    await page.locator(`a[href='/boxes/${second}']`).count(),
  ).toBeGreaterThan(0);
  const detail = await get(page, "/collections/" + id);
  expect(detail.item_count).toBe(3);
  expect(
    detail.items.map(
      (line: { item: { quantity: string | null; unit: string | null } }) => [
        line.item.quantity,
        line.item.unit,
      ],
    ),
  ).toEqual(
    expect.arrayContaining([
      ["2", "m"],
      ["1", "roll"],
      [null, null],
    ]),
  );
  await page.getByLabel("Filter item name", { exact: true }).fill("adapter");
  await expect(
    page.getByText("Organization rope", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Organization adapter", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Filter item name", { exact: true }).fill("");
  await page.screenshot({
    path: "test-results-lan/organization-desktop.png",
    fullPage: true,
  });

  // A box may belong to more than one collection without copying its items.
  const secondId = await collection(page, "Organization travel kit");
  await page
    .getByRole("button", { name: "Edit collection", exact: true })
    .click();
  await page
    .getByRole("checkbox", {
      name: `Organization tools (${first})`,
      exact: true,
    })
    .check();
  await page
    .getByRole("button", { name: "Save collection", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Edit collection", exact: true }),
  ).toBeVisible();
  expect((await get(page, "/boxes/" + first)).collections).toHaveLength(2);
  expect((await get(page, "/collections/" + secondId)).items).toHaveLength(1);

  // Clear a tag without affecting collection memberships or inventory.
  await page.goto(`/boxes/${first}/edit`);
  await page
    .getByRole("button", { name: "Remove tag Fragile", exact: true })
    .click();
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Organization tools", exact: true }),
  ).toBeVisible();
  expect((await get(page, "/boxes/" + first)).tags).toEqual([]);
  expect((await get(page, "/boxes/" + first)).collections).toHaveLength(2);

  await page.goto("/collections/" + id);
  await page
    .getByRole("button", { name: "Edit collection", exact: true })
    .click();
  await page
    .getByRole("checkbox", {
      name: `Organization spares (${second})`,
      exact: true,
    })
    .uncheck();
  await page
    .getByLabel("Collection name", { exact: true })
    .fill("Organization expedition kit");
  await page
    .getByRole("button", { name: "Save collection", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Organization expedition kit",
      exact: true,
    }),
  ).toBeVisible();
  expect((await get(page, "/collections/" + id)).items).toHaveLength(1);
  expect((await get(page, "/boxes/" + second)).items).toHaveLength(2);
  await page
    .getByRole("button", { name: "Delete collection", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete collection", exact: true })
    .click();
  await expect(page).toHaveURL(origin + "/collections");
  expect((await get(page, "/boxes/" + first)).items).toHaveLength(1);
  expect((await get(page, "/boxes/" + second)).items).toHaveLength(2);
  expect(
    (await get(page, "/boxes/" + first)).collections.map(
      (group: { id: string }) => group.id,
    ),
  ).toEqual([secondId]);
});

test("collection phone layout, archived membership and stale edits remain safe", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const id = await collection(page, "Organization mobile collection");
  const code = await box(
    page,
    "Organization archived box",
    "Organization mobile collection",
    "mobile",
  );
  await item(page, "Organization historical item");
  const before = await get(page, "/boxes/" + code);
  await mutate(
    page,
    `/boxes/${code}/archive`,
    "POST",
    undefined,
    `"box:${code}:v${before.version}"`,
  );
  await page.goto("/collections/" + id);
  await expect(
    page.getByRole("heading", { name: "Combined contents", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Organization historical item", { exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("checkbox", { name: "Include archived boxes", exact: true })
    .click();
  await expect(
    page.getByRole("checkbox", { name: "Include archived boxes", exact: true }),
  ).toBeChecked();
  await expect(
    page.getByText("Organization historical item", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Edit collection", exact: true })
    .click();
  const member = page.getByRole("checkbox", {
    name: `Organization archived box (${code})`,
    exact: true,
  });
  await expect(member).toBeChecked();
  await expect(member).toBeDisabled();
  const current = await get(page, "/collections/" + id);
  await mutate(
    page,
    "/collections/" + id,
    "PATCH",
    { description: "Changed on another device" },
    `"collection:${id}:v${current.version}"`,
  );
  await page
    .getByLabel("Collection name", { exact: true })
    .fill("Organization stale draft");
  await page
    .getByRole("button", { name: "Save collection", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Reload latest version", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Collection name", { exact: true })).toHaveValue(
    "Organization stale draft",
  );
  expect((await get(page, "/collections/" + id)).name).toBe(
    "Organization mobile collection",
  );
  await page
    .getByRole("button", { name: "Reload latest version", exact: true })
    .click();
  await expect(page.getByLabel("Description", { exact: true })).toHaveValue(
    "Changed on another device",
  );
  await page
    .getByRole("button", { name: "Save collection", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Edit collection", exact: true }),
  ).toBeVisible();
  expect(
    (await get(page, "/collections/" + id)).boxes.map(
      (box: { code: string }) => box.code,
    ),
  ).toContain(code);
  await page.screenshot({
    path: "test-results-lan/organization-mobile.png",
    fullPage: true,
  });
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  for (const width of [375, 320]) {
    await page.setViewportSize({ width, height: 812 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
});
