// NotAllowedError does not establish that the user clicked Deny. Browsers also
// use it for stored blocks, OS permissions and policy restrictions.
export function cameraError(error: unknown): Error {
  const failure =
    error instanceof Error || error instanceof DOMException ? error : null;
  const name = failure?.name ?? "";
  const detail = failure?.message.trim().slice(0, 240) ?? "";
  const messages: Record<string, string> = {
    NotAllowedError:
      "Camera access was blocked by your browser or phone. A saved site block or Android permission can prevent a prompt from appearing. In Chrome, open Settings → Site settings → Camera and allow this Boxen site. Also check Android Settings → Apps → Chrome → Permissions → Camera. Then return here and tap Start camera again.",
    SecurityError:
      "Your browser's security settings blocked camera access. Open Boxen directly in Chrome over HTTPS and check this site's camera permission.",
    NotFoundError:
      "No camera was found. Check that this device has an available camera, or take/upload a QR photo.",
    NotReadableError:
      "The camera could not start. Close other camera apps and check your phone's Camera access privacy toggle, then try again.",
    OverconstrainedError:
      "This camera could not satisfy the requested video settings. Try another browser or take/upload a QR photo.",
  };
  const message =
    messages[name] ??
    "The camera could not start. Try again or take/upload a QR photo.";
  return new Error(
    message +
      (name
        ? ` Browser reported: ${name}${detail ? ` — ${detail}` : ""}.`
        : ""),
  );
}
