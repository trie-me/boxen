import { ApiError } from "./api";

export type AuthField = "token" | "username" | "display_name" | "password";
export type AuthValues = Record<AuthField, string>;
export type AuthErrors = Partial<Record<AuthField, string>>;
export const authOrder: AuthField[] = [
  "token",
  "username",
  "display_name",
  "password",
];

export function authValues(form: FormData): AuthValues {
  const get = (name: AuthField) => String(form.get(name) ?? "");
  return {
    token: get("token").trim(),
    username: get("username").trim(),
    display_name: get("display_name").trim(),
    password: get("password"),
  };
}

export function validateAuth(values: AuthValues, setup: boolean): AuthErrors {
  const errors: AuthErrors = {};
  const usernameLength = [...values.username].length;
  if (usernameLength < 3 || usernameLength > 64)
    errors.username = "Use a username with 3–64 characters.";
  else if (setup && !/^[\p{L}\p{N}_.-]+$/u.test(values.username))
    errors.username =
      "Use letters, numbers, underscores, dots, or hyphens; no spaces or @ signs.";
  const passwordLength = [...values.password].length;
  if (passwordLength < (setup ? 12 : 1))
    errors.password = setup
      ? "Use a password with at least 12 characters."
      : "Enter your password.";
  else if (
    passwordLength > 1024 ||
    (setup && new TextEncoder().encode(values.password).length > 1024)
  )
    errors.password = setup
      ? "Use a password no larger than 1024 UTF-8 bytes."
      : "Use a password with no more than 1024 characters.";
  if (setup) {
    if (!values.token)
      errors.token = "Enter the one-time setup token from your Boxen host.";
    else if (values.token.length < 43 || values.token.length > 256)
      errors.token =
        "Paste the complete one-time setup token (43–256 characters), not your password.";
    if (
      !values.display_name ||
      [...values.display_name].length > 120 ||
      /[\p{Cc}\p{Cs}]/u.test(values.display_name)
    )
      errors.display_name =
        "Enter a display name with 1–120 characters and no control characters.";
  }
  return errors;
}

export function authServerErrors(error: unknown, setup: boolean): AuthErrors {
  if (!(error instanceof ApiError)) return {};
  const errors: AuthErrors = {};
  for (const field of error.fields) {
    const name =
      field.path === "/headers/X-Boxen-Setup-Token"
        ? "token"
        : field.path.slice(1);
    if (
      authOrder.includes(name as AuthField) &&
      (setup || name === "username" || name === "password")
    )
      errors[name as AuthField] = field.message;
  }
  // Domain failures also identify a field when an older backend lacks paths.
  if (setup && error.code.startsWith("setup.token"))
    errors.token = error.message;
  if (
    ["user.username_invalid", "user.username_taken", "user.reserved"].includes(
      error.code,
    )
  )
    errors.username = error.message;
  if (error.code.startsWith("user.password_")) errors.password = error.message;
  return errors;
}
