import { api, ApiError, randomId, type Schema } from "./api";

export type NamedOrganization = { id: string; name: string };
export type CollectionSummary = Schema<"CollectionSummary">;
export type CollectionLine = Schema<"CollectionItem">;
export type CollectionDetail = Schema<"CollectionDetail">;

export function updateParams(
  params: URLSearchParams,
  key: string,
  value: string,
) {
  const next = new URLSearchParams(params);
  if (value) next.set(key, value);
  else next.delete(key);
  next.delete("cursor");
  return next;
}

export function organizationQuery(params: URLSearchParams) {
  const next = new URLSearchParams();
  for (const key of ["tag_id", "collection_id"]) {
    const value = params.get(key);
    if (value) next.set(key, value);
  }
  return next.size ? "&" + next.toString() : "";
}

export function addTag(tags: string[], input: string) {
  const name = input.trim().normalize("NFC");
  if (!name) return tags;
  if ([...name].length > 64)
    throw new Error("Tags can have up to 64 characters.");
  if (tags.some((tag) => tag.toLocaleLowerCase() === name.toLocaleLowerCase()))
    return tags;
  if (tags.length >= 32) throw new Error("A box can have up to 32 tags.");
  return [...tags, name];
}

export function sameSelection(a: string[], b: string[]) {
  return a.length === b.length && a.every((value) => b.includes(value));
}

export function toggleMembership(
  selected: string[],
  code: string,
  checked: boolean,
  archived: boolean,
) {
  if (archived) return selected;
  return checked
    ? [...new Set([...selected, code])]
    : selected.filter((value) => value !== code);
}

// Publish only a complete traversal, so saving cannot drop unseen memberships.
export async function loadAllBoxes(signal?: AbortSignal) {
  const boxes = new Map<string, Schema<"BoxSummary">>();
  const visited = new Set<string>();
  let cursor: string | null | undefined;
  do {
    const page: Schema<"BoxPage"> = await api(
      "/boxes?lifecycle=all&sort=name_asc&limit=100" +
        (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
      { signal },
    );
    for (const box of page.items) boxes.set(box.code, box);
    cursor = page.page.next_cursor;
    if (cursor && visited.has(cursor))
      throw new Error(
        "The box list could not finish loading. Retry before editing membership.",
      );
    if (cursor) visited.add(cursor);
  } while (cursor);
  return [...boxes.values()];
}

export function uncertainWrite(error: unknown) {
  return (
    !(error instanceof ApiError) ||
    error.status === 0 ||
    error.status === 408 ||
    error.status >= 500
  );
}

export type OrganizationWrite = {
  path: string;
  method: string;
  etag?: string;
  body?: unknown;
};
export function freezeWrite(request: OrganizationWrite) {
  return { ...structuredClone(request), key: randomId() };
}

export function quantityLabel(
  item: Pick<Schema<"InventoryItemView">, "quantity" | "unit">,
) {
  return `${item.quantity === null ? "Unknown quantity" : item.quantity}${item.unit ? " " + item.unit : ""}`;
}

// Groups arrange original lines; quantities are never summed or items merged.
export function groupLines(
  lines: CollectionLine[],
  by: "box" | "item",
  name = "",
  source = "",
) {
  const groups = new Map<string, { label: string; lines: CollectionLine[] }>();
  for (const line of lines) {
    if (source && line.box_code !== source) continue;
    if (
      !line.item.name
        .toLocaleLowerCase()
        .includes(name.trim().toLocaleLowerCase())
    )
      continue;
    const key = by === "box" ? line.box_code : line.item.name;
    const group = groups.get(key) ?? {
      label: by === "box" ? line.box_name : line.item.name,
      lines: [],
    };
    group.lines.push(line);
    groups.set(key, group);
  }
  return [...groups.entries()].map(([key, group]) => ({ key, ...group }));
}
