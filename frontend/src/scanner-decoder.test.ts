import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadScannerImage, ScannerDecoder } from "./scanner-decoder";

class FakeWorker {
  onmessage: Worker["onmessage"] = null;
  onerror: Worker["onerror"] = null;
  onmessageerror: Worker["onmessageerror"] = null;
  postMessage = vi.fn();
  terminate = vi.fn();
  message(data: unknown) {
    this.onmessage?.call(this as unknown as Worker, { data } as MessageEvent);
  }
  failure(kind: "error" | "messageerror") {
    if (kind === "error")
      this.onerror?.call(
        this as unknown as AbstractWorker,
        { preventDefault: vi.fn() } as unknown as ErrorEvent,
      );
    else
      this.onmessageerror?.call(this as unknown as Worker, {} as MessageEvent);
  }
}
const pixels = () =>
  ({ data: new Uint8ClampedArray(16), width: 2, height: 2 }) as ImageData;

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("bounded worker decoding", () => {
  function fixture() {
    const workers: FakeWorker[] = [];
    const create = vi.fn(() => {
      const worker = new FakeWorker();
      workers.push(worker);
      return worker as unknown as Worker;
    });
    const decoder = new ScannerDecoder(create, 100);
    const run = (signal = new AbortController().signal) =>
      decoder.decode(pixels(), true, signal);
    return { workers, create, decoder, run };
  }

  it("waits for initialization, ignores unrelated IDs, and preserves a valid result", async () => {
    const { workers, run, decoder } = fixture();
    const result = run();
    const worker = workers[0];
    expect(worker.postMessage).not.toHaveBeenCalled();
    worker.message({ type: "ready" });
    worker.message({ type: "ready" });
    expect(worker.postMessage).toHaveBeenCalledTimes(1);
    const id = worker.postMessage.mock.calls[0][0].id;
    worker.message({ type: "result", id: id + 1, text: "wrong" });
    worker.message({ type: "result", id, text: "boxen:v1:BX-7K3M-R9QA" });
    await expect(result).resolves.toBe("boxen:v1:BX-7K3M-R9QA");
    expect(vi.getTimerCount()).toBe(0);
    decoder.reset();
  });

  it.each(["initialization", "decoding"])(
    "times out during %s and retries on a fresh worker",
    async (phase) => {
      const { workers, run, decoder } = fixture();
      const result = run();
      const rejected = expect(result).rejects.toThrow("took too long");
      if (phase === "decoding") workers[0].message({ type: "ready" });
      await vi.advanceTimersByTimeAsync(100);
      await rejected;
      expect(workers[0].terminate).toHaveBeenCalledOnce();
      const retry = run();
      const worker = workers[1];
      workers[0].message({ type: "result", id: 1, text: "late" });
      worker.message({ type: "ready" });
      const id = worker.postMessage.mock.calls[0][0].id;
      worker.message({ type: "result", id, text: null });
      await expect(retry).resolves.toBeNull();
      decoder.reset();
    },
  );

  it.each(["error", "messageerror"] as const)(
    "surfaces worker %s and releases the request",
    async (kind) => {
      const { workers, run } = fixture();
      const result = run();
      workers[0].failure(kind);
      await expect(result).rejects.toThrow(
        "could not start or stopped working",
      );
      expect(workers[0].terminate).toHaveBeenCalledOnce();
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("turns constructor and postMessage failures into finite errors", async () => {
    const decoder = new ScannerDecoder(() => {
      throw new Error("blocked");
    }, 100);
    await expect(
      decoder.decode(pixels(), true, new AbortController().signal),
    ).rejects.toThrow("could not start");
    const { workers, run } = fixture();
    const result = run();
    workers[0].postMessage.mockImplementation(() => {
      throw new Error("clone failed");
    });
    workers[0].message({ type: "ready" });
    await expect(result).rejects.toThrow("could not start");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("rejects malformed replies instead of leaving the promise pending", async () => {
    const { workers, run } = fixture();
    const result = run();
    workers[0].message({ type: "ready" });
    workers[0].message({ type: "result", id: 1, text: 42 });
    await expect(result).rejects.toThrow("stopped working");
  });

  it("does not overwrite an in-flight callback and cancels it on reset", async () => {
    const { run, decoder, workers } = fixture();
    const first = run();
    await expect(run()).rejects.toThrow("already reading");
    decoder.reset();
    await expect(first).rejects.toMatchObject({ name: "AbortError" });
    expect(workers[0].terminate).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("aborts pending work and never starts a previously aborted request", async () => {
    const { run, workers } = fixture();
    const controller = new AbortController();
    const result = run(controller.signal);
    controller.abort();
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
    await expect(run(controller.signal)).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(workers).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("local photo loading", () => {
  function fixture() {
    const images: Array<{
      naturalWidth: number;
      naturalHeight: number;
      src: string;
      onload: (() => void) | null;
      onerror: (() => void) | null;
      removeAttribute: ReturnType<typeof vi.fn>;
    }> = [];
    vi.stubGlobal("createImageBitmap", undefined);
    vi.stubGlobal(
      "Image",
      class {
        naturalWidth = 30;
        naturalHeight = 20;
        src = "";
        onload = null;
        onerror = null;
        removeAttribute = vi.fn();
        constructor() {
          images.push(this);
        }
      },
    );
    const create = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:local-photo");
    const revoke = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => {});
    const controller = new AbortController();
    const file = new File(["photo"], "qr.jpg", { type: "image/jpeg" });
    const run = () => loadScannerImage(file, controller.signal, 100);
    return { images, create, revoke, controller, file, run };
  }

  it("loads locally without ImageBitmap and explicitly releases the photo", async () => {
    const { images, revoke, run } = fixture();
    const pending = run();
    expect(images[0].src).toBe("blob:local-photo");
    images[0].onload?.();
    const result = await pending;
    expect(result.image).toBe(images[0]);
    expect(vi.getTimerCount()).toBe(0);
    result.release();
    expect(revoke).toHaveBeenCalledWith("blob:local-photo");
    expect(images[0].removeAttribute).toHaveBeenCalledWith("src");
  });

  it.each(["invalid", "timeout", "abort", "oversize"])(
    "cleans up a photo after %s",
    async (failure) => {
      const { images, revoke, controller, run } = fixture();
      const pending = run();
      const rejected = expect(pending).rejects.toThrow();
      if (failure === "invalid") images[0].onerror?.();
      if (failure === "timeout") await vi.advanceTimersByTimeAsync(100);
      if (failure === "abort") controller.abort();
      if (failure === "oversize") {
        images[0].naturalWidth = 3_000_000;
        images[0].onload?.();
      }
      await rejected;
      expect(revoke).toHaveBeenCalledOnce();
      expect(images[0].onload).toBeNull();
      expect(images[0].onerror).toBeNull();
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("rejects empty, non-image and oversized files before allocating a URL", async () => {
    const { create, controller } = fixture();
    for (const file of [
      new File([], "empty.png"),
      new File(["text"], "a.txt", { type: "text/plain" }),
      { size: 26 * 1024 ** 2, type: "image/jpeg" } as File,
    ])
      await expect(loadScannerImage(file, controller.signal)).rejects.toThrow();
    expect(create).not.toHaveBeenCalled();
  });
});
