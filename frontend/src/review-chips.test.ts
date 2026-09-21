import { afterEach, describe, expect, it, vi } from "vitest";
import * as apiModule from "./api";
import { ApiError } from "./api";
import {
  chipDecision,
  emptyDraft,
  loadPendingChips,
  makeSubmission,
  pendingChips,
  pendingCountsByPhoto,
  reviewDraft,
  uncertainOutcome,
  type Observation,
} from "./review-chips";

const observation = (
  id: string,
  quantity: string | null = "2",
): Observation => ({
  id,
  run_id: "run",
  image_id: "photo-" + id,
  proposed_name: "Cable",
  proposed_quantity: quantity,
  proposed_unit: "pieces",
  confidence: 0.8,
  bounding_box: null,
  attributes: { evidence: "Visible cables" },
  decision: "pending",
  accepted_item_id: null,
  decided_at: null,
  created_at: "2026-09-20T20:00:00Z",
});
afterEach(() => vi.restoreAllMocks());

describe("pending review counts per photo", () => {
  it("counts only unresolved unique observations, including earlier runs", () => {
    const first = observation("one");
    const older = {
      ...observation("two"),
      image_id: first.image_id,
      run_id: "older",
    };
    const unrelated = observation("three");
    const settled = ["accepted", "rejected", "superseded"].map(
      (decision, index) => ({
        ...observation(`settled-${index}`),
        image_id: first.image_id,
        decision: decision as Observation["decision"],
      }),
    );
    expect(
      pendingCountsByPhoto([first, first, older, unrelated, ...settled]),
    ).toEqual(
      new Map([
        [first.image_id, 2],
        [unrelated.image_id, 1],
      ]),
    );
    expect(pendingCountsByPhoto(settled)).toEqual(new Map());
    expect(pendingCountsByPhoto([])).toEqual(new Map());
  });
});

describe("chip review draft", () => {
  it("keeps quantities, ids and manual additions in one mixed decision set", () => {
    const first = observation("one");
    const second = observation("two", null);
    let draft = reviewDraft(emptyDraft(), { type: "remove", id: second.id });
    draft = reviewDraft(draft, {
      type: "add",
      chip: {
        id: "manual",
        item: { name: "Gloves", quantity: null, notes_markdown: "" },
      },
    });
    const request = makeSubmission([first, second], draft, "retry-key");
    expect(request.body.accept).toEqual([
      {
        observation_id: first.id,
        decision: {
          mode: "create",
          item: {
            name: "Cable",
            quantity: "2",
            unit: "pieces",
            notes_markdown: "",
          },
        },
      },
    ]);
    expect(request.body.reject).toEqual([second.id]);
    expect(request.body.add[0]).toMatchObject({
      name: "Gloves",
      quantity: null,
    });
    expect(request.key).toBe("retry-key");
  });
  it("does not deduplicate equal names or invent unknown quantities", () => {
    const request = makeSubmission(
      [observation("one", null), observation("two", null)],
      emptyDraft(),
      "key",
    );
    expect(request.body.accept).toHaveLength(2);
    expect(request.body.accept[0].decision).toMatchObject({
      item: { quantity: null },
    });
  });
  it("keeps removals through new poll objects and can restore them", () => {
    let draft = reviewDraft(emptyDraft(), { type: "remove", id: "one" });
    const refreshed = [observation("one"), observation("two")];
    expect(makeSubmission(refreshed, draft, "key").body.reject).toEqual([
      "one",
    ]);
    draft = reviewDraft(draft, { type: "restore" });
    expect(makeSubmission(refreshed, draft, "key").body.accept).toHaveLength(2);
  });
  it("all-removed sets reject suggestions without creating inventory", () => {
    const draft = reviewDraft(emptyDraft(), { type: "remove", id: "one" });
    expect(makeSubmission([observation("one")], draft, "key").body).toEqual({
      accept: [],
      reject: ["one"],
      add: [],
    });
  });
  it("edits and removes manual chips locally; manual-only sets are valid", () => {
    let draft = reviewDraft(emptyDraft(), {
      type: "add",
      chip: { id: "manual", item: { name: "Glove", notes_markdown: "" } },
    });
    draft = reviewDraft(draft, {
      type: "edit-manual",
      id: "manual",
      item: { name: "Gloves", quantity: "2", notes_markdown: "" },
    });
    expect(makeSubmission([], draft, "key").body.add[0].name).toBe("Gloves");
    draft = reviewDraft(draft, { type: "remove-manual", id: "manual" });
    expect(() => makeSubmission([], draft, "key")).toThrow();
  });
  it("freezes payload and ids for retries without including later suggestions", () => {
    let draft = reviewDraft(emptyDraft(), {
      type: "add",
      chip: { id: "manual", item: { name: "Gloves", notes_markdown: "" } },
    });
    const request = makeSubmission([observation("one")], draft, "key");
    draft.manual[0].item.name = "Changed after snapshot";
    draft = reviewDraft(draft, { type: "remove", id: "one" });
    expect(request.body.add[0].name).toBe("Gloves");
    expect(request.body.reject).toEqual([]);
    const committed = reviewDraft(draft, {
      type: "committed",
      submission: request,
    });
    expect(committed.manual).toEqual([]);
    expect(committed.removed.size).toBe(0);
    expect(
      pendingChips([observation("one"), observation("two")], committed).map(
        (o) => o.id,
      ),
    ).toEqual(["two"]);
  });
  it("explicit links keep original ETag and no quantity patch", () => {
    const decision = {
      mode: "merge" as const,
      item_id: "item",
      item_etag: '"item:item:v1"',
    };
    const draft = reviewDraft(emptyDraft(), {
      type: "decide",
      id: "one",
      decision,
    });
    expect(chipDecision(observation("one"), draft)).toEqual(decision);
    expect(
      makeSubmission([observation("one")], draft, "key").body.accept[0]
        .decision,
    ).toEqual(decision);
  });
  it("deduplicates IDs across pages, ignores non-pending and bounds payloads", () => {
    expect(
      pendingChips(
        [
          observation("one"),
          observation("one"),
          { ...observation("two"), decision: "accepted" },
        ],
        emptyDraft(),
      ),
    ).toHaveLength(1);
    expect(() =>
      makeSubmission(
        Array.from({ length: 501 }, (_, i) => observation(String(i))),
        emptyDraft(),
        "key",
      ),
    ).toThrow();
  });
  it.each([0, 408, 500, 503])(
    "retains frozen retry after uncertain HTTP %s",
    (status) => {
      expect(uncertainOutcome(new ApiError(status, "test", "test"))).toBe(true);
    },
  );
  it.each([400, 403, 409, 412, 422])(
    "allows correction after definitive HTTP %s",
    (status) => {
      expect(uncertainOutcome(new ApiError(status, "test", "test"))).toBe(
        false,
      );
    },
  );
  it("treats unreadable responses as uncertain", () =>
    expect(uncertainOutcome(new SyntaxError())).toBe(true));
  it("loads all pending pages before exposing a set", async () => {
    const mock = vi
      .spyOn(apiModule, "api")
      .mockResolvedValueOnce({
        items: [observation("one")],
        page: { next_cursor: "next/one" },
      })
      .mockResolvedValueOnce({
        items: [observation("one"), observation("two")],
        page: { next_cursor: null },
      });
    expect((await loadPendingChips("BX-test")).map((o) => o.id)).toEqual([
      "one",
      "two",
    ]);
    expect(mock.mock.calls[1][0]).toContain("cursor=next%2Fone");
  });
  it("rejects repeated cursors rather than presenting an incomplete set", async () => {
    vi.spyOn(apiModule, "api").mockResolvedValue({
      items: [observation("one")],
      page: { next_cursor: "repeat" },
    });
    await expect(loadPendingChips("BX-test")).rejects.toThrow("finish loading");
  });
});
