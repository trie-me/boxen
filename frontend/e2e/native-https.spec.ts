import { test, expect } from "@playwright/test";

// Opt-in: run only against a disposable fixture behind the native TLS proxy.
test.skip(
  ({ baseURL }) => baseURL !== process.env.BOXEN_TEST_HTTPS_ORIGIN,
  "Run with playwright.https.config.ts against a disposable backend",
);

test("trusted LAN HTTPS permits anonymous writes and a live camera stream", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Find what you stored." }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => ({
      secure: isSecureContext,
      camera: typeof navigator.mediaDevices?.getUserMedia,
    })),
  ).toEqual({ secure: true, camera: "function" });
  await page.getByRole("link", { name: "New box", exact: true }).click();
  await page.getByLabel("Box name").fill("HTTPS disposable camera test");
  await page.getByRole("button", { name: "Create box", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "HTTPS disposable camera test",
      exact: true,
    }),
  ).toBeVisible();
  const cookies = await context.cookies();
  expect(cookies.some((cookie) => cookie.httpOnly && cookie.secure)).toBe(true);
  await context.grantPermissions(["camera"]);
  await page.goto("/scan");
  await page.getByRole("tab", { name: "Live camera", exact: true }).click();
  const start = page.getByRole("button", { name: "Start camera", exact: true });
  await expect(start).toBeEnabled();
  await start.click();
  await expect(
    page.getByRole("button", { name: "Stop camera", exact: true }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => {
        const video = document.querySelector("video");
        const stream = video?.srcObject as MediaStream | null;
        return (
          !!stream?.active &&
          stream
            .getVideoTracks()
            .some((track) => track.readyState === "live") &&
          !!video?.videoWidth
        );
      }),
    )
    .toBe(true);
  await page.evaluate(() => {
    const video = document.querySelector("video")!;
    (window as unknown as { testTracks: MediaStreamTrack[] }).testTracks = (
      video.srcObject as MediaStream
    ).getTracks();
  });
  await page.getByRole("button", { name: "Stop camera", exact: true }).click();
  await expect(start).toBeEnabled();
  expect(
    await page.evaluate(() =>
      (
        window as unknown as { testTracks: MediaStreamTrack[] }
      ).testTracks.every((track) => track.readyState === "ended"),
    ),
  ).toBe(true);
});
