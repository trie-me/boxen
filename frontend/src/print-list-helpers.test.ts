import { describe, expect, it } from "vitest";
import {
  MAX_PINS,
  mergePins,
  readPins,
  sheetCount,
} from "./print-list-helpers";

describe("print pins", () => {
  it("recovers safely from malformed browser storage", () => {
    for (const value of [null, "broken", "{}", "null", '"abc"'])
      expect(readPins(value)).toEqual([]);
    expect(
      readPins(
        '["BX-7K3M-R9QA", false, "BX-7K3M-R9QA", "not a code", "BX-0000-0004"]',
      ),
    ).toEqual(["BX-7K3M-R9QA", "BX-0000-0004"]);
  });
  it("preserves original pin order across repeated and overlapping additions", () => {
    expect(mergePins(["b", "a"], ["a", "c", "b", "d"])).toEqual([
      "b",
      "a",
      "c",
      "d",
    ]);
  });
  it("refuses an oversized addition without silently dropping boxes", () => {
    const current = Array.from({ length: MAX_PINS }, (_, i) => String(i));
    expect(mergePins(current, ["extra"])).toEqual(current);
    expect(mergePins(current, ["0"])).toEqual(current);
  });
  it("counts only required pages, including partly used first sheets", () => {
    expect(sheetCount(0, 10)).toBe(0);
    expect(sheetCount(1, 10)).toBe(1);
    expect(sheetCount(2, 10)).toBe(2);
    expect(sheetCount(10, 1)).toBe(1);
    expect(sheetCount(11, 1)).toBe(2);
    expect(sheetCount(500, 10)).toBe(51);
  });
});
