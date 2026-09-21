import { describe, expect, it } from "vitest";
import {
  searchIntent,
  suggestionHref,
  suggestionParams,
  type Suggestion,
} from "./search-suggestions";

describe("contextual search intent", () => {
  it.each([
    "",
    " ",
    "a",
    "B",
    "BX",
    "bx-",
    "BX-A",
    "BX-U7",
    "BX-AB*",
    "BX-AB-CD",
    "BX-ABCDEFGH9",
    "BX-ßAB",
    "-_%",
    "🔧",
  ])("does not suggest for incomplete or invalid %j", (input) => {
    expect(searchIntent(input)).toBe("none");
  });
  it.each([
    "BX-AB",
    "bx-7k",
    " BX-oi ",
    "BX-ABCD",
    "BX-ABCD-",
    "BX-ABCD-E",
    "BX-ABCDEFGH",
    "BX-ABCD-EFGH",
  ])("recognizes meaningful code prefix %j", (input) => {
    expect(searchIntent(input)).toBe("box_code");
  });
  it.each([
    "sc",
    "brass screw",
    "Éc",
    "e\u0301c",
    "螺丝",
    "a b",
    "Box name",
    "BXword",
  ])("uses contents and organization intent for %j", (input) => {
    expect(searchIntent(input)).toBe("text");
  });
});

it("keeps only relevant filters, NFC text and a bounded suggestion count", () => {
  expect(
    Object.fromEntries(
      suggestionParams(
        " e\u0301c ",
        new URLSearchParams(
          "tag_id=tag&collection_id=group&cursor=old&lifecycle=archived&q=old",
        ),
      ),
    ),
  ).toEqual({
    q: "éc",
    limit: "8",
    include_archived: "true",
    tag_id: "tag",
    collection_id: "group",
  });
  expect(
    suggestionParams("ab", new URLSearchParams()).get("include_archived"),
  ).toBe("false");
  expect(
    suggestionParams("ab", new URLSearchParams("archived=true")).get(
      "include_archived",
    ),
  ).toBe("true");
});

it("opens the containing box for items, collections directly and scoped tags", () => {
  const item: Suggestion = {
    kind: "item",
    id: "item-id",
    label: "Screw",
    detail: "Tools",
    box_code: "BX-7K3M-R9QA",
  };
  expect(suggestionHref(item, new URLSearchParams())).toBe(
    "/boxes/BX-7K3M-R9QA",
  );
  expect(suggestionHref({ ...item, kind: "box" }, new URLSearchParams())).toBe(
    "/boxes/BX-7K3M-R9QA",
  );
  expect(
    suggestionHref(
      { ...item, kind: "collection", id: "group", box_code: null },
      new URLSearchParams(),
    ),
  ).toBe("/collections/group");
  expect(
    suggestionHref(
      { ...item, kind: "tag", id: "tag", box_code: null },
      new URLSearchParams("collection_id=group&archived=true&q=old&cursor=old"),
    ),
  ).toBe("/boxes?tag_id=tag&collection_id=group&lifecycle=all");
});
