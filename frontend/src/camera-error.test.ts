import { describe, expect, it } from "vitest";
import { cameraError } from "./camera-error";

describe("camera failure feedback", () => {
  it("does not claim the user denied an unseen permission prompt", () => {
    const message = cameraError(
      new DOMException("Permission denied by system", "NotAllowedError"),
    ).message;
    expect(message).toContain(
      "A saved site block or Android permission can prevent a prompt",
    );
    expect(message).toContain("Site settings → Camera");
    expect(message).toContain("Apps → Chrome → Permissions → Camera");
    expect(message).toContain("NotAllowedError — Permission denied by system");
    expect(message).not.toContain("Camera permission was denied");
  });
  it.each([
    ["SecurityError", "security settings"],
    ["NotFoundError", "No camera was found"],
    ["NotReadableError", "Close other camera apps"],
    ["OverconstrainedError", "video settings"],
  ])("explains %s separately", (name, text) => {
    expect(cameraError(new DOMException("detail", name)).message).toContain(
      text,
    );
  });
  it("bounds browser detail and handles unknown failures", () => {
    expect(
      cameraError(new Error("x".repeat(1000))).message.length,
    ).toBeLessThan(400);
    expect(cameraError(null).message).toContain("The camera could not start");
  });
});
