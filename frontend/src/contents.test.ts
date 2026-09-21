import { describe, expect, it } from "vitest";
import { analysisEligible, analysisStatusMessage } from "./contents";
import { matchingItems } from "./review";
import type { Item, Photo, Schema } from "./api";

const photo = (state: Schema<"AnalysisJobView">["state"] | null): Photo => ({
  id: "photo",
  box_code: "BX-TEST",
  lifecycle: "ready",
  caption: "",
  sort_order: 0,
  version: 1,
  original_filename: "photo.png",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  latest_analysis: state
    ? {
        id: "job",
        image_id: "photo",
        state,
        model_profile: "test",
        prompt_version: "test",
        attempt_count: 1,
        max_attempts: 3,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      }
    : null,
});

describe("analysis review status", () => {
  it("stops prompting after all suggestions are accepted or removed", () => {
    expect(analysisStatusMessage("succeeded", 0)).toBe(
      "Complete. No suggestions left to review.",
    );
  });
  it.each([1, 2])("shows only the %s remaining suggestions", (count) => {
    expect(analysisStatusMessage("succeeded", count)).toBe(
      `Complete. ${count} suggestion${count === 1 ? "" : "s"} to review in the shared inventory.`,
    );
  });
  it("does not claim review is complete before suggestions load", () => {
    expect(analysisStatusMessage("succeeded")).toBe("Complete.");
  });
  it("does not present a cached count as current after a failed read", () => {
    expect(analysisStatusMessage("succeeded", 0, true)).toBe(
      "Complete. Review status unavailable.",
    );
  });
  it.each(["queued", "running"] as const)("preserves %s progress", (state) => {
    expect(analysisStatusMessage(state, 0)).toBe("No need to submit again.");
  });
  it.each(["failed", "cancelled"] as const)(
    "does not claim %s is complete",
    (state) => {
      expect(analysisStatusMessage(state, 0)).toBe("");
    },
  );
});

describe("collective photo analysis eligibility", () => {
  it.each([null, "failed", "cancelled"] as const)(
    "allows a ready photo with %s analysis",
    (state) => {
      expect(analysisEligible(photo(state))).toBe(true);
    },
  );
  it.each(["queued", "running", "succeeded"] as const)(
    "does not resubmit %s jobs",
    (state) => {
      expect(analysisEligible(photo(state))).toBe(false);
    },
  );
  it.each(["staged", "rejected", "deleted"] as const)(
    "excludes %s photos",
    (lifecycle) => {
      expect(analysisEligible({ ...photo(null), lifecycle })).toBe(false);
    },
  );
  it("uses a polled terminal state rather than an older queued snapshot", () => {
    expect(
      analysisEligible(photo("queued"), photo("failed").latest_analysis),
    ).toBe(true);
  });
  it("allows a successful photo only after explicit reanalysis confirmation", () => {
    const successful = photo("succeeded");
    expect(analysisEligible(successful)).toBe(false);
    expect(analysisEligible(successful, successful.latest_analysis, true)).toBe(
      true,
    );
  });
  it.each(["queued", "running"] as const)(
    "confirmation does not requeue %s work",
    (state) => {
      const active = photo(state);
      expect(analysisEligible(active, active.latest_analysis, true)).toBe(
        false,
      );
    },
  );
});

describe("same-name review affordance", () => {
  const item = (
    name: string,
    lifecycle: Item["lifecycle"] = "active",
  ): Item => ({
    id: name,
    name,
    lifecycle,
    box_code: "BX-TEST",
    quantity: "3",
    unit: "pieces",
    notes: { source: "", html: "", text: "", renderer_version: "test" },
    provenance: "manual",
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  });
  it("offers all active exact case/space-normalized matches without changing them", () => {
    const first = item(" Wrench "),
      second = item("wrench");
    const items = [
      first,
      second,
      item("WRENCH", "removed"),
      item("Adjustable wrench"),
    ];
    expect(matchingItems({ items }, "WRENCH")).toEqual([first, second]);
    expect(items.map((i) => i.quantity)).toEqual(["3", "3", "3", "3"]);
  });
  it("does not assert fuzzy or partial matches are the same item", () => {
    expect(
      matchingItems({ items: [item("Adjustable wrench")] }, "Wrench"),
    ).toEqual([]);
  });
});
