import { useEffect, useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  api,
  changed,
  query,
  randomId,
  tag,
  type Box,
  type Item,
  type Photo,
  type Schema,
} from "./api";
import {
  Empty,
  ErrorNote,
  Field,
  Icon,
  Markdown,
  MarkdownEditor,
  Modal,
  Submit,
  type SubmitEvent,
} from "./components";
import { pendingChipsQuery, pendingCountsByPhoto } from "./review-chips";

export function Inventory({ box, editable }: { box: Box; editable: boolean }) {
  const [editing, setEditing] = useState<Item | "new" | null>(null),
    [filter, setFilter] = useState(""),
    [error, setError] = useState<unknown>(),
    [merge, setMerge] = useState(false),
    [removed, setRemoved] = useState(false);
  const all = useQuery({
    ...query<{ items: Item[] }>(
      `/boxes/${box.code}/items?include_removed=true`,
    ),
    enabled: removed,
  });
  const rows = (removed ? (all.data?.items ?? box.items) : box.items).filter(
    (i) => i.name.toLowerCase().includes(filter.toLowerCase()),
  );
  async function remove(item: Item) {
    if (
      !confirm(
        `Remove “${item.name}” from this inventory? It can be restored later.`,
      )
    )
      return;
    try {
      await api("/items/" + item.id, {
        method: "DELETE",
        etag: tag("item", item.id, item.version),
      });
      await changed();
    } catch (e) {
      setError(e);
    }
  }
  async function restore(item: Item) {
    try {
      await api("/items/" + item.id, {
        method: "PATCH",
        etag: tag("item", item.id, item.version),
        body: { lifecycle: "active" },
      });
      await changed();
    } catch (e) {
      setError(e);
    }
  }
  return (
    <section className="panel">
      <div className="section-head">
        <div>
          <div className="eyebrow">03 / CONFIRMED CONTENTS</div>
          <h2>
            Inventory <span className="count">{box.item_count}</span>
          </h2>
        </div>
        {editable && (
          <button className="primary" onClick={() => setEditing("new")}>
            <Icon name="plus" size={18} />
            Add item
          </button>
        )}
      </div>
      {box.items.length > 0 && (
        <div className="filters">
          <Field label="Filter items">
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Item name…"
            />
          </Field>
          {editable && (
            <button
              onClick={() => setMerge(true)}
              disabled={box.items.length < 2}
            >
              Merge duplicates
            </button>
          )}
        </div>
      )}
      {editable && (
        <label className="check">
          <input
            type="checkbox"
            checked={removed}
            onChange={(e) => setRemoved(e.target.checked)}
          />
          Show removed items
        </label>
      )}
      <ErrorNote error={error ?? all.error} />
      {rows.length ? (
        <div className="inventory">
          {rows.map((item) => (
            <article
              className={
                "inventory-row " +
                (item.lifecycle === "removed" ? "removed" : "")
              }
              key={item.id}
            >
              <span className="item-glyph">
                <Icon size={20} />
              </span>
              <div className="item-content">
                <h3>
                  {item.name}
                  <span className="quantity">
                    {item.quantity ?? "—"} {item.unit}
                  </span>
                </h3>
                {item.notes.source && <Markdown html={item.notes.html} />}
                <small>
                  {item.lifecycle === "removed" ? "Removed · " : ""}
                  {
                    {
                      manual: "Manual",
                      ai: "AI accepted",
                      mixed: "Edited after AI",
                    }[item.provenance]
                  }
                </small>
              </div>
              {editable && (
                <div className="actions">
                  {item.lifecycle === "removed" ? (
                    <button onClick={() => restore(item)}>Restore</button>
                  ) : (
                    <>
                      <button onClick={() => setEditing(item)}>Edit</button>
                      <button
                        className="ghost danger-text"
                        onClick={() => remove(item)}
                      >
                        Remove
                      </button>
                    </>
                  )}
                </div>
              )}
            </article>
          ))}
        </div>
      ) : (
        <Empty title="No matching items">
          <p>
            Add the contents yourself, or analyze the photos assigned to this
            box and review their suggestions together.
          </p>
        </Empty>
      )}
      {editing && (
        <Modal
          title={
            editing === "new" ? "Add inventory item" : "Edit inventory item"
          }
          close={() => setEditing(null)}
        >
          <ItemForm
            existing={editing === "new" ? undefined : editing}
            submit={async (body) => {
              await api(
                editing === "new"
                  ? `/boxes/${box.code}/items`
                  : "/items/" + editing.id,
                {
                  method: editing === "new" ? "POST" : "PATCH",
                  body,
                  etag:
                    editing === "new"
                      ? undefined
                      : tag("item", editing.id, editing.version),
                },
              );
              await changed();
              setEditing(null);
            }}
          />
        </Modal>
      )}
      {merge && <MergeItems box={box} close={() => setMerge(false)} />}
    </section>
  );
}
export function ItemForm({
  existing,
  defaults,
  submit,
  label = "Save item",
}: {
  existing?: Item;
  defaults?: Schema<"InventoryItemCreate">;
  submit: (body: Schema<"InventoryItemCreate">) => Promise<void>;
  label?: string;
}) {
  const [name, setName] = useState(existing?.name ?? defaults?.name ?? ""),
    [quantity, setQuantity] = useState(
      existing?.quantity ?? defaults?.quantity ?? "",
    ),
    [unit, setUnit] = useState(existing?.unit ?? defaults?.unit ?? ""),
    [notes, setNotes] = useState(
      existing?.notes.source ?? defaults?.notes_markdown ?? "",
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  async function save(e: SubmitEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await submit({
        name,
        quantity: quantity || null,
        unit: unit || null,
        notes_markdown: notes,
      });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={save}>
      <Field label="Item name">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={160}
          autoFocus
        />
      </Field>
      <div className="form-grid">
        <Field label="Quantity" help="Leave blank if unknown.">
          <input
            inputMode="decimal"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            pattern="[0-9]+(\.[0-9]{1,3})?"
            placeholder="e.g. 2"
          />
        </Field>
        <Field label="Unit">
          <input
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            maxLength={24}
            placeholder="e.g. pieces"
          />
        </Field>
      </div>
      <MarkdownEditor
        value={notes}
        onChange={setNotes}
        label="Item notes"
        max={16384}
      />
      <ErrorNote error={error} />
      <div className="form-footer">
        <span className="muted">Confirmed inventory</span>
        <Submit busy={busy}>{label}</Submit>
      </div>
    </form>
  );
}
function MergeItems({ box, close }: { box: Box; close: () => void }) {
  const [survivor, setSurvivor] = useState(box.items[0].id),
    [selected, setSelected] = useState<string[]>([]),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  return (
    <Modal title="Merge duplicate items" close={close}>
      <p>
        Keep one item and combine selected duplicates into it. Quantities are
        added only when units match; uncertain quantities remain unknown. Source
        items are marked removed.
      </p>
      <Field label="Item to keep">
        <select
          value={survivor}
          onChange={(e) => {
            setSurvivor(e.target.value);
            setSelected([]);
          }}
        >
          {box.items.map((i) => (
            <option key={i.id} value={i.id}>
              {i.name}
            </option>
          ))}
        </select>
      </Field>
      {box.items
        .filter((i) => i.id !== survivor)
        .map((i) => (
          <label className="check" key={i.id}>
            <input
              type="checkbox"
              checked={selected.includes(i.id)}
              onChange={(e) =>
                setSelected(
                  e.target.checked
                    ? [...selected, i.id]
                    : selected.filter((id) => id !== i.id),
                )
              }
            />
            {i.name} · {i.quantity ?? "?"} {i.unit}
          </label>
        ))}
      <ErrorNote error={error} />
      <button
        className="primary"
        disabled={busy || !selected.length}
        onClick={async () => {
          setBusy(true);
          try {
            const i = box.items.find((i) => i.id === survivor)!;
            await api("/items/merge", {
              method: "POST",
              body: {
                survivor_id: survivor,
                merged_item_ids: selected,
                survivor_etag: tag("item", i.id, i.version),
              },
            });
            await changed();
            close();
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Merging…" : "Merge selected items"}
      </button>
    </Modal>
  );
}

type Queued = {
  key: string;
  file: File;
  url: string;
  caption: string;
  state: "waiting" | "uploading" | "failed" | "done";
  error?: unknown;
};
type AnalysisJob = Schema<"AnalysisJobView">;
// The server's latest job is authoritative, including across browsers/reloads.
export function analysisEligible(
  photo: Photo,
  job = photo.latest_analysis,
  confirmedReanalysis = false,
) {
  return (
    photo.lifecycle === "ready" &&
    (!job ||
      job.state === "failed" ||
      job.state === "cancelled" ||
      (confirmedReanalysis && job.state === "succeeded"))
  );
}

export function Photos({ box, editable }: { box: Box; editable: boolean }) {
  return <PhotoCollection key={box.code} box={box} editable={editable} />;
}
function PhotoCollection({ box, editable }: { box: Box; editable: boolean }) {
  const [queue, setQueue] = useState<Queued[]>([]),
    [uploading, setUploading] = useState(false),
    [error, setError] = useState<unknown>(),
    [editing, setEditing] = useState<Photo | null>(null),
    [caption, setCaption] = useState(""),
    [submittedJobs, setSubmittedJobs] = useState<Record<string, AnalysisJob>>(
      {},
    ),
    [analysisErrors, setAnalysisErrors] = useState<Record<string, unknown>>({}),
    [analyzing, setAnalyzing] = useState(false),
    [batch, setBatch] = useState<{
      total: number;
      done: number;
      queued: number;
      skipped: number;
      failed: number;
    } | null>(null);
  const analysisLock = useRef(false);
  const detail = useQuery({
    ...query<Box>(`/boxes/${box.code}`),
    refetchInterval: editable && box.images.length > 0 ? 5000 : false,
  });
  const photos = detail.data?.images ?? box.images;
  const latestJobs = photos.map((photo) => {
    const server = photo.latest_analysis;
    const submitted = submittedJobs[photo.id];
    return server &&
      (!submitted ||
        server.id === submitted.id ||
        server.created_at > submitted.created_at)
      ? server
      : submitted;
  });
  const jobQueries = useQueries({
    queries: latestJobs
      .filter((job): job is AnalysisJob => !!job)
      .map((job) => ({
        ...query<AnalysisJob>(`/jobs/${job.id}`),
        initialData: job,
        refetchInterval: (q: { state: { data?: AnalysisJob } }) =>
          ["queued", "running"].includes(q.state.data?.state ?? "queued")
            ? 2000
            : false,
      })),
  });
  const jobs = Object.fromEntries(
    jobQueries.map((q) => [q.data.image_id, q.data]),
  );
  const jobErrors = Object.fromEntries(
    jobQueries.map((q) => [q.data.image_id, q.error]),
  );
  const observations = useQuery({
    ...pendingChipsQuery(box.code),
    enabled: Object.values(jobs).some((job) => job.state === "succeeded"),
  });
  // Missing/failed reads are unknown, not zero. Count across this photo's runs:
  // reanalysis does not discard older suggestions still awaiting a decision.
  const pendingByPhoto =
    observations.data && !observations.isError
      ? pendingCountsByPhoto(observations.data)
      : undefined;
  const completed = Object.values(jobs)
    .filter((job) => !["queued", "running"].includes(job.state))
    .map((job) => `${job.id}:${job.state}`)
    .sort()
    .join(",");
  useEffect(() => {
    if (completed) void changed();
  }, [completed]);
  const eligible = photos.filter((photo) =>
    analysisEligible(photo, jobs[photo.id]),
  );
  const count = (state: AnalysisJob["state"]) =>
    photos.filter((photo) => jobs[photo.id]?.state === state).length;
  const queueRef = useRef(queue);
  queueRef.current = queue;
  const system = useQuery(query<Schema<"SystemStatusView">>("/system"));
  const aiReady = system.data?.components.ai?.status === "ready";
  useEffect(
    () => () => queueRef.current.forEach((q) => URL.revokeObjectURL(q.url)),
    [],
  );
  function choose(files: FileList | null) {
    if (!files) return;
    const additions = Array.from(files).map((file) => ({
      key: randomId(),
      file,
      url: URL.createObjectURL(file),
      caption: "",
      state: "waiting" as const,
    }));
    setQueue((q) => [...q, ...additions]);
  }
  function update(key: string, patch: Partial<Queued>) {
    setQueue((q) => q.map((i) => (i.key === key ? { ...i, ...patch } : i)));
  }
  async function upload() {
    setUploading(true);
    for (const entry of queue.filter(
      (q) => q.state === "waiting" || q.state === "failed",
    )) {
      update(entry.key, { state: "uploading", error: undefined });
      try {
        const form = new FormData();
        form.set("file", entry.file);
        form.set("caption", entry.caption);
        await api(`/boxes/${box.code}/images`, {
          method: "POST",
          body: form,
          key: entry.key,
        });
        update(entry.key, { state: "done" });
        await changed();
      } catch (e) {
        update(entry.key, { state: "failed", error: e });
      }
    }
    setUploading(false);
  }
  async function move(photo: Photo, direction: number) {
    const order = box.images.map((i) => i.id),
      index = order.indexOf(photo.id);
    [order[index], order[index + direction]] = [
      order[index + direction],
      order[index],
    ];
    try {
      await api(`/boxes/${box.code}/image-order`, {
        method: "PUT",
        etag: tag("box", box.code, box.version),
        body: { image_ids: order },
      });
      await changed();
    } catch (e) {
      setError(e);
    }
  }
  async function analyze(selected?: Photo, confirmedReanalysis = false) {
    if (analysisLock.current) return;
    analysisLock.current = true;
    setAnalyzing(true);
    setError(null);
    const progress = { total: 0, done: 0, queued: 0, skipped: 0, failed: 0 };
    setBatch(progress);
    try {
      // Re-read durable state before submitting: another device may have run
      // analysis since this page loaded. A successful empty result also counts.
      const fresh = await api<Box>(`/boxes/${box.code}`);
      const candidates = fresh.images.filter((photo) =>
        selected ? photo.id === selected.id : analysisEligible(photo),
      );
      progress.total = candidates.length;
      setBatch({ ...progress });
      for (const candidate of candidates) {
        setAnalysisErrors((old) => ({ ...old, [candidate.id]: undefined }));
        try {
          const photo = await api<Photo>(`/images/${candidate.id}`);
          if (
            !analysisEligible(
              photo,
              photo.latest_analysis,
              !!selected && confirmedReanalysis,
            )
          ) {
            progress.skipped += 1;
          } else {
            const job = await api<AnalysisJob>(`/images/${photo.id}/analyses`, {
              method: "POST",
              body: {},
            });
            setSubmittedJobs((old) => ({ ...old, [photo.id]: job }));
            progress.queued += 1;
          }
        } catch (e) {
          setAnalysisErrors((old) => ({ ...old, [candidate.id]: e }));
          progress.failed += 1;
        }
        progress.done += 1;
        setBatch({ ...progress });
      }
    } catch (e) {
      setError(e);
    } finally {
      await changed();
      analysisLock.current = false;
      setAnalyzing(false);
    }
  }
  return (
    <section className="panel">
      <div className="section-head">
        <div>
          <div className="eyebrow">02 / VISUAL RECORD</div>
          <h2>
            Photos <span className="count">{box.image_count}</span>
          </h2>
        </div>
        {editable && (
          <div className="actions">
            <label className="button file-button">
              <Icon name="photo" size={18} />
              Take photo
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                capture="environment"
                onChange={(e) => {
                  choose(e.target.files);
                  e.target.value = "";
                }}
              />
            </label>
            <label className="button file-button">
              Choose files
              <input
                type="file"
                multiple
                accept="image/jpeg,image/png,image/webp"
                onChange={(e) => {
                  choose(e.target.files);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
        )}
      </div>
      <p className="muted">
        Together, these photos represent the items assigned to this box. Use
        staged items, close-ups or reference views; the container does not need
        to appear, and items need not be inside it. JPEG, PNG or WebP, up to 25
        MB each. Uploads are saved as WebP, up to 2,048 pixels on the longest
        edge, to save space. Smaller photos keep their size.
      </p>
      {system.data?.runtime_offline === false && (
        <p className="notice caution" role="note">
          Remote AI is configured. Choosing Analyze sends the selected photos to
          the administrator's AI server. Saved photos and confirmed inventory
          remain stored on this Boxen host.
        </p>
      )}
      {editable && photos.length > 0 && (
        <div className="notice ai-note">
          <p>
            Analyze each photo, then review all suggestions in one shared box
            inventory. Photos are processed separately, not as a joint image
            analysis. If the same item appears twice, link the second suggestion
            to the confirmed item to keep its quantity unchanged.
          </p>
          <div className="actions">
            <button
              className="ai"
              disabled={!aiReady || analyzing || !eligible.length}
              onClick={() => analyze()}
            >
              {analyzing
                ? "Queueing photos…"
                : Object.keys(jobs).length
                  ? `Analyze remaining photos (${eligible.length})`
                  : `Analyze all photos (${eligible.length})`}
            </button>
            {(detail.data ?? box).pending_observation_count > 0 && (
              <Link className="button ai" to={`/review?box=${box.code}`}>
                Review all photo suggestions
              </Link>
            )}
          </div>
          <p role="status">
            {count("succeeded")} of {photos.length} photos analyzed ·{" "}
            {count("queued")} queued · {count("running")} running ·{" "}
            {count("failed") + count("cancelled")} need retry.
          </p>
          <small>
            Active and already successful analyses are skipped, including those
            with no suggestions. Failed or cancelled photos can be retried. Use
            “Analyze again” on an individual photo to explicitly rerun a
            completed analysis, for example after a model update.
          </small>
          {batch && (
            <p role="status">
              {analyzing ? "Queueing" : "Queue requests finished"}: {batch.done}
              /{batch.total} checked · {batch.queued} queued · {batch.skipped}{" "}
              skipped · {batch.failed} could not queue.
              {batch.failed > 0 &&
                " See each photo’s error and retry it below."}
            </p>
          )}
        </div>
      )}
      <ErrorNote error={error ?? detail.error} />
      {queue.length > 0 && (
        <div className="upload-queue">
          {queue.map((q) => (
            <article key={q.key} className="queued-photo">
              <img src={q.url} alt={"Upload preview: " + q.file.name} />
              <div>
                <strong>{q.file.name}</strong>
                <Field label="Caption">
                  <input
                    maxLength={500}
                    disabled={q.state === "done" || uploading}
                    value={q.caption}
                    onChange={(e) => update(q.key, { caption: e.target.value })}
                  />
                </Field>
                <span role="status">
                  {q.state === "uploading"
                    ? "Uploading and processing…"
                    : q.state === "done"
                      ? "Uploaded"
                      : q.state === "failed"
                        ? "Upload failed"
                        : "Ready to upload"}
                </span>
                <ErrorNote error={q.error} />
              </div>
              <button
                disabled={uploading}
                onClick={() => {
                  URL.revokeObjectURL(q.url);
                  setQueue((items) => items.filter((i) => i.key !== q.key));
                }}
              >
                {q.state === "done" ? "Dismiss" : "Remove"}
              </button>
            </article>
          ))}
          <button
            className="primary"
            disabled={uploading || queue.every((q) => q.state === "done")}
            onClick={upload}
          >
            {uploading ? "Uploading…" : "Upload / retry photos"}
          </button>
        </div>
      )}
      {photos.length ? (
        <div className="photo-grid">
          {photos.map((photo, index) => (
            <article
              className="photo-tile"
              key={photo.id}
              aria-label={`Photo ${index + 1}`}
            >
              <a
                href={photo.display_url ?? "#"}
                target="_blank"
                rel="noreferrer"
              >
                <img
                  src={photo.thumbnail_url ?? ""}
                  alt={photo.caption || `Photo ${index + 1} of ${box.name}`}
                  loading="lazy"
                  decoding="async"
                />
              </a>
              <div>
                <small>PHOTO {String(index + 1).padStart(2, "0")}</small>
                <p>{photo.caption || "No caption"}</p>
                {jobs[photo.id] && (
                  <JobStatus
                    job={jobs[photo.id]}
                    error={jobErrors[photo.id]}
                    pendingCount={
                      pendingByPhoto
                        ? (pendingByPhoto.get(photo.id) ?? 0)
                        : undefined
                    }
                    reviewUnavailable={observations.isError}
                  />
                )}
                <ErrorNote error={analysisErrors[photo.id]} />
                {editable && (
                  <>
                    <div className="actions">
                      <button
                        className="ai"
                        disabled={
                          !aiReady ||
                          analyzing ||
                          !analysisEligible(photo, jobs[photo.id], true)
                        }
                        onClick={() => {
                          const repeat = jobs[photo.id]?.state === "succeeded";
                          if (
                            repeat &&
                            !confirm(
                              "Analyze this photo again? This adds another set of suggestions. Previous suggestions and confirmed items remain. Repeated photos can create duplicate pending evidence: link the same item instead of counting it twice.",
                            )
                          )
                            return;
                          void analyze(photo, repeat);
                        }}
                      >
                        <Icon name="review" size={16} />
                        {jobs[photo.id]?.state === "succeeded"
                          ? "Analyze again"
                          : ["queued", "running"].includes(
                                jobs[photo.id]?.state,
                              )
                            ? "Analysis in progress"
                            : jobs[photo.id] || analysisErrors[photo.id]
                              ? "Retry analysis"
                              : "Analyze"}
                      </button>
                      <button
                        onClick={() => {
                          setEditing(photo);
                          setCaption(photo.caption);
                        }}
                      >
                        Caption
                      </button>
                    </div>
                    <div className="actions">
                      <button
                        className="ghost"
                        disabled={index === 0}
                        onClick={() => move(photo, -1)}
                        aria-label={`Move photo ${index + 1} earlier`}
                      >
                        ← Earlier
                      </button>
                      <button
                        className="ghost"
                        disabled={index === box.images.length - 1}
                        onClick={() => move(photo, 1)}
                        aria-label={`Move photo ${index + 1} later`}
                      >
                        Later →
                      </button>
                      <button
                        className="ghost danger-text"
                        onClick={async () => {
                          if (
                            !confirm(
                              "Remove this photo? Pending analysis and unreviewed suggestions for it will be cancelled.",
                            )
                          )
                            return;
                          try {
                            await api("/images/" + photo.id, {
                              method: "DELETE",
                              etag: tag("image", photo.id, photo.version),
                            });
                            await changed();
                          } catch (e) {
                            setError(e);
                          }
                        }}
                      >
                        Remove
                      </button>
                    </div>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <Empty title="Build a visual contents collection">
          <p>
            Add photos of the items assigned to this box. Optimized photos are
            stored on your Boxen host.
          </p>
        </Empty>
      )}
      {editable && !aiReady && (
        <div className="notice ai-note">
          AI is not ready. Photos, manual inventory, and existing AI review
          remain available.
        </div>
      )}
      {editing && (
        <Modal title="Edit photo caption" close={() => setEditing(null)}>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                await api("/images/" + editing.id, {
                  method: "PATCH",
                  etag: tag("image", editing.id, editing.version),
                  body: { caption },
                });
                await changed();
                setEditing(null);
              } catch (e) {
                setError(e);
              }
            }}
          >
            <Field label="Caption">
              <input
                value={caption}
                maxLength={500}
                onChange={(e) => setCaption(e.target.value)}
              />
            </Field>
            <ErrorNote error={error} />
            <button className="primary">Save caption</button>
          </form>
        </Modal>
      )}
    </section>
  );
}
export function analysisStatusMessage(
  state: AnalysisJob["state"],
  pendingCount?: number,
  reviewUnavailable = false,
) {
  if (state === "succeeded") {
    if (reviewUnavailable) return "Complete. Review status unavailable.";
    if (pendingCount === undefined) return "Complete.";
    if (pendingCount === 0) return "Complete. No suggestions left to review.";
    return `Complete. ${pendingCount} suggestion${pendingCount === 1 ? "" : "s"} to review in the shared inventory.`;
  }
  return ["queued", "running"].includes(state)
    ? "No need to submit again."
    : "";
}

function JobStatus({
  job,
  error,
  pendingCount,
  reviewUnavailable,
}: {
  job: AnalysisJob;
  error?: unknown;
  pendingCount?: number;
  reviewUnavailable: boolean;
}) {
  const message = analysisStatusMessage(
    job.state,
    pendingCount,
    reviewUnavailable,
  );
  return (
    <div role="status" className="notice ai-note">
      Analysis: {job.state}
      {message && ` · ${message}`}
      <ErrorNote
        error={error ?? (job.error ? new Error(job.error.summary) : null)}
      />
    </div>
  );
}
