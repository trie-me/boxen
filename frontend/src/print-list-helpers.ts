export const MAX_PINS = 500;
export function readPins(raw: string | null): string[] {
  try {
    const value: unknown = JSON.parse(raw ?? "[]");
    if (!Array.isArray(value)) return [];
    return [
      ...new Set(
        value.filter(
          (code): code is string =>
            typeof code === "string" &&
            /^BX-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$/.test(code),
        ),
      ),
    ].slice(0, MAX_PINS);
  } catch {
    return [];
  }
}
export function mergePins(current: string[], added: string[]) {
  const result = [...new Set([...current, ...added])];
  return result.length > MAX_PINS ? current : result;
}
export function sheetCount(count: number, start: number) {
  return count ? Math.ceil((count + start - 1) / 10) : 0;
}
