import { useReducer, useRef, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  api,
  changed,
  query,
  randomId,
  tag,
  type Box,
  type Schema,
} from "./api";
import {
  Empty,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHead,
  Unsaved,
} from "./components";
import { ItemForm } from "./contents";
import { useSession } from "./session";
import {
  REVIEW_LIMIT,
  chipDecision,
  emptyDraft,
  pendingChipsQuery,
  makeSubmission,
  pendingChips,
  reviewDraft,
  suggestionItem,
  uncertainOutcome,
  type Decision,
  type ItemInput,
  type Observation,
  type ReviewSubmission,
} from "./review-chips";
import "./review.css";

export function Review() {
  const [params] = useSearchParams();
  const code = params.get("box");
  const boxes = useInfiniteQuery({
    queryKey: ["review-boxes"],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Schema<"BoxPage">>(
        "/boxes?limit=100" +
          (pageParam ? "&cursor=" + encodeURIComponent(pageParam) : ""),
      ),
    getNextPageParam: (p) => p.page.next_cursor ?? undefined,
    enabled: !code,
  });
  if (useSession().user.role === "viewer")
    return <Empty title="Review requires editor access" />;
  return (
    <>
      <PageHead
        title="Review AI suggestions"
        eyebrow="YOU HAVE THE FINAL SAY"
      />
      <p className="intro">
        Keep what belongs, remove what doesn’t, and add anything the photos
        missed.
      </p>
      {code ? (
        <BoxReview key={code} code={code} />
      ) : (
        <>
          <ErrorNote error={boxes.error} />
          {boxes.isPending ? (
            <Loading />
          ) : (
            boxes.data?.pages
              .flatMap((p) => p.items)
              .filter((b) => b.pending_observation_count > 0)
              .map((b) => (
                <section className="panel" key={b.code}>
                  <div className="section-head">
                    <div>
                      <code>{b.code}</code>
                      <h2>{b.name}</h2>
                    </div>
                    <Link className="button ai" to={"/review?box=" + b.code}>
                      Review {b.pending_observation_count} suggestions
                    </Link>
                  </div>
                </section>
              ))
          )}
          {boxes.data &&
            !boxes.data.pages.some((p) =>
              p.items.some((b) => b.pending_observation_count > 0),
            ) && (
              <Empty title="No pending suggestions on this page">
                <p>Analyze a box’s photos to get started.</p>
                <Link className="button" to="/boxes">
                  Browse boxes
                </Link>
              </Empty>
            )}
          {boxes.hasNextPage && (
            <button onClick={() => boxes.fetchNextPage()}>
              Load more boxes
            </button>
          )}
        </>
      )}
    </>
  );
}

function BoxReview({ code }: { code: string }) {
  const [draft, dispatch] = useReducer(reviewDraft, undefined, emptyDraft);
  const [addition, setAddition] = useState("");
  const [error, setError] = useState<unknown>();
  const [submission, setSubmission] = useState<ReviewSubmission | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [editing, setEditing] = useState<{
    id: string;
    manual: boolean;
  } | null>(null);
  const box = useQuery({
    ...query<Box>("/boxes/" + code),
    refetchInterval: 5000,
  });
  const observations = useQuery({
    ...pendingChipsQuery(code),
    enabled: !submission,
  });
  const all = pendingChips(observations.data ?? [], draft);
  const selected =
    submission?.observations ??
    all.slice(0, REVIEW_LIMIT - draft.manual.length);
  const kept = selected.filter((o) => !draft.removed.has(o.id));
  const removed = selected.length - kept.length;
  const actionCount = selected.length + draft.manual.length;
  const activeJobs =
    box.data?.images.filter((photo) =>
      ["queued", "running"].includes(photo.latest_analysis?.state ?? ""),
    ).length ?? 0;
  const archived = box.data?.lifecycle === "archived";
  const locked = busy || !!submission || archived;
  const dirty = !!(
    draft.removed.size ||
    draft.decisions.size ||
    draft.manual.length ||
    addition.trim() ||
    submission
  );
  const editingObservation =
    editing && !editing.manual
      ? selected.find((o) => o.id === editing.id)
      : undefined;
  const editingManual = editing?.manual
    ? draft.manual.find((chip) => chip.id === editing.id)
    : undefined;

  async function accept() {
    if (inFlight.current || archived) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    let request = submission;
    try {
      request ??= makeSubmission(selected, draft, randomId());
      setSubmission(request);
      await api<Schema<"ObservationReviewResult">>(
        `/boxes/${code}/observations/review`,
        {
          method: "POST",
          body: request.body,
          key: request.key,
        },
      );
    } catch (failure) {
      setError(failure);
      if (!uncertainOutcome(failure)) {
        setSubmission(null);
        void changed();
      }
      setBusy(false);
      inFlight.current = false;
      return;
    }
    dispatch({ type: "committed", submission: request });
    setSubmission(null);
    setBusy(false);
    inFlight.current = false;
    void changed();
  }

  return (
    <>
      <Unsaved dirty={dirty} />
      <Link to={"/boxes/" + code}>← {box.data?.name ?? code}</Link>
      <ErrorNote error={box.error ?? observations.error} />
      {!box.data || !observations.data ? (
        <Loading />
      ) : (
        <section
          className="panel chip-review"
          aria-labelledby="chip-review-title"
        >
          <div className="section-head">
            <h2 id="chip-review-title">Identified items</h2>
            <span className="chip-count" aria-live="polite">
              {kept.length + draft.manual.length} items to keep
            </span>
          </div>
          <p className="muted">
            All photos contribute to this box. Tap an item for details; ×
            removes it from this set.
          </p>
          {activeJobs > 0 && (
            <p role="status">
              {activeJobs} photo analyses still running. New suggestions appear
              as they finish.
            </p>
          )}
          {archived && (
            <p className="notice">
              Restore this box before reviewing its contents.
            </p>
          )}
          {all.length + draft.manual.length > REVIEW_LIMIT && (
            <p className="notice">
              Reviewing the first {selected.length} suggestions.{" "}
              {all.length - selected.length} more will remain pending for the
              next set.
            </p>
          )}
          <ul className="review-chip-list" aria-label="Items to accept">
            {kept.map((o) => {
              const decision = chipDecision(o, draft);
              const linked =
                decision.mode === "merge"
                  ? box.data.items.find((item) => item.id === decision.item_id)
                  : undefined;
              const name =
                decision.mode === "create"
                  ? decision.item.name
                  : (linked?.name ?? o.proposed_name);
              const photo =
                box.data.images.findIndex((image) => image.id === o.image_id) +
                1;
              return (
                <ItemChip
                  key={o.id}
                  name={name}
                  detail={`${linked ? "Linked item · " : ""}Photo ${photo || "—"}`}
                  disabled={locked}
                  edit={() => setEditing({ id: o.id, manual: false })}
                  remove={() => dispatch({ type: "remove", id: o.id })}
                />
              );
            })}
            {draft.manual.map((chip) => (
              <ItemChip
                key={chip.id}
                name={chip.item.name}
                detail="Added by you"
                disabled={locked}
                manual
                edit={() => setEditing({ id: chip.id, manual: true })}
                remove={() => dispatch({ type: "remove-manual", id: chip.id })}
              />
            ))}
          </ul>
          {removed > 0 && (
            <div className="chip-removed">
              <span>{removed} removed from this set</span>
              <button
                className="ghost"
                disabled={locked}
                onClick={() => dispatch({ type: "restore" })}
              >
                Restore removed items
              </button>
            </div>
          )}
          {actionCount === 0 && (
            <Empty
              title={
                activeJobs ? "Waiting for photo suggestions" : "Review complete"
              }
            >
              <p>
                {activeJobs
                  ? "You can add missing items while analysis finishes."
                  : "Your confirmed inventory is up to date. You can add more items below."}
              </p>
            </Empty>
          )}
          {actionCount > 0 && !kept.length && !draft.manual.length && (
            <p>No items to keep. Accept to discard these suggestions.</p>
          )}
          <form
            className="chip-add"
            onSubmit={(event) => {
              event.preventDefault();
              const name = addition.trim();
              if (locked || !name || actionCount >= REVIEW_LIMIT) return;
              dispatch({
                type: "add",
                chip: {
                  id: randomId(),
                  item: {
                    name,
                    quantity: null,
                    unit: null,
                    notes_markdown: "",
                  },
                },
              });
              setAddition("");
            }}
          >
            <Field label="Add an item">
              <input
                value={addition}
                maxLength={160}
                disabled={locked || actionCount >= REVIEW_LIMIT}
                onChange={(event) => setAddition(event.target.value)}
                placeholder="Something the photos missed…"
              />
            </Field>
            <button
              type="submit"
              disabled={
                locked || !addition.trim() || actionCount >= REVIEW_LIMIT
              }
            >
              Add
            </button>
          </form>
          <ErrorNote error={error} />
          {submission && !busy && (
            <p className="notice" role="status">
              The save result is uncertain. Press Accept items again to safely
              check the same save without adding duplicates. Editing is paused
              until it’s resolved.
            </p>
          )}
          <div className="chip-review-footer">
            <p className="muted">
              Nothing changes until you accept. Existing inventory stays intact.
            </p>
            <button
              className="ai"
              disabled={
                busy ||
                archived ||
                !actionCount ||
                !!addition.trim() ||
                (!submission && !!observations.error)
              }
              onClick={() => void accept()}
            >
              {busy ? "Accepting items…" : "Accept items"}
            </button>
          </div>
          {!!addition.trim() && (
            <small>Add your typed item to the set before accepting.</small>
          )}
          {editing && (editingObservation || editingManual) && (
            <ChipDetails
              key={editing.id}
              box={box.data}
              observation={editingObservation}
              decision={
                editingObservation
                  ? chipDecision(editingObservation, draft)
                  : undefined
              }
              manual={editingManual?.item}
              close={() => setEditing(null)}
              save={(decision) => {
                if (editing.manual && decision.mode === "create")
                  dispatch({
                    type: "edit-manual",
                    id: editing.id,
                    item: decision.item,
                  });
                else dispatch({ type: "decide", id: editing.id, decision });
                setEditing(null);
              }}
            />
          )}
        </section>
      )}
    </>
  );
}

function ItemChip({
  name,
  detail,
  disabled,
  manual = false,
  edit,
  remove,
}: {
  name: string;
  detail: string;
  disabled: boolean;
  manual?: boolean;
  edit: () => void;
  remove: () => void;
}) {
  return (
    <li className={`review-chip${manual ? " manual-chip" : ""}`}>
      <button
        className="chip-name"
        disabled={disabled}
        onClick={edit}
        aria-label={"Edit " + name}
        title={detail}
      >
        <span>{name}</span>
        <small>{detail}</small>
      </button>
      <button
        className="chip-remove"
        disabled={disabled}
        onClick={remove}
        aria-label={"Remove " + name}
      >
        ×
      </button>
    </li>
  );
}

function ChipDetails({
  box,
  observation,
  decision,
  manual,
  close,
  save,
}: {
  box: Box;
  observation?: Observation;
  decision?: Decision;
  manual?: ItemInput;
  close: () => void;
  save: (decision: Decision) => void;
}) {
  const [mode, setMode] = useState(decision?.mode ?? "create");
  const [itemId, setItemId] = useState(
    decision?.mode === "merge" ? decision.item_id : "",
  );
  const item = box.items.find(
    (entry) => entry.id === itemId && entry.lifecycle === "active",
  );
  const defaults =
    manual ??
    (decision?.mode === "create"
      ? decision.item
      : observation
        ? suggestionItem(observation)
        : { name: "", notes_markdown: "" });
  const photo = box.images.find((image) => image.id === observation?.image_id);
  return (
    <Modal title="Item details" close={close}>
      {photo && (
        <div className="chip-source">
          <img
            src={photo.thumbnail_url ?? ""}
            alt={photo.caption || "Source photo"}
          />
          <p>
            {String(
              observation?.attributes.evidence ?? "Suggested from this photo.",
            )}
          </p>
        </div>
      )}
      {observation &&
        box.items.some((entry) => entry.lifecycle === "active") && (
          <Field label="How to keep this item">
            <select
              value={mode}
              onChange={(event) =>
                setMode(event.target.value as "create" | "merge")
              }
            >
              <option value="create">Add as a new item</option>
              <option value="merge">Link to existing item</option>
            </select>
          </Field>
        )}
      {mode === "merge" ? (
        <>
          <Field label="Confirmed item">
            <select
              value={itemId}
              onChange={(event) => setItemId(event.target.value)}
            >
              <option value="">Choose the same physical item…</option>
              {box.items
                .filter((entry) => entry.lifecycle === "active")
                .map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {entry.name} · {entry.quantity ?? "unknown"} {entry.unit}
                  </option>
                ))}
            </select>
          </Field>
          <p>
            Only this photo evidence is linked. The confirmed quantity stays
            unchanged.
          </p>
          <button
            className="ai"
            disabled={!item}
            onClick={() =>
              item &&
              save({
                mode: "merge",
                item_id: item.id,
                item_etag: tag("item", item.id, item.version),
              })
            }
          >
            Save changes
          </button>
        </>
      ) : (
        <>
          {!!matchingItems(box, defaults.name).length && (
            <p className="notice">
              A confirmed item has the same name. If this is another view of the
              same item, link it instead of adding its quantity again.
            </p>
          )}
          <ItemForm
            defaults={defaults}
            label="Save changes"
            submit={async (body) => {
              if (!body.name.trim()) throw new Error("Enter an item name.");
              save({
                mode: "create",
                item: { ...body, name: body.name.trim() },
              });
            }}
          />
        </>
      )}
    </Modal>
  );
}

export function matchingItems(box: Pick<Box, "items">, name: string) {
  const normalized = name.trim().toLocaleLowerCase();
  return box.items.filter(
    (item) =>
      item.lifecycle === "active" &&
      item.name.trim().toLocaleLowerCase() === normalized,
  );
}
