import { QueryClient } from "@tanstack/react-query";
import type { components } from "./contracts";

export type Schema<K extends keyof components["schemas"]> =
  components["schemas"][K];
export type Session = Schema<"SessionView">;
export type Box = Schema<"BoxDetail">;
export type Item = Schema<"InventoryItemView">;
export type Photo = Schema<"ImageView">;
export const cache = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2,
      refetchOnWindowFocus: true,
    },
    mutations: { retry: false },
  },
});
let csrf = "";
export function setSession(session: Session | null) {
  csrf = session?.csrf_token ?? "";
  cache.setQueryData(["session"], session);
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public requestId?: string,
    public fields: Schema<"FieldError">[] = [],
  ) {
    super(message);
  }
}

export function fieldErrors(value: unknown): Schema<"FieldError">[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(
      (field): field is Schema<"FieldError"> =>
        field !== null &&
        typeof field === "object" &&
        typeof field.path === "string" &&
        typeof field.code === "string" &&
        typeof field.message === "string",
    )
    .slice(0, 20);
}
// getRandomValues is available on plain HTTP; randomUUID requires a secure
// context. Keep mutation and upload retry keys cryptographically random in both.
export function randomId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10).join(""),
  ].join("-");
}
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    etag?: string;
    headers?: Record<string, string>;
    key?: string;
    signal?: AbortSignal;
    responseType?: "blob";
  } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  const upload = options.body instanceof FormData;
  if (options.body !== undefined && !upload)
    headers.set("Content-Type", "application/json");
  if (method !== "GET") {
    headers.set("X-CSRF-Token", csrf);
    headers.set("Idempotency-Key", options.key ?? randomId());
  }
  if (options.etag) headers.set("If-Match", options.etag);
  let response: Response;
  try {
    response = await fetch("/api/v1" + path, {
      method,
      headers,
      credentials: "same-origin",
      body: upload
        ? (options.body as FormData)
        : options.body === undefined
          ? undefined
          : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new ApiError(
      0,
      "host.unavailable",
      "Boxen host unavailable. Your unsaved changes are still on this device.",
    );
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const error =
      payload && typeof payload === "object" && !Array.isArray(payload)
        ? payload
        : {};
    if (response.status === 401 && path !== "/auth/login")
      window.dispatchEvent(new Event("boxen-session-expired"));
    throw new ApiError(
      response.status,
      error.code ?? "request.failed",
      error.detail ?? "The request could not complete.",
      error.request_id,
      fieldErrors(error.errors),
    );
  }
  if (options.responseType === "blob") return (await response.blob()) as T;
  return response.status === 204 ? (undefined as T) : response.json();
}
export const tag = (kind: string, id: string, version: number) =>
  `"${kind}:${id}:v${version}"`;
export function changed() {
  return cache.invalidateQueries({
    predicate: (q) => q.queryKey[0] !== "session",
  });
}
export function query<T>(path: string) {
  return {
    queryKey: [path],
    queryFn: ({ signal }: { signal: AbortSignal }) => api<T>(path, { signal }),
  };
}
