import { useEffect, useRef, useState } from "react";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ErrorNote, Loading } from "./components";

GlobalWorkerOptions.workerSrc = workerUrl;
export default function PdfPreview({ url }: { url: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState<unknown>(),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const task = getDocument({
      url,
      withCredentials: true,
      useSystemFonts: false,
    });
    void (async () => {
      try {
        const document = await task.promise;
        const page = await document.getPage(1);
        if (cancelled || !canvas.current) return;
        const viewport = page.getViewport({ scale: 2 });
        canvas.current.width = viewport.width;
        canvas.current.height = viewport.height;
        await page.render({ canvas: canvas.current, viewport }).promise;
        if (!cancelled) setLoading(false);
      } catch (error) {
        if (!cancelled) {
          setError(error);
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
      void task.destroy();
    };
  }, [url]);
  return (
    <div className="pdf-preview">
      {loading && <Loading label="Rendering the printable label…" />}
      <ErrorNote error={error} />
      <canvas
        ref={canvas}
        role="img"
        aria-label="Exact PDF label preview, including QR code, box name, and typeable code"
      />
    </div>
  );
}
