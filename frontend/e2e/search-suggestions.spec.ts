import {
  test,
  expect,
  type Locator,
  type Page,
  type Response,
  type Route,
} from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { randomUUID } from "node:crypto";
import type { Schema } from "../src/api";

const origin = "http://boxen.test:8174";
const endpoint = "/api/v1/search/suggestions";
const suggestionRoute = "**/api/v1/search/suggestions?*";
type Suggestions = Schema<"SearchSuggestions">;
type Suggestion = Schema<"SearchSuggestion">;

test.skip(
  ({ baseURL }) => baseURL !== origin,
  "Run with playwright.suggestions.config.ts and the disposable LAN fixture",
);

const records = new WeakMap<Page, { errors: string[]; outbound: string[] }>();
test.beforeEach(async ({ page }) => {
  const record = { errors: [] as string[], outbound: [] as string[] };
  records.set(page, record);
  page.on("pageerror", (error) => record.errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["blob:", "data:"].includes(url.protocol) && url.origin !== origin)
      record.outbound.push(request.url());
  });
  await page.goto("/");
  await expect(page.locator("#page-search")).toBeVisible();
});

test.afterEach(({ page }, testInfo) => {
  // The baseline config discovers this file, but intentional skips do not run setup.
  if (testInfo.status === "skipped") return;
  const record = records.get(page);
  if (!record) return;
  expect(record.errors).toEqual([]);
  expect(record.outbound).toEqual([]);
});

async function get<T>(page: Page, path: string): Promise<T> {
  return page.evaluate(async (path) => {
    const response = await fetch("/api/v1" + path);
    if (!response.ok)
      throw new Error(`Fixture read failed: ${response.status}`);
    return response.json();
  }, path);
}

async function mutate<T>(
  page: Page,
  path: string,
  method: string,
  body?: unknown,
  etag?: string,
): Promise<T> {
  return page.evaluate(
    async ({ path, method, body, etag }) => {
      const session = await fetch("/api/v1/session").then((r) => r.json());
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
          `Fixture write failed: ${response.status} ${await response.text()}`,
        );
      return response.status === 204 ? null : response.json();
    },
    { path, method, body, etag },
  );
}

async function seed(page: Page, prefix = "Suggestion") {
  const token = "sg" + randomUUID().replaceAll("-", "").slice(0, 12);
  const query = `${prefix} ${token}`;
  const collection = await mutate<Schema<"CollectionDetail">>(
    page,
    "/collections",
    "POST",
    { name: `${query} collection` },
  );
  const box = await mutate<Schema<"BoxDetail">>(page, "/boxes", "POST", {
    name: `${query} title`,
    description_markdown: `Descriptiononly${token} holds useful inventory.`,
    tags: [`${query} tag`],
    collection_ids: [collection.id],
  });
  const item = await mutate<Schema<"InventoryItemView">>(
    page,
    `/boxes/${box.code}/items`,
    "POST",
    { name: `${query} item` },
  );
  return { token, query, collection, box, item, tag: box.tags[0] };
}

function listbox(page: Page) {
  return page.getByRole("listbox", { name: "Search suggestions", exact: true });
}

function option(page: Page, label: string) {
  return listbox(page)
    .getByRole("option")
    .filter({
      has: page.locator("strong").filter({ hasText: label }),
    });
}

function responseFor(page: Page, query: string) {
  return page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === endpoint && url.searchParams.get("q") === query;
  });
}

async function responseBody(
  response: Response,
  query: string,
  kind: Suggestions["kind"],
) {
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as Suggestions;
  expect(body.query).toBe(query);
  expect(body.kind).toBe(kind);
  expect(body.suggestions.length).toBeLessThanOrEqual(8);
  return body;
}

async function suggest(
  page: Page,
  input: Locator,
  query: string,
  kind: Suggestions["kind"] = "text",
) {
  // Re-entering an unchanged controlled value does not emit React onChange.
  if ((await input.inputValue()) === query) await input.fill("");
  const pending = responseFor(page, query.trim().normalize("NFC"));
  await input.fill(query);
  const response = await pending;
  const body = await responseBody(
    response,
    query.trim().normalize("NFC"),
    kind,
  );
  await expect(listbox(page)).toHaveAttribute("aria-busy", "false");
  await expect(listbox(page).getByRole("option")).toHaveCount(
    body.suggestions.length,
  );
  return { response, body };
}

async function popupQuality(page: Page, screenshot: string) {
  await expect(listbox(page)).toBeVisible();
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
  const rect = await listbox(page).boundingBox();
  expect(rect).not.toBeNull();
  expect(rect!.x).toBeGreaterThanOrEqual(0);
  expect(rect!.x + rect!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  await page.screenshot({ path: screenshot, fullPage: true });
}

test("requires two valid BX payload characters, suppresses malformed/short input, and opens the matching box", async ({
  page,
}) => {
  const data = await seed(page);
  const input = page.locator("#page-search");
  await expect(input).toHaveAttribute("role", "combobox");
  await page.clock.install();
  await page.clock.pauseAt(new Date());
  const queries: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === endpoint) queries.push(url.searchParams.get("q")!);
  });
  for (const value of [
    "",
    " ",
    "B",
    "BX",
    "BX-",
    "BX-A",
    "BX-U7",
    "BX-AB*",
    "BX-AB-CD",
    "BX-ABCDEFGH9",
    "BX-ßAB",
    "-_%",
    "🔧",
    "é",
    "e\u0301",
    "螺",
  ]) {
    await input.fill(value);
    await page.clock.runFor(300);
    await expect(input).toHaveAttribute("aria-expanded", "false");
  }
  expect(queries).toEqual([]);
  const prefix = data.box.code.slice(0, 5);
  const pending = responseFor(page, prefix);
  await input.fill(prefix);
  await page.clock.runFor(249);
  expect(queries).toEqual([]);
  await page.clock.runFor(1);
  const body = await responseBody(await pending, prefix, "box_code");
  expect(body.suggestions.every((entry) => entry.kind === "box")).toBe(true);
  expect(body.suggestions).toContainEqual(
    expect.objectContaining({ label: data.box.code, detail: data.box.name }),
  );
  await page.clock.resume();
  await expect(option(page, data.box.code)).toBeVisible();
  await option(page, data.box.code).click();
  await expect(page).toHaveURL(`${origin}/boxes/${data.box.code}`);
  await expect(
    page.getByRole("heading", { name: data.box.name, exact: true }),
  ).toBeVisible();
});

test("ordinary text renders item/tag/collection details while free Enter still searches titles and descriptions", async ({
  page,
}, testInfo) => {
  const data = await seed(page);
  const input = page.locator("#page-search");
  const { body } = await suggest(page, input, data.query);
  expect(body.suggestions.map((entry) => entry.kind)).toEqual([
    "item",
    "tag",
    "collection",
  ]);
  for (const entry of body.suggestions) {
    const row = option(page, entry.label);
    await expect(row.locator(".search-suggestion-kind")).toHaveText(
      entry.kind[0].toUpperCase() + entry.kind.slice(1),
    );
    await expect(row.locator("strong")).toHaveText(entry.label);
    await expect(row.locator("small")).toHaveText(entry.detail);
  }
  await expect(option(page, data.box.name)).toHaveCount(0);
  await expect(input).toHaveAttribute("aria-autocomplete", "list");
  expect(await input.getAttribute("aria-controls")).toBe(
    await listbox(page).getAttribute("id"),
  );
  await popupQuality(page, testInfo.outputPath("suggestions-desktop.png"));
  await option(page, data.item.name).click();
  await expect(page).toHaveURL(`${origin}/boxes/${data.box.code}`);

  for (const query of [`${data.query} title`, `Descriptiononly${data.token}`]) {
    await page.goto("/");
    const result = await suggest(page, input, query);
    expect(result.body.suggestions).toEqual([]);
    await input.press("Enter");
    await expect(page).toHaveURL(
      (url) =>
        url.pathname === "/search" && url.searchParams.get("q") === query,
    );
    await expect(
      page.getByRole("heading", { name: data.box.name, exact: true }),
    ).toBeVisible();
  }
});

test("global combobox supports arrows, Escape, Tab, selected Enter and continued typing after a full search", async ({
  page,
}) => {
  const data = await seed(page);
  const input = page.locator("#global-search");
  await expect(input).toHaveAttribute("role", "combobox");
  await suggest(page, input, data.query);
  await input.press("ArrowDown");
  await expect(listbox(page).getByRole("option").first()).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(await input.getAttribute("aria-activedescendant")).toBe(
    await listbox(page).getByRole("option").first().getAttribute("id"),
  );
  await input.press("ArrowDown");
  await input.press("ArrowUp");
  await expect(listbox(page).getByRole("option").first()).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await input.press("Escape");
  await expect(listbox(page)).toHaveCount(0);
  await expect(input).toBeFocused();
  await expect(input).toHaveValue(data.query);
  await input.press("ArrowDown");
  await expect(listbox(page).getByRole("option")).toHaveCount(3);
  await input.press("Tab");
  await expect(listbox(page)).toHaveCount(0);
  await expect(input).not.toBeFocused();
  await input.focus();
  await expect(listbox(page).getByRole("option")).toHaveCount(3);
  await input.press("ArrowUp");
  await expect(option(page, data.collection.name)).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await input.press("Enter");
  await expect(page).toHaveURL(`${origin}/collections/${data.collection.id}`);
  await expect(
    page.getByRole("heading", { name: data.collection.name, exact: true }),
  ).toBeVisible();

  await suggest(page, input, `${data.query} item`);
  await input.press("ArrowDown");
  await input.press("ArrowRight");
  await expect(input).not.toHaveAttribute("aria-activedescendant", /.+/);
  await input.press("Enter");
  await expect(page).toHaveURL(
    (url) =>
      url.pathname === "/search" &&
      url.searchParams.get("q") === `${data.query} item`,
  );
  // SPA navigation must not leave the still-mounted global input unable to reopen.
  await expect(
    page.getByRole("heading", { name: data.box.name, exact: true }),
  ).toBeVisible();
  await suggest(page, input, data.query);
  await input.press("ArrowDown");
  await input.press("Enter");
  await expect(page).toHaveURL(`${origin}/boxes/${data.box.code}`);
});

test("page and global searches retain tag/collection/archive scope for API requests, tag selection and full search", async ({
  page,
}) => {
  const data = await seed(page);
  const current = await get<Schema<"BoxDetail">>(
    page,
    `/boxes/${data.box.code}`,
  );
  await mutate(
    page,
    `/boxes/${data.box.code}/archive`,
    "POST",
    undefined,
    `"box:${data.box.code}:v${current.version}"`,
  );
  const outside = await mutate<Schema<"BoxDetail">>(page, "/boxes", "POST", {
    name: `${data.query} outside`,
  });
  await mutate(page, `/boxes/${outside.code}/items`, "POST", {
    name: `${data.query} outside item`,
  });
  const scope = new URLSearchParams({
    tag_id: data.tag.id,
    collection_id: data.collection.id,
    lifecycle: "archived",
  });
  for (const selector of ["#page-search", "#global-search"]) {
    await page.goto("/boxes?" + scope);
    const input = page.locator(selector);
    const { response, body } = await suggest(page, input, data.query);
    expect(Object.fromEntries(new URL(response.url()).searchParams)).toEqual({
      q: data.query,
      limit: "8",
      include_archived: "true",
      tag_id: data.tag.id,
      collection_id: data.collection.id,
    });
    expect(body.suggestions.map((entry) => entry.kind)).toEqual([
      "item",
      "tag",
      "collection",
    ]);
    expect(
      body.suggestions
        .filter((entry) => entry.kind === "item")
        .map((entry) => entry.box_code),
    ).toEqual([data.box.code]);
    await option(page, data.tag.name).click();
    await expect(page).toHaveURL(
      (url) =>
        url.pathname === "/boxes" &&
        url.searchParams.get("tag_id") === data.tag.id &&
        url.searchParams.get("collection_id") === data.collection.id &&
        url.searchParams.get("lifecycle") === "all",
    );
    // The URL can update before React commits the new filter state.
    await expect(page.getByLabel("Show", { exact: true })).toHaveValue("all");
    await suggest(page, input, data.query);
    const searchResponse = page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api/v1/search",
    );
    await input.press("Enter");
    const searchURL = new URL((await searchResponse).url());
    expect(searchURL.searchParams.get("include_archived")).toBe("true");
    expect(searchURL.searchParams.get("tag_id")).toBe(data.tag.id);
    expect(searchURL.searchParams.get("collection_id")).toBe(
      data.collection.id,
    );
    await expect(page).toHaveURL(
      (url) =>
        url.pathname === "/search" &&
        url.searchParams.get("archived") === "true" &&
        url.searchParams.get("tag_id") === data.tag.id &&
        url.searchParams.get("collection_id") === data.collection.id,
    );
    await expect(
      page.getByRole("heading", { name: data.box.name, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: outside.name, exact: true }),
    ).toHaveCount(0);
  }
  await page.goto(
    `/boxes?tag_id=${data.tag.id}&collection_id=${data.collection.id}`,
  );
  expect(
    (await suggest(page, page.locator("#page-search"), data.query)).body
      .suggestions,
  ).toEqual([]);
});

test("IME composition sends no suggestion request or submission until composition ends, then accepts Unicode letters", async ({
  page,
}) => {
  const data = await seed(page, "螺丝");
  const input = page.locator("#page-search");
  const queries: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === endpoint || url.pathname === "/api/v1/search")
      queries.push(url.pathname);
  });
  await page.clock.install();
  await page.clock.pauseAt(new Date());
  await input.focus();
  await input.dispatchEvent("compositionstart", { data: "" });
  await input.fill("螺丝");
  await page.clock.runFor(600);
  await input.press("Enter");
  await expect(page).toHaveURL(origin + "/");
  expect(queries).toEqual([]);
  await expect(input).toHaveAttribute("aria-expanded", "false");
  const pending = responseFor(page, "螺丝");
  await input.dispatchEvent("compositionend", { data: "螺丝" });
  await page.clock.runFor(250);
  const body = await responseBody(await pending, "螺丝", "text");
  expect(body.suggestions).toContainEqual(
    expect.objectContaining({ label: data.item.name, kind: "item" }),
  );
  await page.clock.resume();
  await option(page, data.item.name).click();
  await expect(page).toHaveURL(`${origin}/boxes/${data.box.code}`);
});

test("debounces replacement text, aborts superseded work and ignores a late response even when transport ignores abort", async ({
  page,
}) => {
  const data = await seed(page);
  const oldQuery = `${data.query} old`;
  const newQuery = `${data.query} new`;
  // Keep the transport alive to exercise the stale-result guard independently
  // of fetch abort, while recording that the component did cancel its signal.
  await page.evaluate((endpoint) => {
    const nativeFetch = window.fetch.bind(window);
    const fixture = window as typeof window & { suggestionAborts: string[] };
    fixture.suggestionAborts = [];
    window.fetch = (input, init) => {
      const url = new URL(String(input), location.href);
      if (url.pathname !== endpoint) return nativeFetch(input, init);
      init?.signal?.addEventListener("abort", () =>
        fixture.suggestionAborts.push(url.searchParams.get("q")!),
      );
      return nativeFetch(input, { ...init, signal: undefined });
    };
  }, endpoint);
  let delayed: Route | undefined;
  const seen: string[] = [];
  const row = (label: string): Suggestion => ({
    kind: "item",
    id: data.item.id,
    label,
    detail: `${data.box.name} · ${data.box.code}`,
    box_code: data.box.code,
  });
  await page.route(suggestionRoute, async (route) => {
    const query = new URL(route.request().url()).searchParams.get("q")!;
    seen.push(query);
    if (query === oldQuery) {
      delayed = route;
      return;
    }
    await route.fulfill({
      json: {
        query,
        kind: "text",
        suggestions: [row(newQuery)],
      } satisfies Suggestions,
    });
  });
  try {
    await page.clock.install();
    await page.clock.pauseAt(new Date());
    const input = page.locator("#page-search");
    await input.fill(oldQuery);
    await page.clock.runFor(250);
    await expect.poll(() => delayed !== undefined).toBe(true);
    await input.fill(`${data.query} intermediate`);
    await page.clock.runFor(200);
    await input.fill(newQuery);
    await page.clock.runFor(249);
    expect(seen).toEqual([oldQuery]);
    await expect(listbox(page)).toHaveCount(0);
    const pending = responseFor(page, newQuery);
    await page.clock.runFor(1);
    await responseBody(await pending, newQuery, "text");
    await expect(option(page, newQuery)).toBeVisible();
    expect(
      await page.evaluate(
        () =>
          (window as typeof window & { suggestionAborts: string[] })
            .suggestionAborts,
      ),
    ).toContain(oldQuery);
    const late = responseFor(page, oldQuery);
    await delayed!.fulfill({
      json: {
        query: oldQuery,
        kind: "text",
        suggestions: [row(oldQuery)],
      } satisfies Suggestions,
    });
    delayed = undefined;
    await (await late).finished();
    await page.clock.runFor(100);
    await expect(option(page, newQuery)).toBeVisible();
    await expect(option(page, oldQuery)).toHaveCount(0);
    expect(seen).toEqual([oldQuery, newQuery]);
    await input.press("Escape");
    await expect(listbox(page)).toHaveCount(0);
    await page.clock.resume();
  } finally {
    if (delayed) await delayed.abort();
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
});

test("failed requests and the five-second deadline stay bounded, recover and leave full search usable", async ({
  page,
}) => {
  const data = await seed(page);
  const input = page.locator("#page-search");
  const failedQuery = `${data.query} failure`;
  const timeoutQuery = `${data.query} title`;
  const seen: string[] = [];
  let delayed: Route | undefined;
  await page.route(suggestionRoute, async (route) => {
    const query = new URL(route.request().url()).searchParams.get("q")!;
    seen.push(query);
    if (query === timeoutQuery) {
      delayed = route;
      return;
    }
    if (query === failedQuery) {
      await route.fulfill({
        status: 503,
        json: {
          code: "fixture.unavailable",
          detail: "Disposable suggestion failure",
        },
      });
      return;
    }
    await route.continue();
  });
  try {
    await input.fill(failedQuery);
    const unavailable = page.locator(".search-suggestions-message");
    await expect(unavailable).toHaveText(
      "Suggestions unavailable. You can still submit Search.",
    );
    await expect(listbox(page).getByRole("option")).toHaveCount(0);
    await suggest(page, input, data.query);
    await expect(option(page, data.item.name)).toBeVisible();
    await page.clock.install();
    await page.clock.pauseAt(new Date());
    await input.fill(timeoutQuery);
    await page.clock.runFor(250);
    await expect.poll(() => delayed !== undefined).toBe(true);
    await expect(unavailable).toHaveText("Looking for suggestions…");
    await page.clock.runFor(4_999);
    await expect(unavailable).toHaveText("Looking for suggestions…");
    const aborted = page.waitForEvent("requestfailed", {
      predicate: (request) =>
        new URL(request.url()).searchParams.get("q") === timeoutQuery,
    });
    await page.clock.runFor(1);
    await expect(unavailable).toHaveText(
      "Suggestions unavailable. You can still submit Search.",
    );
    await aborted;
    await delayed!.abort();
    delayed = undefined;
    await page.clock.runFor(5_000);
    expect(seen).toEqual([failedQuery, data.query, timeoutQuery]);
    await page.clock.resume();
    await input.press("Enter");
    await expect(page).toHaveURL(
      (url) =>
        url.pathname === "/search" &&
        url.searchParams.get("q") === timeoutQuery,
    );
    await expect(
      page.getByRole("heading", { name: data.box.name, exact: true }),
    ).toBeVisible();
  } finally {
    if (delayed) await delayed.abort();
    await page.unrouteAll({ behavior: "ignoreErrors" });
  }
});

test.describe("emulated touch context (not physical-phone qualification)", () => {
  test.use({
    hasTouch: true,
    isMobile: true,
    viewport: { width: 375, height: 812 },
  });
  test("375px and 320px popups remain accessible and actual option taps navigate", async ({
    page,
  }, testInfo) => {
    const data = await seed(page, "Touch inventory with a descriptive label");
    expect(await page.evaluate(() => navigator.maxTouchPoints)).toBeGreaterThan(
      0,
    );
    for (const width of [375, 320]) {
      await page.setViewportSize({ width, height: 812 });
      await page.goto("/");
      const input = page.locator("#page-search");
      await input.tap();
      await suggest(page, input, data.query);
      await popupQuality(
        page,
        testInfo.outputPath(`suggestions-touch-${width}.png`),
      );
      // Native Playwright tap dispatches touch input; do not replace with click
      // or DOM dispatch, which would hide a blur-before-selection race.
      await option(page, data.item.name).tap();
      await expect(page).toHaveURL(`${origin}/boxes/${data.box.code}`);
      await expect(
        page.getByRole("heading", { name: data.box.name, exact: true }),
      ).toBeVisible();
      await page.goto("/");
      await suggest(page, input, data.query);
      await option(page, data.collection.name).tap();
      await expect(page).toHaveURL(
        `${origin}/collections/${data.collection.id}`,
      );
    }
  });
});
