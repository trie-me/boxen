import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, cache, randomId, setSession } from "./api";

const uuid =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

afterEach(() => {
  vi.unstubAllGlobals();
  setSession(null);
  cache.clear();
});

describe("mutation IDs", () => {
  it("uses the native UUID generator in a secure context", () => {
    const native = vi.fn(() => "00000000-0000-4000-8000-000000000000");
    vi.stubGlobal("crypto", { randomUUID: native });
    expect(randomId()).toBe("00000000-0000-4000-8000-000000000000");
    expect(native).toHaveBeenCalledOnce();
  });

  it("uses 16 secure random bytes with UUID v4 version and variant on HTTP", () => {
    const fill = vi.fn((bytes: Uint8Array) => {
      for (let i = 0; i < bytes.length; i++) bytes[i] = i + 240;
      return bytes;
    });
    vi.stubGlobal("crypto", { getRandomValues: fill });
    expect(randomId()).toBe("f0f1f2f3-f4f5-46f7-b8f9-fafbfcfdfeff");
    expect(fill).toHaveBeenCalledOnce();
    expect(fill.mock.calls[0][0]).toHaveLength(16);
  });

  it("produces distinct valid IDs without randomUUID", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: webcrypto.getRandomValues.bind(webcrypto),
    });
    const keys = Array.from({ length: 100 }, () => randomId());
    keys.forEach((key) => expect(key).toMatch(uuid));
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("HTTP anonymous editor requests", () => {
  const send = vi.fn<typeof fetch>();
  beforeEach(() => {
    send.mockReset();
    send.mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", send);
    vi.stubGlobal("crypto", {
      getRandomValues: webcrypto.getRandomValues.bind(webcrypto),
    });
    setSession({
      anonymous: true,
      csrf_token: "test-csrf-token",
      expires_at: "2030-01-01T00:00:00Z",
      capabilities: [],
      user: {
        is_system_admin: false,
        local_password: true,
        id: "00000000-0000-4000-8000-000000000001",
        username: "anonymous",
        display_name: "Local access",
        role: "editor",
        status: "active",
        version: 1,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    });
  });

  it.each(["POST", "PATCH", "PUT", "DELETE"])(
    "sends %s with CSRF, cookie credentials and an HTTP-safe ID",
    async (method) => {
      await api("/boxes/BX-7K3M-R9QA", {
        method,
        body: { name: "Updated" },
        etag: '"box:v1"',
      });
      const [url, options] = send.mock.calls[0];
      expect(url).toBe("/api/v1/boxes/BX-7K3M-R9QA");
      expect(options?.method).toBe(method);
      expect(options?.credentials).toBe("same-origin");
      expect(options?.body).toBe('{"name":"Updated"}');
      const headers = new Headers(options?.headers);
      expect(headers.get("Idempotency-Key")).toMatch(uuid);
      expect(headers.get("X-CSRF-Token")).toBe("test-csrf-token");
      expect(headers.get("If-Match")).toBe('"box:v1"');
    },
  );

  it("keeps the caller's retry key and multipart body unchanged", async () => {
    const body = new FormData();
    body.set("caption", "Shelf photo");
    const key = randomId();
    for (let retry = 0; retry < 2; retry++) {
      await api("/boxes/BX-7K3M-R9QA/images", { method: "POST", body, key });
      const options = send.mock.calls[retry][1];
      expect(options?.body).toBe(body);
      const headers = new Headers(options?.headers);
      expect(headers.get("Idempotency-Key")).toBe(key);
      expect(headers.has("Content-Type")).toBe(false);
    }
  });

  it("does not add mutation headers for reads", async () => {
    await api("/boxes");
    const headers = new Headers(send.mock.calls[0][1]?.headers);
    expect(headers.has("Idempotency-Key")).toBe(false);
    expect(headers.has("X-CSRF-Token")).toBe(false);
  });
  it("preserves server validation details for the form instead of dropping them", async () => {
    const fields = [
      {
        path: "/headers/X-Boxen-Setup-Token",
        code: "value.invalid",
        message: "Use at least 43 characters.",
      },
    ];
    send.mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "request.validation",
          detail: "Correct the indicated fields.",
          request_id: "test-request",
          errors: fields,
        }),
        { status: 422 },
      ),
    );
    const error = await api("/setup/owner", { method: "POST", body: {} }).catch(
      (error: unknown) => error,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 422,
      fields,
      requestId: "test-request",
    });
  });
  it.each([null, [], "unexpected proxy response"])(
    "handles non-object error responses without losing the failure",
    async (payload) => {
      send.mockResolvedValue(
        new Response(JSON.stringify(payload), { status: 422 }),
      );
      await expect(
        api("/auth/login", { method: "POST", body: {} }),
      ).rejects.toMatchObject({
        status: 422,
        code: "request.failed",
        fields: [],
      });
    },
  );
});
