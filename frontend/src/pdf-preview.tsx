import { useEffect, useRef, useState } from "react";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ErrorNote, Loading } from "./components";

GlobalWorkerOptions.workerSrc = workerUrl;
type PreviewProps = { url: string; data?: Uint8Array };
export default function PdfPreview({ url, data }: PreviewProps) {
  return <PdfPages key={url} url={url} data={data} />;
}
function PdfPages({ url, data }: PreviewProps) {
  const [pageNumber, setPageNumber] = useState(1);
  const [pageCount, setPageCount] = useState(1);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState<unknown>(),
    [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const task = getDocument({
      // Copy because PDF.js transfers ownership of the buffer to its worker.
      ...(data ? { data: data.slice() } : { url }),
      withCredentials: true,
      useSystemFonts: false,
    });
    void (async () => {
      try {
        const document = await task.promise;
        if (cancelled) return;
        setPageCount(document.numPages);
        const page = await document.getPage(pageNumber);
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
  }, [url, data, pageNumber]);
  return (
    <div className="pdf-preview">
      {pageCount > 1 && (
        <div className="pdf-pagination">
          <button
            disabled={pageNumber === 1 || loading}
            onClick={() => setPageNumber((page) => page - 1)}
          >
            Previous page
          </button>
          <span aria-live="polite">
            Page {pageNumber} of {pageCount}
          </span>
          <button
            disabled={pageNumber === pageCount || loading}
            onClick={() => setPageNumber((page) => page + 1)}
          >
            Next page
          </button>
        </div>
      )}
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
