import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";

const origin = "http://boxen.test:8174";
test.skip(
  ({ baseURL }) => baseURL !== origin,
  "Run with playwright.scanner.config.ts",
);

function photo(code: string, oriented = false) {
  return {
    name: oriented ? "phone-photo.jpg" : "label.png",
    mimeType: oriented ? "image/jpeg" : "image/png",
    buffer: execFileSync("../.venv/bin/python", [
      "-c",
      oriented
        ? 'import segno,sys,io; from PIL import Image; b=io.BytesIO(); segno.make_qr(sys.argv[1],error="q").save(b,kind="png",scale=8,border=4); b.seek(0); qr=Image.open(b).convert("RGB"); im=Image.new("RGB",(qr.width+160,qr.height+80),"white"); im.paste(qr,(80,40)); im=im.transpose(Image.Transpose.ROTATE_90); exif=Image.Exif(); exif[274]=6; im.save(sys.stdout.buffer,format="JPEG",quality=98,exif=exif)'
        : 'import segno,sys; segno.make_qr(sys.argv[1],error="q").save(sys.stdout.buffer,kind="png",scale=8,border=4)',
      "boxen:v1:" + code,
    ]),
  };
}

async function createBox(page: Page, name: string) {
  await page.goto("/boxes/new");
  await page.getByLabel("Box name").fill(name);
  await page.getByRole("button", { name: "Create box", exact: true }).click();
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  return { url: page.url(), code: page.url().split("/").at(-1)! };
}
async function uploadTab(page: Page) {
  await page.goto("/scan");
  await page.getByRole("tab", { name: "Upload QR image" }).click();
}

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  const outbound: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["blob:", "data:"].includes(url.protocol) && url.origin !== origin)
      outbound.push(request.url());
  });
  // Include unhandled promise rejections and forbid photo/network decoding services.
  errorRecords.set(page, { errors, outbound });
});
const errorRecords = new WeakMap<
  Page,
  { errors: string[]; outbound: string[] }
>();
test.afterEach(async ({ page }) => {
  const record = errorRecords.get(page);
  if (!record) return;
  expect(record.errors).toEqual([]);
  expect(record.outbound).toEqual([]);
});

test("HTTP offers native capture without a live-camera prompt and decodes its selected photo", async ({
  page,
}) => {
  const box = await createBox(page, "HTTP native capture");
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/scan");
  expect(
    await page.evaluate(() => ({
      secure: isSecureContext,
      media: typeof navigator.mediaDevices,
    })),
  ).toEqual({ secure: false, media: "undefined" });
  await page.getByRole("tab", { name: "Live camera" }).click();
  await expect(
    page.getByRole("button", { name: "Start camera" }),
  ).toBeDisabled();
  await expect(page.getByText(/no browser prompt will appear/)).toBeVisible();
  const capture = page.getByLabel("Take QR photo", { exact: true });
  await expect(capture).toHaveAttribute("accept", "image/*");
  await expect(capture).toHaveAttribute("capture", "environment");
  await expect(capture).toBeEnabled();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results-scanner/http-photo-capture.png",
    fullPage: true,
  });
  // Supplying a file proves the pipeline, not any physical phone picker UI.
  await capture.setInputFiles(photo(box.code));
  await expect(page).toHaveURL(box.url);
});

test("an EXIF-oriented phone JPEG decodes without createImageBitmap", async ({
  page,
}) => {
  await page.addInitScript(() =>
    Object.defineProperty(window, "createImageBitmap", { value: undefined }),
  );
  const box = await createBox(page, "Oriented phone photo");
  await uploadTab(page);
  await page
    .getByLabel("Choose QR image", { exact: true })
    .setInputFiles(photo(box.code, true));
  await expect(page).toHaveURL(box.url);
});

type WorkerMode =
  | "native"
  | "constructor"
  | "error"
  | "messageerror"
  | "silent-init"
  | "silent-decode";
type WorkerFixture = {
  scannerMode: WorkerMode;
  scannerWorkers: number;
  scannerTerminations: number;
};
async function workerFixture(page: Page, mode: WorkerMode) {
  await page.addInitScript((initialMode) => {
    const fixture = window as unknown as WorkerFixture;
    fixture.scannerMode = initialMode;
    fixture.scannerWorkers = fixture.scannerTerminations = 0;
    const NativeWorker = Worker;
    window.Worker = new Proxy(NativeWorker, {
      construct(target, args) {
        if (fixture.scannerMode === "native")
          return Reflect.construct(target, args);
        fixture.scannerWorkers++;
        if (fixture.scannerMode === "constructor")
          throw new Error("Fixture worker constructor failure");
        const worker = {
          onmessage: null as Worker["onmessage"],
          onerror: null as Worker["onerror"],
          onmessageerror: null as Worker["onmessageerror"],
          postMessage() {},
          terminate() {
            fixture.scannerTerminations++;
          },
        };
        const fake = worker as unknown as Worker;
        setTimeout(() => {
          if (fixture.scannerMode === "error")
            fake.onerror?.(
              new ErrorEvent("error", { message: "fixture crash" }),
            );
          if (fixture.scannerMode === "messageerror")
            fake.onmessageerror?.(new MessageEvent("messageerror"));
          if (fixture.scannerMode === "silent-decode")
            fake.onmessage?.(
              new MessageEvent("message", { data: { type: "ready" } }),
            );
        }, 0);
        return worker;
      },
    });
  }, mode);
}

for (const mode of [
  "constructor",
  "error",
  "messageerror",
  "silent-init",
  "silent-decode",
] as const) {
  test(`worker ${mode} fails visibly and the same file retries with a fresh reader`, async ({
    page,
  }) => {
    await workerFixture(page, mode);
    const box = await createBox(page, "Retry " + mode);
    await uploadTab(page);
    if (mode.startsWith("silent")) await page.clock.install();
    const input = page.getByLabel("Choose QR image", { exact: true });
    const file = photo(box.code);
    await input.setInputFiles(file);
    if (mode.startsWith("silent")) {
      await expect(page.getByRole("main").getByRole("status")).toHaveText(
        "Reading QR image on this device…",
      );
      await expect(input).toBeDisabled();
      await expect(
        page.getByRole("button", { name: "Cancel scan" }),
      ).toBeVisible();
      await page.clock.fastForward(12_100);
    }
    await expect(page.getByRole("alert")).toContainText(
      mode.startsWith("silent")
        ? "reader took too long"
        : "reader could not start or stopped working",
    );
    await expect(input).toBeEnabled();
    await expect(input).toHaveValue("");
    await expect(page.getByRole("main").getByRole("status")).toBeEmpty();
    await page.evaluate(() => {
      (window as unknown as WorkerFixture).scannerMode = "native";
    });
    await input.setInputFiles(file);
    await expect(page).toHaveURL(box.url);
  });
}

test("invalid photo and cancelled picker leave a same-file retry available", async ({
  page,
}) => {
  await uploadTab(page);
  const input = page.getByLabel("Choose QR image", { exact: true });
  await input.setInputFiles([]);
  await expect(page.getByRole("button", { name: "Cancel scan" })).toHaveCount(
    0,
  );
  for (let i = 0; i < 2; i++) {
    await input.setInputFiles({
      name: "bad.png",
      mimeType: "image/png",
      buffer: Buffer.from("not a photo"),
    });
    await expect(page.getByRole("alert")).toContainText(
      "photo could not be opened",
    );
    await expect(input).toHaveValue("");
    await expect(input).toBeEnabled();
  }
});

test("cancelling a pending decode allows immediate same-file retry without stale busy state", async ({
  page,
}) => {
  await workerFixture(page, "silent-decode");
  const box = await createBox(page, "Cancelled image retry");
  await uploadTab(page);
  const file = photo(box.code);
  await page.getByLabel("Choose QR image", { exact: true }).setInputFiles(file);
  await expect(page.getByRole("main").getByRole("status")).toHaveText(
    "Reading QR image on this device…",
  );
  await page.getByRole("button", { name: "Cancel scan" }).click();
  await expect(page.getByRole("main").getByRole("status")).toBeEmpty();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.evaluate(() => {
    (window as unknown as WorkerFixture).scannerMode = "native";
  });
  await page.getByLabel("Choose QR image", { exact: true }).setInputFiles(file);
  await expect(page).toHaveURL(box.url);
});

test("changing methods cancels a hung decoder so typed lookup can complete", async ({
  page,
}) => {
  await workerFixture(page, "silent-decode");
  const box = await createBox(page, "New scan owns result");
  await uploadTab(page);
  await page
    .getByLabel("Choose QR image", { exact: true })
    .setInputFiles(photo(box.code));
  await expect(page.getByRole("main").getByRole("status")).toHaveText(
    "Reading QR image on this device…",
  );
  await page.getByRole("tab", { name: "Type code" }).click();
  await page.getByLabel("Printed box code").fill(box.code);
  await page.getByRole("button", { name: "Find box", exact: true }).click();
  await expect(page).toHaveURL(box.url);
});

type CameraFixture = {
  scannerStreams: MediaStream[];
  scannerDelay: boolean;
  scannerRelease?: () => void;
  scannerDeny: boolean;
};
async function cameraFixture(page: Page, deny = false) {
  await page.addInitScript((denied) => {
    // Simulate secure-context camera capabilities only inside this test page.
    // This does not establish HTTPS, alter browser security, or use a real camera.
    Object.defineProperty(window, "isSecureContext", { value: true });
    const fixture = window as unknown as CameraFixture;
    fixture.scannerStreams = [];
    fixture.scannerDelay = false;
    fixture.scannerDeny = denied;
    Object.defineProperty(navigator, "mediaDevices", {
      value: {
        getUserMedia: async () => {
          if (fixture.scannerDeny)
            throw new DOMException("Fixture denial", "NotAllowedError");
          const canvas = document.createElement("canvas");
          canvas.width = 320;
          canvas.height = 240;
          canvas.getContext("2d")!.fillRect(0, 0, 320, 240);
          const stream = canvas.captureStream(5);
          fixture.scannerStreams.push(stream);
          if (fixture.scannerDelay)
            await new Promise<void>((resolve) => {
              fixture.scannerRelease = resolve;
            });
          return stream;
        },
      },
    });
  }, deny);
}
async function allTracksEnded(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window as unknown as CameraFixture).scannerStreams.every((stream) =>
          stream.getTracks().every((track) => track.readyState === "ended"),
        ),
      ),
    )
    .toBe(true);
}

test("denied camera permission reports a useful error with photo and type alternatives", async ({
  page,
}) => {
  await cameraFixture(page, true);
  await page.goto("/scan");
  await page.getByRole("tab", { name: "Live camera" }).click();
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Camera access was blocked by your browser or phone",
  );
  await expect(page.getByLabel("Take QR photo", { exact: true })).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Start camera" }),
  ).toBeEnabled();
  await page.getByRole("tab", { name: "Type code" }).click();
  await expect(page.getByLabel("Printed box code")).toBeVisible();
});

test("camera stops tracks after stop, method change, unmount and late permission", async ({
  page,
}) => {
  await cameraFixture(page);
  await page.goto("/scan");
  for (const action of ["stop", "method", "unmount"]) {
    await page.getByRole("tab", { name: "Live camera" }).click();
    await page.getByRole("button", { name: "Start camera" }).click();
    await expect(
      page.getByRole("button", { name: "Stop camera" }),
    ).toBeVisible();
    if (action === "stop")
      await page.getByRole("button", { name: "Stop camera" }).click();
    if (action === "method")
      await page.getByRole("tab", { name: "Type code" }).click();
    if (action === "unmount")
      await page
        .getByRole("link", { name: "Boxes", exact: true })
        .first()
        .click();
    await allTracksEnded(page);
  }
  await page.getByRole("link", { name: "Scan", exact: true }).first().click();
  await page.evaluate(() => {
    (window as unknown as CameraFixture).scannerDelay = true;
  });
  await page.getByRole("tab", { name: "Live camera" }).click();
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(
    page.getByRole("button", { name: "Opening camera…" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Boxes", exact: true }).first().click();
  await page.evaluate(() =>
    (window as unknown as CameraFixture).scannerRelease?.(),
  );
  await allTracksEnded(page);
});

test("an unanswered camera request has a deadline and closes a late stream", async ({
  page,
}) => {
  await cameraFixture(page);
  await page.goto("/scan");
  await page.clock.install();
  await page.evaluate(() => {
    (window as unknown as CameraFixture).scannerDelay = true;
  });
  await page.getByRole("tab", { name: "Live camera" }).click();
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(
    page.getByRole("button", { name: "Opening camera…" }),
  ).toBeVisible();
  await page.clock.fastForward(20_100);
  await expect(page.getByRole("alert")).toContainText(
    "Camera access did not finish",
  );
  await page.evaluate(() =>
    (window as unknown as CameraFixture).scannerRelease?.(),
  );
  await allTracksEnded(page);
  await expect(
    page.getByRole("button", { name: "Start camera" }),
  ).toBeEnabled();
});

test("hiding the page cancels pending camera permission and closes a late grant", async ({
  page,
}) => {
  await cameraFixture(page);
  await page.goto("/scan");
  await page.evaluate(() => {
    (window as unknown as CameraFixture).scannerDelay = true;
  });
  await page.getByRole("tab", { name: "Live camera" }).click();
  await page.getByRole("button", { name: "Start camera" }).click();
  await expect(
    page.getByRole("button", { name: "Opening camera…" }),
  ).toBeVisible();
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
    (window as unknown as CameraFixture).scannerRelease?.();
  });
  await allTracksEnded(page);
  await expect(
    page.getByRole("button", { name: "Start camera" }),
  ).toBeEnabled();
  await expect(page.getByRole("main").getByRole("status")).toBeEmpty();
});
