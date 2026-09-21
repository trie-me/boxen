export const QR_DECODE_TIMEOUT_MS = 12_000;
export const QR_IMAGE_TIMEOUT_MS = 12_000;

const cancelled = () => new DOMException("Scan cancelled.", "AbortError");
const readerFailure = () =>
  new Error(
    "The QR reader could not start or stopped working. Try the image again, or type the printed code.",
  );

type Pending = {
  finish: (error: Error | null, text?: string | null) => void;
  send: () => void;
  id: number;
};

// One request at a time, identified across worker restarts. A failed/cancelled
// worker is discarded, so retrying cannot inherit a hung decoder or stale reply.
export class ScannerDecoder {
  private worker: Worker | null = null;
  private ready = false;
  private pending: Pending | null = null;
  private nextId = 0;

  constructor(
    private createWorker: () => Worker = () =>
      new Worker(new URL("./qr.worker.ts", import.meta.url), {
        type: "module",
      }),
    private timeoutMs = QR_DECODE_TIMEOUT_MS,
  ) {}

  decode(
    image: ImageData,
    allowPure: boolean,
    signal: AbortSignal,
  ): Promise<string | null> {
    if (signal.aborted) return Promise.reject(cancelled());
    if (this.pending)
      return Promise.reject(
        new Error(
          "The QR reader is already reading an image. Cancel it before trying another.",
        ),
      );
    return new Promise((resolve, reject) => {
      const id = ++this.nextId;
      const abort = () => this.reset(cancelled());
      const timer = setTimeout(
        () =>
          this.reset(
            new Error(
              "The QR reader took too long. Try the image again, or type the printed code.",
            ),
          ),
        this.timeoutMs,
      );
      const finish: Pending["finish"] = (error, text = null) => {
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
        this.pending = null;
        if (error) reject(error);
        else resolve(text);
      };
      const send = () => {
        try {
          this.worker!.postMessage(
            {
              id,
              data: image.data,
              width: image.width,
              height: image.height,
              allowPure,
            },
            [image.data.buffer],
          );
        } catch {
          this.reset(readerFailure());
        }
      };
      this.pending = { id, finish, send };
      signal.addEventListener("abort", abort, { once: true });
      try {
        if (!this.worker) {
          const worker = this.createWorker();
          this.worker = worker;
          worker.onerror = (event) => {
            event.preventDefault();
            if (this.worker === worker) this.reset(readerFailure());
          };
          worker.onmessageerror = () => {
            if (this.worker === worker) this.reset(readerFailure());
          };
          worker.onmessage = ({ data }) => {
            if (this.worker !== worker) return;
            if (data?.type === "ready") {
              if (!this.ready) {
                this.ready = true;
                this.pending?.send();
              }
              return;
            }
            if (!this.pending || data?.id !== this.pending.id) return;
            if (
              data.type !== "result" ||
              (data.text !== null && typeof data.text !== "string")
            ) {
              this.reset(readerFailure());
              return;
            }
            this.pending.finish(null, data.text);
          };
        }
        if (this.ready) send();
      } catch {
        this.reset(readerFailure());
      }
    });
  }

  reset(error: Error = cancelled()) {
    this.worker?.terminate();
    this.worker = null;
    this.ready = false;
    this.pending?.finish(error);
  }
}

export function scannerPixels(
  source: CanvasImageSource,
  width: number,
  height: number,
): ImageData {
  if (!width || !height || width * height > 50_000_000)
    throw new Error(
      "The image is too large or has no pixels. Choose a smaller photo.",
    );
  const scale = Math.min(1, 1600 / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context)
    throw new Error(
      "This browser could not read the image. Try another browser or type the code.",
    );
  // Photos include white quiet zones; transparent QR PNGs need the same backing.
  context.fillStyle = "white";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(source, 0, 0, canvas.width, canvas.height);
  return context.getImageData(0, 0, canvas.width, canvas.height);
}

export type ScannerImage = { image: HTMLImageElement; release: () => void };

export function loadScannerImage(
  file: File,
  signal: AbortSignal,
  timeoutMs = QR_IMAGE_TIMEOUT_MS,
): Promise<ScannerImage> {
  if (signal.aborted) return Promise.reject(cancelled());
  if (!file.size || (file.type && !file.type.startsWith("image/")))
    return Promise.reject(
      new Error("Choose a readable QR photo (JPEG, PNG or WebP)."),
    );
  if (file.size > 25 * 1024 ** 2)
    return Promise.reject(new Error("Choose a QR image smaller than 25 MB."));
  return new Promise((resolve, reject) => {
    // HTML images apply camera EXIF orientation and work without createImageBitmap.
    // A blob URL stays local; no photo is uploaded to the Boxen server.
    const image = new Image();
    const url = URL.createObjectURL(file);
    const release = () => {
      image.removeAttribute("src");
      URL.revokeObjectURL(url);
    };
    const finish = (error?: Error) => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      image.onload = image.onerror = null;
      if (error) {
        release();
        reject(error);
      } else resolve({ image, release });
    };
    const abort = () => finish(cancelled());
    const timer = setTimeout(
      () =>
        finish(
          new Error(
            "Opening this photo took too long. Try a smaller image or type the code.",
          ),
        ),
      timeoutMs,
    );
    signal.addEventListener("abort", abort, { once: true });
    image.onerror = () =>
      finish(
        new Error(
          "This photo could not be opened. Choose a JPEG, PNG or WebP image, or take another photo.",
        ),
      );
    image.onload = () => {
      if (
        !image.naturalWidth ||
        !image.naturalHeight ||
        image.naturalWidth * image.naturalHeight > 50_000_000
      )
        finish(
          new Error(
            "The image is too large or has no pixels. Choose a smaller photo.",
          ),
        );
      else finish();
    };
    image.src = url;
  });
}
