import { describe, expect, it } from "vitest";
import { ApiError, fieldErrors } from "./api";
import {
  authServerErrors,
  authValues,
  validateAuth,
  type AuthValues,
} from "./auth-validation";

const valid: AuthValues = {
  token: "fixture-token-" + "x".repeat(32),
  username: "local.owner",
  display_name: "Local owner",
  password: "test-only-password-12",
};

describe("auth field validation", () => {
  it("accepts valid setup and login without setup-only fields", () => {
    expect(validateAuth(valid, true)).toEqual({});
    expect(
      validateAuth(
        { ...valid, token: "", display_name: "", password: "x" },
        false,
      ),
    ).toEqual({});
  });
  it("reports every missing field, not an empty generic alert", () => {
    expect(
      Object.keys(
        validateAuth(
          { token: "", username: "", display_name: "", password: "" },
          true,
        ),
      ).sort(),
    ).toEqual(["display_name", "password", "token", "username"]);
  });
  it.each(["short", "x".repeat(257)])(
    "identifies incomplete/oversized setup tokens without echoing them",
    (token) => {
      const errors = validateAuth({ ...valid, token }, true);
      expect(errors.token).toContain("complete one-time setup token");
      expect(JSON.stringify(errors)).not.toContain(token);
    },
  );
  it.each(["ab", "x".repeat(65), "local owner", "me@example.test"])(
    "shows invalid username rules",
    (username) => {
      expect(validateAuth({ ...valid, username }, true).username).toBeTruthy();
    },
  );
  it("accepts Unicode letters/numbers without imposing ASCII-only accounts", () => {
    expect(
      validateAuth({ ...valid, username: "Élodie.用户_12" }, true),
    ).toEqual({});
  });
  it.each(["", "x".repeat(121), "line\nbreak"])(
    "rejects invalid display names",
    (display_name) => {
      expect(
        validateAuth({ ...valid, display_name }, true).display_name,
      ).toBeTruthy();
    },
  );
  it("matches setup password UTF-8 byte limits without trimming", () => {
    expect(
      validateAuth({ ...valid, password: "🔑".repeat(256) }, true).password,
    ).toBeUndefined();
    expect(
      validateAuth({ ...valid, password: "🔑".repeat(257) }, true).password,
    ).toContain("1024 UTF-8 bytes");
    expect(
      validateAuth({ ...valid, password: "short" }, true).password,
    ).toContain("at least 12");
  });
  it("reads pasted/autofilled form values and trims only non-password fields", () => {
    const form = new FormData();
    form.set("username", " local.owner ");
    form.set("display_name", " Local owner ");
    form.set("token", "\n" + valid.token + "\n");
    form.set("password", "  password-with-spaces  ");
    expect(authValues(form)).toEqual({
      ...valid,
      password: "  password-with-spaces  ",
    });
  });
  it("maps server header and body paths to visible inputs", () => {
    expect(
      authServerErrors(
        new ApiError(422, "request.validation", "Correct the fields.", "id", [
          {
            path: "/headers/X-Boxen-Setup-Token",
            code: "value.invalid",
            message: "Use the complete host token.",
          },
          {
            path: "/password",
            code: "value.invalid",
            message: "At least 12 characters.",
          },
          {
            path: "/display_name",
            code: "value.invalid",
            message: "A name is required.",
          },
        ]),
        true,
      ),
    ).toEqual({
      token: "Use the complete host token.",
      password: "At least 12 characters.",
      display_name: "A name is required.",
    });
  });
  it.each([
    ["setup.token_invalid", "token"],
    ["user.username_invalid", "username"],
    ["user.username_taken", "username"],
    ["user.password_common", "password"],
  ])("maps %s domain failures from older responses", (code, field) => {
    expect(
      authServerErrors(new ApiError(422, code, "Actionable error"), true),
    ).toEqual({ [field]: "Actionable error" });
  });
  it("keeps credential failure generic rather than claiming which credential is wrong", () => {
    expect(
      authServerErrors(
        new ApiError(
          401,
          "auth.invalid_credentials",
          "Sign-in details were not accepted.",
        ),
        false,
      ),
    ).toEqual({});
  });
  it("does not map setup-only fields onto login", () => {
    expect(
      authServerErrors(
        new ApiError(422, "request.validation", "Invalid", undefined, [
          {
            path: "/headers/X-Boxen-Setup-Token",
            code: "value.invalid",
            message: "Token required",
          },
        ]),
        false,
      ),
    ).toEqual({});
  });
  it("ignores malformed field details and bounds their count", () => {
    expect(fieldErrors(null)).toEqual([]);
    expect(
      fieldErrors([
        null,
        {},
        { path: "/password", code: "invalid", message: 123 },
      ]),
    ).toEqual([]);
    expect(
      fieldErrors(
        Array.from({ length: 50 }, () => ({
          path: "/username",
          code: "invalid",
          message: "Required.",
        })),
      ),
    ).toHaveLength(20);
  });
});
