import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Schema } from "./api";
import { ErrorNote, Field, Icon, PageHead } from "./components";
import { validatePayload } from "./code";
import { cameraError } from "./camera-error";
import {
  loadScannerImage,
  ScannerDecoder,
  scannerPixels,
} from "./scanner-decoder";

export function Scan() {
  const navigate = useNavigate();
  const cameraLimitation = !window.isSecureContext
    ? "Live camera scanning requires HTTPS on your local network. Upload a QR image or type the printed code; both work over HTTP."
    : !navigator.mediaDevices?.getUserMedia
      ? "Live camera access is unavailable in this browser. Upload a QR image or type the printed code instead."
      : "";
  const [tab, setTab] = useState("type"),
    [input, setInput] = useState(""),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false),
    [active, setActive] = useState(false),
    [starting, setStarting] = useState(false),
    [message, setMessage] = useState("");
  const video = useRef<HTMLVideoElement>(null),
    stream = useRef<MediaStream | null>(null),
    decoder = useRef<ScannerDecoder | null>(null),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null),
    timeout = useRef<ReturnType<typeof setTimeout> | null>(null),
    operation = useRef<AbortController | null>(null),
    cameraRequested = useRef(false),
    mounted = useRef(true);
  function releaseCamera() {
    cameraRequested.current = false;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (mounted.current) {
      setActive(false);
      setStarting(false);
    }
  }
  function stop() {
    operation.current?.abort();
    operation.current = null;
    decoder.current?.reset();
    releaseCamera();
    if (timeout.current) clearTimeout(timeout.current);
    timeout.current = null;
    if (mounted.current) {
      setBusy(false);
      setMessage("");
    }
  }
  function current(job: AbortController) {
    return mounted.current && operation.current === job && !job.signal.aborted;
  }
  function deadline(job: AbortController, delay: number, detail: string) {
    if (timeout.current) clearTimeout(timeout.current);
    timeout.current = setTimeout(() => {
      if (!current(job)) return;
      stop();
      setError(new Error(detail));
    }, delay);
  }
  function begin() {
    stop();
    const job = new AbortController();
    operation.current = job;
    setError(null);
    return job;
  }
  function fail(job: AbortController, error: unknown) {
    if (!current(job)) return;
    stop();
    setError(error);
  }
  useEffect(() => {
    mounted.current = true;
    decoder.current = new ScannerDecoder();
    const hide = () => {
      // Native photo pickers can hide the page; only live camera must stop here.
      if (document.hidden && cameraRequested.current) stop();
    };
    document.addEventListener("visibilitychange", hide);
    return () => {
      mounted.current = false;
      stop();
      document.removeEventListener("visibilitychange", hide);
    };
  }, []);
  async function resolve(value: string, job: AbortController) {
    if (!current(job)) return;
    setBusy(true);
    releaseCamera();
    deadline(
      job,
      15_000,
      "Finding this box took too long. Check the Boxen connection and try again.",
    );
    const code = await validatePayload(value);
    if (!current(job)) return;
    setMessage("Found " + code + ". Opening inventory…");
    const result = await api<Schema<"CodeResolveResult">>("/codes/resolve", {
      method: "POST",
      body: { input: code },
      signal: job.signal,
    });
    if (!current(job)) return;
    stop();
    navigator.vibrate?.(80);
    navigate("/boxes/" + result.box.code);
  }
  function decode(
    source: CanvasImageSource,
    width: number,
    height: number,
    job: AbortController,
    allowPure = false,
  ): Promise<string | null> {
    if (!decoder.current)
      throw new Error(
        "The QR reader is unavailable. Reopen Scan or type the printed code.",
      );
    return decoder.current.decode(
      scannerPixels(source, width, height),
      allowPure,
      job.signal,
    );
  }
  async function frame(job: AbortController) {
    if (!current(job) || !stream.current || !video.current) return;
    try {
      if (video.current.readyState >= 2) {
        const text = await decode(
          video.current,
          video.current.videoWidth,
          video.current.videoHeight,
          job,
        );
        if (!current(job)) return;
        if (text) {
          await resolve(text, job);
          return;
        }
      }
      if (current(job) && stream.current)
        timer.current = setTimeout(() => void frame(job), 250);
    } catch (error) {
      fail(job, error);
    }
  }
  async function start() {
    if (operation.current) return;
    if (cameraLimitation) {
      setError(new Error(cameraLimitation));
      return;
    }
    const job = begin();
    cameraRequested.current = true;
    try {
      setStarting(true);
      setMessage(
        "Opening camera… If access was previously denied, your browser may not ask again.",
      );
      deadline(
        job,
        20_000,
        "Camera access did not finish. Check this site's camera permission, take a QR photo, or type the code.",
      );
      const acquired = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
        audio: false,
      });
      if (!current(job)) {
        acquired.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = acquired;
      setStarting(false);
      setActive(true);
      if (video.current) {
        video.current.srcObject = stream.current;
        await video.current.play();
      }
      if (!current(job)) return;
      setMessage("Looking for a QR label…");
      deadline(
        job,
        30_000,
        "No QR code found in 30 seconds. Try better light, upload a clearer photo, or type the code.",
      );
      void frame(job);
    } catch (e) {
      fail(job, cameraError(e));
    }
  }
  async function upload(file?: File) {
    if (!file) return;
    const job = begin();
    setBusy(true);
    setMessage("Opening QR photo…");
    deadline(
      job,
      30_000,
      "Reading this QR photo took too long. Try a smaller image or type the printed code.",
    );
    try {
      const { image, release } = await loadScannerImage(file, job.signal);
      try {
        if (!current(job)) return;
        setMessage("Reading QR image on this device…");
        const text = await decode(
          image,
          image.naturalWidth,
          image.naturalHeight,
          job,
          true,
        );
        if (!current(job)) return;
        if (!text)
          throw new Error(
            "No QR code found. Keep the full square and its white border visible.",
          );
        await resolve(text, job);
      } finally {
        release();
      }
    } catch (e) {
      fail(job, e);
    }
  }
  function chooseFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    // Reset synchronously, so reselecting the same file triggers another change.
    event.currentTarget.value = "";
    void upload(file);
  }
  async function typeCode() {
    if (operation.current) return;
    const job = begin();
    setMessage("Checking printed code…");
    try {
      await resolve(input, job);
    } catch (error) {
      fail(job, error);
    }
  }
  return (
    <>
      <PageHead
        title="Find a box by its label"
        eyebrow="SCAN / LOCATE / RETRIEVE"
      />
      <div className="scan-layout">
        <section className="panel">
          <div className="scan-tabs" role="tablist" aria-label="Scan method">
            {[
              ["camera", "Live camera"],
              ["upload", "Upload QR image"],
              ["type", "Type code"],
            ].map(([id, label]) => (
              <button
                role="tab"
                aria-selected={tab === id}
                key={id}
                onClick={() => {
                  stop();
                  setTab(id);
                  setError(null);
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {tab === "camera" ? (
            <div className="scan-camera">
              {!cameraLimitation && (
                <>
                  <div className="viewfinder">
                    <video
                      ref={video}
                      muted
                      playsInline
                      aria-label="Local camera preview"
                    />
                    {!active && <Icon name="scan" size={100} />}
                    <div className="reticle" />
                  </div>
                  <p>
                    Place the full QR square inside the frame. Frames never
                    leave your browser.
                  </p>
                </>
              )}
              {cameraLimitation && (
                <p id="camera-limitation" role="note">
                  {cameraLimitation}
                </p>
              )}
              {!window.isSecureContext && (
                <p>
                  This HTTP page cannot request live-camera permission, so no
                  browser prompt will appear. Take QR photo opens your phone’s
                  camera or photo picker instead.
                </p>
              )}
              <button
                className="primary"
                disabled={!!cameraLimitation || busy}
                aria-describedby={
                  cameraLimitation ? "camera-limitation" : undefined
                }
                onClick={() => (active || starting ? stop() : void start())}
              >
                {starting
                  ? "Opening camera…"
                  : active
                    ? "Stop camera"
                    : "Start camera"}
              </button>
              {starting && (
                <button onClick={stop}>Cancel camera request</button>
              )}
              <label className="button primary file-button">
                Take QR photo
                <input
                  type="file"
                  accept="image/*"
                  capture="environment"
                  disabled={busy}
                  onClick={stop}
                  onChange={chooseFile}
                />
              </label>
            </div>
          ) : tab === "upload" ? (
            <div className="upload-scan">
              <Icon name="photo" size={72} />
              <h2>Read a label from a photo</h2>
              <p>The image is decoded here, not uploaded or saved.</p>
              <label className="button primary file-button">
                Choose QR image
                <input
                  type="file"
                  accept="image/*"
                  disabled={busy}
                  onChange={chooseFile}
                />
              </label>
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void typeCode();
              }}
            >
              <Field
                label="Printed box code"
                help="Letters O, I and L are accepted as 0, 1 and 1. The final character checks for typing errors."
              >
                <input
                  className="code-input"
                  autoComplete="off"
                  autoCapitalize="characters"
                  spellCheck={false}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="BX-7K3M-R9QA"
                  required
                  maxLength={64}
                />
              </Field>
              <button className="primary" disabled={busy}>
                {busy ? "Finding box…" : "Find box"}
                <Icon name="arrow" />
              </button>
            </form>
          )}
          <ErrorNote error={error} />
          <p role="status" aria-live="polite" aria-atomic="true">
            {message}
          </p>
          {busy && <button onClick={stop}>Cancel scan</button>}
        </section>
        <aside className="panel">
          <div className="eyebrow">NO INTERNET REQUIRED</div>
          <h2>
            A small label.
            <br />
            The whole inventory.
          </h2>
          <p className="muted">
            Use a label printed by this Boxen installation. You’ll see the box’s
            description, photos, and confirmed contents.
          </p>
          <p className="muted">
            On a phone, connect to the same local network. Camera scanning needs
            an HTTPS connection to your Boxen host. Uploading a QR image and
            typing its code also work over plain HTTP. Take QR photo can open
            your phone’s native camera or picker on HTTP; available choices
            depend on your phone and browser.
          </p>
        </aside>
      </div>
    </>
  );
}
