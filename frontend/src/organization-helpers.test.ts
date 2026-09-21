import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type Schema } from "./api";
import {
  addTag,
  freezeWrite,
  groupLines,
  loadAllBoxes,
  organizationQuery,
  quantityLabel,
  sameSelection,
  toggleMembership,
  uncertainWrite,
  updateParams,
  type CollectionLine,
} from "./organization-helpers";

afterEach(() => vi.unstubAllGlobals());

describe("tags and filter navigation", () => {
  it("trims and normalizes names while retaining the first display spelling", () => {
    const tags = addTag([], "  Cafe\u0301  ");
    expect(tags).toEqual(["Café"]);
    expect(addTag(tags, "CAFÉ")).toBe(tags);
    expect(addTag(tags, "   ")).toBe(tags);
  });

  it("enforces name and list limits without losing the existing draft", () => {
    const tags = Array.from({ length: 32 }, (_, index) => `Tag ${index}`);
    expect(() => addTag(tags, "extra")).toThrow("32 tags");
    expect(addTag(tags, "TAG 0")).toBe(tags);
    expect(() => addTag([], "a".repeat(65))).toThrow("64 characters");
    expect(addTag([], "📦".repeat(64))).toHaveLength(1);
    expect(tags).toHaveLength(32);
  });

  it.each([
    ["sort", "name_asc"],
    ["lifecycle", "all"],
    ["archived", "true"],
    ["q", "cables"],
  ])("preserves both organization filters when changing %s", (key, value) => {
    const params = new URLSearchParams(
      "tag_id=tag-1&collection_id=group-1&sort=updated_desc&lifecycle=active&q=rope&cursor=old",
    );
    const next = updateParams(params, key, value);
    expect(next.get(key)).toBe(value);
    expect(next.get("tag_id")).toBe("tag-1");
    expect(next.get("collection_id")).toBe("group-1");
    expect(next.has("cursor")).toBe(false);
    expect(params.get("cursor")).toBe("old");
  });

  it("clears one filter without clearing the other or the search", () => {
    const next = updateParams(
      new URLSearchParams(
        "q=rope&tag_id=tag-1&collection_id=group-1&archived=true",
      ),
      "tag_id",
      "",
    );
    expect(next.get("q")).toBe("rope");
    expect(next.get("archived")).toBe("true");
    expect(organizationQuery(next)).toBe("&collection_id=group-1");
    expect(organizationQuery(new URLSearchParams())).toBe("");
  });
});

describe("complete membership selection", () => {
  it("preserves archived members and refuses to add archived non-members", () => {
    const original = ["active", "archived-member"];
    expect(toggleMembership(original, "archived-member", false, true)).toBe(
      original,
    );
    expect(toggleMembership(original, "archived-other", true, true)).toBe(
      original,
    );
    expect(toggleMembership(original, "active", false, false)).toEqual([
      "archived-member",
    ]);
    expect(toggleMembership(original, "new-active", true, false)).toEqual([
      "active",
      "archived-member",
      "new-active",
    ]);
    expect(sameSelection(original, ["archived-member", "active"])).toBe(true);
  });

  it("loads all pages, keeps archived boxes, and encodes cursors", async () => {
    const first = Array.from({ length: 100 }, (_, index) => ({
      code: `box-${index}`,
      lifecycle: "active",
    }));
    const send = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ items: first, page: { next_cursor: "second/+page" } }),
      )
      .mockResolvedValueOnce(
        Response.json({
          items: [{ code: "archived", lifecycle: "archived" }],
          page: { next_cursor: null },
        }),
      );
    vi.stubGlobal("fetch", send);
    const boxes = await loadAllBoxes();
    expect(boxes).toHaveLength(101);
    expect(boxes.at(-1)?.lifecycle).toBe("archived");
    expect(send.mock.calls[0][0]).toContain("lifecycle=all");
    expect(send.mock.calls[1][0]).toContain("cursor=second%2F%2Bpage");
  });

  it("rejects partial results on later page failure", async () => {
    const send = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({
          items: [{ code: "first" }],
          page: { next_cursor: "next" },
        }),
      )
      .mockResolvedValueOnce(
        Response.json({ detail: "Host unavailable" }, { status: 503 }),
      );
    vi.stubGlobal("fetch", send);
    await expect(loadAllBoxes()).rejects.toMatchObject({ status: 503 });
  });

  it("stops repeated cursors instead of exposing an incomplete selection", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(
            Response.json({ items: [], page: { next_cursor: "repeated" } }),
          ),
        ),
    );
    await expect(loadAllBoxes()).rejects.toThrow("could not finish loading");
  });
});

function line(
  id: string,
  code: string,
  quantity: string | null,
  unit: string | null,
  name = "Rope",
): CollectionLine {
  return {
    box_code: code,
    box_name: "Same box name",
    box_lifecycle: "active",
    item: { id, name, quantity, unit } as Schema<"InventoryItemView">,
  };
}

describe("source-preserving itemization", () => {
  const lines = [
    line("a", "box-1", "2", "m"),
    line("b", "box-2", "1", "roll"),
    line("c", "box-2", null, null),
    line("d", "box-2", "0", "pcs", "Adapter"),
  ];

  it("groups matching names without merging lines or summing different units", () => {
    const groups = groupLines(lines, "item");
    expect(groups[0].lines).toEqual(lines.slice(0, 3));
    expect(groups[0].lines.map((entry) => quantityLabel(entry.item))).toEqual([
      "2 m",
      "1 roll",
      "Unknown quantity",
    ]);
    expect(groups.flatMap((group) => group.lines)).toHaveLength(4);
  });

  it("uses source codes to distinguish boxes sharing a name", () => {
    expect(
      groupLines(lines, "box").map((group) => [group.key, group.lines.length]),
    ).toEqual([
      ["box-1", 1],
      ["box-2", 3],
    ]);
  });

  it("combines item-name and source-box filters without changing inventory", () => {
    const groups = groupLines(lines, "item", "rOp", "box-2");
    expect(groups[0].lines).toEqual([lines[1], lines[2]]);
    expect(groupLines(lines, "box", "missing")).toEqual([]);
    expect(lines).toHaveLength(4);
  });

  it("distinguishes zero, unknown quantities and optional units", () => {
    expect(quantityLabel({ quantity: "0", unit: "pcs" })).toBe("0 pcs");
    expect(quantityLabel({ quantity: null, unit: "m" })).toBe(
      "Unknown quantity m",
    );
    expect(quantityLabel({ quantity: "3", unit: null })).toBe("3");
  });
});

describe("safe organization write retries", () => {
  it("freezes body, version and retry key across a lost response", async () => {
    const body = { name: "Camping", box_codes: ["first", "archived"] };
    const request = freezeWrite({
      path: "/collections/group",
      method: "PATCH",
      etag: '"collection:group:v2"',
      body,
    });
    body.name = "Changed draft";
    body.box_codes.pop();
    const send = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Disconnected"))
      .mockResolvedValueOnce(Response.json({ id: "group" }));
    vi.stubGlobal("fetch", send);
    const { path, ...options } = request;
    await expect(api(path, options)).rejects.toMatchObject({ status: 0 });
    await api(path, options);
    for (const [, call] of send.mock.calls) {
      expect(JSON.parse(call.body)).toEqual({
        name: "Camping",
        box_codes: ["first", "archived"],
      });
      expect(new Headers(call.headers).get("If-Match")).toBe(
        '"collection:group:v2"',
      );
      expect(new Headers(call.headers).get("Idempotency-Key")).toBe(
        request.key,
      );
    }
  });

  it.each([0, 408, 500, 503])(
    "retains frozen submissions after uncertain status %s",
    (status) => {
      expect(uncertainWrite(new ApiError(status, "test", "test"))).toBe(true);
    },
  );

  it.each([400, 401, 403, 409, 412, 422])(
    "treats status %s as a definitive rejection",
    (status) => {
      expect(uncertainWrite(new ApiError(status, "test", "test"))).toBe(false);
    },
  );

  it("retains the key if a committed response cannot be decoded", () => {
    expect(uncertainWrite(new SyntaxError("Invalid JSON"))).toBe(true);
  });
});
