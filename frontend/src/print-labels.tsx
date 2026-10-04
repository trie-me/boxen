import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, query, type Schema } from "./api";
import { Empty, ErrorNote, Field, Loading, PageHead } from "./components";
import { loadAllBoxes } from "./organization-helpers";
import { usePrintList } from "./print-list";
import { sheetCount, MAX_PINS } from "./print-list-helpers";
import { useSession } from "./session";
import "./print-labels.css";
const PdfPreview = lazy(() => import("./pdf-preview"));

export function PrintLabels() {
  const { collectionId } = useParams();
  const list = usePrintList();
  const editor = useSession().user.role !== "viewer";
  const collection = useQuery({
    ...query<Schema<"CollectionDetail">>("/collections/" + collectionId),
    enabled: editor && !!collectionId,
    refetchOnMount: "always",
  });
  const boxes = useQuery({
    queryKey: ["organization-all-boxes"],
    queryFn: ({ signal }) => loadAllBoxes(signal),
    enabled: editor && !collectionId && list.codes.length > 0,
    refetchOnMount: "always",
  });
  const available = new Map(boxes.data?.map((box) => [box.code, box]));
  const entries = collectionId
    ? (collection.data?.boxes ?? []).map((box) => ({ code: box.code, box }))
    : list.codes.map((code) => ({ code, box: available.get(code) }));
  const state = collectionId ? collection : boxes;
  if (!editor)
    return (
      <Empty title="Printing requires edit access">
        <p>Sign in as an editor or owner to print labels.</p>
      </Empty>
    );
  return (
    <>
      <PageHead
        title={collectionId ? "Print collection labels" : "Print list"}
        eyebrow="FROM DIGITAL TO PHYSICAL"
      >
        <Link
          className="button"
          to={collectionId ? "/collections/" + collectionId : "/boxes"}
        >
          {collectionId ? "Back to collection" : "Choose more boxes"}
        </Link>
      </PageHead>
      <p className="muted">
        {collectionId
          ? `One label for every box in ${collection.data?.name ?? "this collection"}, including archived boxes, in name order.`
          : "Pin boxes as you browse. This browser saves your list for your account, in the order selected."}
      </p>
      {list.notice && (
        <p role="status" className="notice caution">
          {list.notice}
        </p>
      )}
      <ErrorNote error={state.error} />
      {state.error && (
        <button onClick={() => state.refetch()}>Retry print list</button>
      )}
      {(collectionId || list.codes.length > 0) && state.isPending ? (
        <Loading />
      ) : (
        <>
          {entries.length ? (
            <>
              <section className="panel">
                <div className="section-head">
                  <h2>
                    {entries.length} {entries.length === 1 ? "label" : "labels"}
                  </h2>
                  {!collectionId && (
                    <button onClick={list.clear}>Clear print list</button>
                  )}
                </div>
                <ol className="print-entries">
                  {entries.map(({ code, box }) => (
                    <li key={code}>
                      <div>
                        {box ? (
                          <Link to={"/boxes/" + code}>{box.name}</Link>
                        ) : (
                          <strong>Box unavailable</strong>
                        )}
                        <small>
                          {code}
                          {box?.lifecycle === "archived" && " · Archived"}
                          {!box && " · Remove this label to continue"}
                        </small>
                      </div>
                      {!collectionId && (
                        <button
                          aria-label={
                            "Remove " + (box?.name ?? code) + " from print list"
                          }
                          onClick={() => list.remove(code)}
                        >
                          Remove
                        </button>
                      )}
                    </li>
                  ))}
                </ol>
              </section>
              <SheetBuilder
                key={JSON.stringify([
                  collectionId,
                  entries.map(({ code, box }) => [code, box?.version]),
                ])}
                count={entries.length}
                ready={
                  !state.error &&
                  entries.every(({ box }) => !!box) &&
                  entries.length <= MAX_PINS
                }
                source={
                  collectionId
                    ? { collection_id: collectionId }
                    : { box_codes: list.codes }
                }
              />
            </>
          ) : (
            !state.error && (
              <Empty
                title={
                  collectionId
                    ? "This collection has no labels"
                    : "Your print list is empty"
                }
              >
                <p>
                  {collectionId
                    ? "Add boxes to the collection, then return here to print them."
                    : "Select “Pin label for printing” on any box to add it here."}
                </p>
                <Link
                  className="button primary"
                  to={collectionId ? "/collections/" + collectionId : "/boxes"}
                >
                  {collectionId ? "Back to collection" : "Browse boxes"}
                </Link>
              </Empty>
            )
          )}
        </>
      )}
    </>
  );
}

function SheetBuilder({
  count,
  ready,
  source,
}: {
  count: number;
  ready: boolean;
  source: { collection_id: string } | { box_codes: string[] };
}) {
  const [start, setStart] = useState(1);
  const [x, setX] = useState("0"),
    [y, setY] = useState("0");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  const [pdf, setPdf] = useState<{
    url: string;
    settings: string;
    data: Uint8Array;
  }>();
  const settings = JSON.stringify([start, x, y]);
  const url = pdf?.settings === settings && ready ? pdf.url : undefined;
  useEffect(
    () => () => {
      if (pdf) URL.revokeObjectURL(pdf.url);
    },
    [pdf],
  );
  useEffect(() => {
    setPdf(undefined);
  }, [settings]);
  // Prevent a completed request from creating a blob after navigation.
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  async function prepare(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !ready) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError(undefined);
    setPdf(undefined);
    try {
      const blob = await api<Blob>("/labels.pdf", {
        method: "POST",
        responseType: "blob",
        signal: controller.signal,
        body: {
          ...source,
          start_position: start,
          offset_x_mm: Number(x),
          offset_y_mm: Number(y),
        },
      });
      const data = new Uint8Array(await blob.arrayBuffer());
      if (!controller.signal.aborted)
        setPdf({ url: URL.createObjectURL(blob), settings, data });
    } catch (error) {
      if (!controller.signal.aborted) setError(error);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h2>Letter sheet setup</h2>
      <p>
        US Letter (8½ × 11 inches) · 4 × 2-inch labels · 2 columns × 5 rows.
        Avery 5163 / 8163 layout.
      </p>
      <p className="notice">
        Print at <strong>100% / actual size</strong>, portrait, on Letter paper.
        Turn off “Fit to page” and two-sided printing. Test on plain paper
        against your label sheet before printing.
      </p>
      <form onSubmit={prepare}>
        <fieldset disabled={busy} className="print-settings">
          <Field label="First label position">
            <select
              value={start}
              onChange={(e) => setStart(Number(e.target.value))}
            >
              {Array.from({ length: 10 }, (_, i) => (
                <option key={i} value={i + 1}>
                  {i + 1} · Row {Math.floor(i / 2) + 1},{" "}
                  {i % 2 ? "right" : "left"}
                </option>
              ))}
            </select>
          </Field>
          <p className="muted">
            Positions run left to right, top to bottom. Earlier positions on the
            first sheet stay blank.
          </p>
          <details>
            <summary>Adjust printer alignment</summary>
            <p>
              Move all labels by up to 3 mm. Positive values move right or down.
            </p>
            <div className="print-offsets">
              <Field label="Horizontal offset (mm)">
                <input
                  type="number"
                  required
                  min={-3}
                  max={3}
                  step="0.1"
                  value={x}
                  onChange={(e) => setX(e.target.value)}
                />
              </Field>
              <Field label="Vertical offset (mm)">
                <input
                  type="number"
                  required
                  min={-3}
                  max={3}
                  step="0.1"
                  value={y}
                  onChange={(e) => setY(e.target.value)}
                />
              </Field>
            </div>
          </details>
        </fieldset>
        <p>
          {count} labels · {sheetCount(count, start)}{" "}
          {sheetCount(count, start) === 1 ? "sheet" : "sheets"}
        </p>
        {count > MAX_PINS && (
          <p className="notice caution">
            A document can contain up to 500 labels. Split this collection into
            smaller print lists.
          </p>
        )}
        <ErrorNote error={error} />
        <button className="primary" disabled={busy || !ready} type="submit">
          {busy ? "Preparing PDF…" : "Prepare printable PDF"}
        </button>
      </form>
      {url && (
        <div className="print-document">
          <div className="actions">
            <a
              className="button primary"
              href={url}
              target="_blank"
              rel="noreferrer"
            >
              Open PDF to print
            </a>
            <a className="button" href={url} download="boxen-labels-letter.pdf">
              Download PDF
            </a>
          </div>
          <Suspense fallback={<Loading label="Loading PDF preview…" />}>
            <PdfPreview url={url} data={pdf?.data} />
          </Suspense>
        </div>
      )}
    </section>
  );
}
