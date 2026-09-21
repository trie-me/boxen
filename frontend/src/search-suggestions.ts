import type { Schema } from "./api";

export type Suggestion = Schema<"SearchSuggestion">;
export type SearchIntent = "none" | "box_code" | "text";

// Keep the same eligibility rules as the local suggestions endpoint. A partial
// or malformed reserved code never falls back to unrelated text suggestions.
export function searchIntent(raw: string): SearchIntent {
  const query = raw.trim().normalize("NFC");
  const upper = query.toUpperCase();
  if (upper === "BX" || upper.startsWith("BX-")) {
    if (!/^[\x00-\x7f]*$/.test(query)) return "none";
    const payload = upper
      .slice(3)
      .replace(/[OIL]/g, (c) => (c === "O" ? "0" : "1"));
    return /^[0-9A-HJKMNP-TV-Z]{2,4}(?:-?[0-9A-HJKMNP-TV-Z]{0,4})?$/.test(
      payload,
    ) &&
      (!payload.includes("-") || payload.indexOf("-") === 4)
      ? "box_code"
      : "none";
  }
  return (query.match(/[\p{L}\p{N}]/gu)?.length ?? 0) >= 2 ? "text" : "none";
}

export function suggestionParams(raw: string, filters: URLSearchParams) {
  const result = new URLSearchParams({
    q: raw.trim().normalize("NFC"),
    limit: "8",
    include_archived: String(
      filters.get("archived") === "true" ||
        ["all", "archived"].includes(filters.get("lifecycle") ?? ""),
    ),
  });
  for (const key of ["tag_id", "collection_id"])
    if (filters.get(key)) result.set(key, filters.get(key)!);
  return result;
}

export function suggestionHref(item: Suggestion, filters: URLSearchParams) {
  if ((item.kind === "box" || item.kind === "item") && item.box_code)
    return "/boxes/" + encodeURIComponent(item.box_code);
  if (item.kind === "collection")
    return "/collections/" + encodeURIComponent(item.id);
  const next = new URLSearchParams();
  next.set("tag_id", item.id);
  if (filters.get("collection_id"))
    next.set("collection_id", filters.get("collection_id")!);
  if (
    filters.get("archived") === "true" ||
    ["all", "archived"].includes(filters.get("lifecycle") ?? "")
  )
    next.set("lifecycle", "all");
  return "/boxes?" + next.toString();
}

export const suggestionLabels: Record<Suggestion["kind"], string> = {
  box: "Box",
  item: "Item",
  tag: "Tag",
  collection: "Collection",
};
