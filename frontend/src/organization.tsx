import { useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  api,
  ApiError,
  changed,
  query,
  randomId,
  tag,
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
import { useSession } from "./session";
import {
  addTag,
  updateParams,
  uncertainWrite,
  freezeWrite,
  groupLines,
  loadAllBoxes,
  quantityLabel,
  sameSelection,
  toggleMembership,
  type NamedOrganization,
  type CollectionSummary,
  type CollectionDetail,
  type OrganizationWrite,
} from "./organization-helpers";
import "./organization.css";

export function useCollections() {
  return useQuery(query<{ items: CollectionSummary[] }>("/collections"));
}

export function TagInput({
  value,
  onChange,
  input,
  onInput,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  input: string;
  onInput: (value: string) => void;
}) {
  const tags = useQuery(
    query<{ items: (NamedOrganization & { box_count: number })[] }>("/tags"),
  );
  const id = useId();
  const [error, setError] = useState<unknown>();
  function add(name: string) {
    try {
      onChange(addTag(value, name));
      onInput("");
      setError(null);
    } catch (error) {
      setError(error);
    }
  }
  return (
    <section className="org-tag-editor" aria-labelledby={id}>
      <label id={id} htmlFor={id + "-input"}>
        Tags
      </label>
      <div className="org-badges">
        {value.map((name) => (
          <span className="org-chip" key={name}>
            {name}
            <button
              type="button"
              aria-label={"Remove tag " + name}
              onClick={() => onChange(value.filter((tag) => tag !== name))}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="org-input-row">
        <input
          id={id + "-input"}
          value={input}
          maxLength={64}
          placeholder="e.g. camping"
          onChange={(e) => onInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              add(input);
            }
          }}
        />
        <button
          type="button"
          disabled={!input.trim()}
          onClick={() => add(input)}
        >
          Add tag
        </button>
      </div>
      <small>Press Enter to add · {value.length}/32 tags</small>
      <ErrorNote error={error ?? tags.error} />
      {!!tags.data?.items.length && (
        <div className="org-suggestions" aria-label="Suggested tags">
          {tags.data.items
            .filter(
              (tag) =>
                !value.some(
                  (name) =>
                    name.toLocaleLowerCase() === tag.name.toLocaleLowerCase(),
                ) &&
                tag.name
                  .toLocaleLowerCase()
                  .includes(input.toLocaleLowerCase()),
            )
            .slice(0, 12)
            .map((tag) => (
              <button type="button" key={tag.id} onClick={() => add(tag.name)}>
                {tag.name}
              </button>
            ))}
        </div>
      )}
    </section>
  );
}

export function CollectionChecklist({
  value,
  onChange,
}: {
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const collections = useCollections();
  return (
    <fieldset className="org-fieldset">
      <legend>Collections</legend>
      <ErrorNote error={collections.error} />
      {collections.error && (
        <button type="button" onClick={() => collections.refetch()}>
          Retry collections
        </button>
      )}
      {collections.isPending ? (
        <Loading label="Loading collections…" />
      ) : collections.data?.items.length ? (
        <div className="org-checklist">
          {collections.data.items.map((collection) => (
            <label className="org-check" key={collection.id}>
              <input
                type="checkbox"
                checked={value.includes(collection.id)}
                disabled={!value.includes(collection.id) && value.length >= 100}
                onChange={(e) =>
                  onChange(
                    e.target.checked
                      ? [...value, collection.id]
                      : value.filter((id) => id !== collection.id),
                  )
                }
              />
              <span>{collection.name}</span>
            </label>
          ))}
        </div>
      ) : (
        !collections.error && (
          <p className="muted">
            No collections yet. Create one on the{" "}
            <Link to="/collections">Collections page</Link>.
          </p>
        )
      )}
    </fieldset>
  );
}

export function OrganizationFilters({
  params,
  onChange,
}: {
  params: URLSearchParams;
  onChange: (value: URLSearchParams) => void;
}) {
  const tags = useQuery(query<{ items: NamedOrganization[] }>("/tags"));
  const collections = useCollections();
  return (
    <div className="org-filters">
      {(
        [
          ["tag_id", "tag", tags.data?.items],
          ["collection_id", "collection", collections.data?.items],
        ] as const
      ).map(([key, label, items]) => (
        <Field key={key} label={"Filter by " + label}>
          <select
            value={params.get(key) ?? ""}
            onChange={(e) =>
              onChange(updateParams(params, key, e.target.value))
            }
          >
            <option value="">
              All {label === "tag" ? "tags" : "collections"}
            </option>
            {params.get(key) &&
              !items?.some((item) => item.id === params.get(key)) && (
                <option value={params.get(key)!}>Selected {label}</option>
              )}
            {items?.map((item) => (
              <option value={item.id} key={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </Field>
      ))}
      <ErrorNote error={tags.error ?? collections.error} />
    </div>
  );
}

export function Collections() {
  const collections = useCollections();
  const editor = useSession().user.role !== "viewer";
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>();
  const [pending, setPending] = useState<{
    key: string;
    body: { name: string; description: string };
  }>();
  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const submission = pending ?? {
      key: randomId(),
      body: { name: name.trim(), description },
    };
    setPending(submission);
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ id: string }>("/collections", {
        method: "POST",
        ...submission,
      });
      setSaved(true);
      setPending(undefined);
      await changed();
      setTimeout(() => navigate("/collections/" + result.id), 0);
    } catch (error) {
      setError(error);
      if (!uncertainWrite(error)) setPending(undefined);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHead title="Collections" eyebrow="RELATED BOXES, TOGETHER">
        <Link className="button" to="/boxes">
          Your boxes
        </Link>
      </PageHead>
      <p className="muted">
        Group related boxes and see their contents together. Every item keeps
        its source box.
      </p>
      {editor && (
        <form className="panel org-create" onSubmit={create}>
          <h2>Create a collection</h2>
          <fieldset disabled={busy || !!pending} className="org-fieldset">
            <Field label="Collection name">
              <input
                required
                maxLength={120}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Camping gear"
              />
            </Field>
            <Field label="Description">
              <textarea
                maxLength={2000}
                rows={2}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </Field>
          </fieldset>
          <ErrorNote error={error} />
          {pending && !busy && (
            <p className="notice caution">
              The outcome is unknown. Retry the same request to safely finish
              creating this collection.
            </p>
          )}
          <button
            className="primary"
            disabled={busy || saved || !name.trim()}
            type="submit"
          >
            {busy
              ? "Saving…"
              : pending
                ? "Retry create collection"
                : "Create collection"}
          </button>
        </form>
      )}
      <ErrorNote error={collections.error} />
      {collections.error && (
        <button onClick={() => collections.refetch()}>Retry collections</button>
      )}
      {collections.isPending ? (
        <Loading />
      ) : collections.data?.items.length ? (
        <div className="org-collection-grid">
          {collections.data.items.map((collection) => (
            <article className="panel" key={collection.id}>
              <Link to={"/collections/" + collection.id}>
                <h2>{collection.name}</h2>
              </Link>
              {collection.description && (
                <p className="org-description">{collection.description}</p>
              )}
              <p className="muted">
                {collection.box_count} active boxes · {collection.item_count}{" "}
                item lines
                {collection.archived_box_count > 0 &&
                  ` · ${collection.archived_box_count} archived boxes`}
              </p>
              <Link className="button" to={"/collections/" + collection.id}>
                View contents
              </Link>
            </article>
          ))}
        </div>
      ) : (
        !collections.error && (
          <Empty title="No collections yet">
            <p>
              Bring related boxes together, such as camping gear or workshop
              supplies.
            </p>
          </Empty>
        )
      )}
      <Unsaved
        dirty={editor && !saved && (!!name || !!description || !!pending)}
      />
    </>
  );
}

function useOrganizationWrite() {
  const frozen = useRef<ReturnType<typeof freezeWrite> | undefined>(undefined);
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [conflict, setConflict] = useState(false);
  const running = useRef(false);
  async function run<T>(
    request: OrganizationWrite,
  ): Promise<{ value: T } | undefined> {
    if (running.current || conflict) return;
    frozen.current ??= freezeWrite(request);
    const { path, ...options } = frozen.current;
    running.current = true;
    setBusy(true);
    setPending(true);
    setError(null);
    try {
      const value = await api<T>(path, options);
      frozen.current = undefined;
      setPending(false);
      return { value };
    } catch (error) {
      setError(error);
      if (!uncertainWrite(error)) {
        frozen.current = undefined;
        setPending(false);
      }
      if (error instanceof ApiError && error.status === 412) setConflict(true);
    } finally {
      running.current = false;
      setBusy(false);
    }
  }
  return { run, pending, busy, error, conflict };
}

function WriteNotice({
  write,
  reload,
}: {
  write: ReturnType<typeof useOrganizationWrite>;
  reload: () => Promise<void>;
}) {
  const [loading, setLoading] = useState(false);
  const [reloadError, setReloadError] = useState<unknown>();
  return (
    <>
      <ErrorNote error={write.error} />
      {write.pending && !write.busy && (
        <p className="notice caution">
          The outcome is unknown. Retry the same request to safely finish this
          change.
        </p>
      )}
      {write.conflict && (
        <div className="notice caution">
          <h2>The server has a newer version</h2>
          <p>
            Your draft is still here. Reloading discards it. Copy anything you
            want to keep first.
          </p>
          <button
            type="button"
            disabled={loading}
            onClick={async () => {
              setLoading(true);
              setReloadError(null);
              try {
                await reload();
              } catch (error) {
                setReloadError(error);
              } finally {
                setLoading(false);
              }
            }}
          >
            Reload latest version
          </button>
          <ErrorNote error={reloadError} />
        </div>
      )}
    </>
  );
}

export function CollectionDetailPage() {
  const { collectionId } = useParams();
  const [params, setParams] = useSearchParams();
  const archived = params.get("include_archived") === "true";
  const collection = useQuery(
    query<CollectionDetail>(
      `/collections/${collectionId}?include_archived=${archived}`,
    ),
  );
  const editor = useSession().user.role !== "viewer";
  const [editing, setEditing] = useState<CollectionDetail>();
  const [deleting, setDeleting] = useState<CollectionDetail>();
  if (collection.isPending) return <Loading />;
  if (!collection.data)
    return (
      <>
        <ErrorNote error={collection.error} />
        <button onClick={() => collection.refetch()}>Retry collection</button>
        <Link to="/collections">All collections</Link>
      </>
    );
  const c = collection.data;
  if (editing && editor)
    return (
      <CollectionEditor
        key={editing.id + ":" + editing.version}
        initial={editing}
        close={() => setEditing(undefined)}
        reload={async () =>
          setEditing(await api<CollectionDetail>("/collections/" + editing.id))
        }
      />
    );
  const groupBy = params.get("group") === "item" ? "item" : "box";
  const groups = groupLines(
    c.items,
    groupBy,
    params.get("item_name") ?? "",
    params.get("box_code") ?? "",
  );
  return (
    <>
      <PageHead title={c.name} eyebrow="COLLECTION CONTENTS">
        <Link className="button" to="/collections">
          All collections
        </Link>
        {editor && (
          <button onClick={() => setEditing(structuredClone(c))}>
            Edit collection
          </button>
        )}
      </PageHead>
      <ErrorNote error={collection.error} />
      {c.description && <p className="org-description">{c.description}</p>}
      <p className="muted">
        {c.box_count} active boxes · {c.item_count} active item lines
        {c.archived_box_count > 0 &&
          ` · ${c.archived_box_count} archived boxes`}
      </p>
      <section className="panel">
        <h2>Boxes in this collection</h2>
        {c.boxes.length ? (
          <div className="org-members">
            {c.boxes.map((box) => (
              <Link
                className="org-badge"
                key={box.code}
                to={"/boxes/" + box.code}
              >
                {box.name} · {box.code}
                {box.lifecycle === "archived" && " · Archived"}
              </Link>
            ))}
          </div>
        ) : (
          <p className="muted">
            No boxes in this collection yet.
            {editor && " Use Edit collection to choose boxes."}
          </p>
        )}
      </section>
      <section className="panel">
        <h2>Combined contents</h2>
        <p className="muted">
          Each line stays with its source box. Quantities and units are shown as
          recorded; items are never merged or totaled.
        </p>
        <label className="org-check">
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) =>
              setParams(
                updateParams(
                  params,
                  "include_archived",
                  String(e.target.checked),
                ),
              )
            }
          />
          <span>Include archived boxes</span>
        </label>
        <div className="org-filters">
          <Field label="Group items by">
            <select
              value={groupBy}
              onChange={(e) =>
                setParams(updateParams(params, "group", e.target.value))
              }
            >
              <option value="box">Source box</option>
              <option value="item">Item name</option>
            </select>
          </Field>
          <Field label="Filter item name">
            <input
              type="search"
              value={params.get("item_name") ?? ""}
              onChange={(e) =>
                setParams(updateParams(params, "item_name", e.target.value), {
                  replace: true,
                })
              }
            />
          </Field>
          <Field label="Source box">
            <select
              value={params.get("box_code") ?? ""}
              onChange={(e) =>
                setParams(updateParams(params, "box_code", e.target.value))
              }
            >
              <option value="">All boxes</option>
              {c.boxes.map((box) => (
                <option key={box.code} value={box.code}>
                  {box.name} ({box.code})
                  {box.lifecycle === "archived" && " · Archived"}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {groups.length ? (
          groups.map((group) => (
            <section
              key={group.key}
              className="org-item-group"
              aria-label={group.label}
            >
              <h3>{group.label}</h3>
              {group.lines.map((line) => (
                <article
                  className="org-item-line"
                  key={line.box_code + ":" + line.item.id}
                >
                  <div>
                    <h3>{line.item.name}</h3>
                    {line.box_lifecycle === "archived" && (
                      <span className="badge caution">Archived</span>
                    )}
                  </div>
                  <p>{quantityLabel(line.item)}</p>
                  <Link to={"/boxes/" + line.box_code}>
                    {line.box_name}
                    <small>
                      <code>{line.box_code}</code>
                    </small>
                  </Link>
                </article>
              ))}
            </section>
          ))
        ) : (
          <Empty title="No items to show">
            <p>
              {c.items.length
                ? "Try another item name or source box."
                : "Add confirmed items to a member box, or include archived boxes."}
            </p>
          </Empty>
        )}
      </section>
      {editor && (
        <section className="panel">
          <h2>Collection settings</h2>
          <p>
            Deleting this collection removes only the group. Its boxes,
            contents, tags, and photos remain.
          </p>
          <button
            className="danger"
            onClick={() => setDeleting(structuredClone(c))}
          >
            Delete collection
          </button>
        </section>
      )}
      {deleting && (
        <DeleteCollection
          key={deleting.id + ":" + deleting.version}
          collection={deleting}
          close={() => setDeleting(undefined)}
          reload={async () =>
            setDeleting(
              await api<CollectionDetail>("/collections/" + deleting.id),
            )
          }
        />
      )}
    </>
  );
}

function CollectionEditor({
  initial,
  close,
  reload,
}: {
  initial: CollectionDetail;
  close: () => void;
  reload: () => Promise<void>;
}) {
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);
  const [selected, setSelected] = useState(
    initial.boxes.map((box) => box.code),
  );
  const [filter, setFilter] = useState("");
  const [saved, setSaved] = useState(false);
  const write = useOrganizationWrite();
  const boxes = useQuery({
    queryKey: ["organization-all-boxes"],
    queryFn: ({ signal }) => loadAllBoxes(signal),
    refetchOnWindowFocus: false,
  });
  const membershipChanged = !sameSelection(
    selected,
    initial.boxes.map((box) => box.code),
  );
  const dirty =
    !saved &&
    (name !== initial.name ||
      description !== initial.description ||
      membershipChanged ||
      write.pending);
  const available = new Map<string, Schema<"BoxSummary">>(
    initial.boxes.map((box) => [box.code, box]),
  );
  for (const box of boxes.data ?? []) available.set(box.code, box);
  function cancel() {
    if (!dirty || confirm("Discard these unsaved collection changes?")) close();
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const result = await write.run<CollectionDetail>({
      path: "/collections/" + initial.id,
      method: "PATCH",
      etag: tag("collection", initial.id, initial.version),
      body: {
        name: name.trim(),
        description,
        ...(membershipChanged ? { box_codes: [...selected] } : {}),
      },
    });
    if (result) {
      setSaved(true);
      await changed();
      close();
    }
  }
  return (
    <>
      <PageHead title="Edit collection" eyebrow="RELATED BOXES, TOGETHER" />
      <form className="panel form-panel" onSubmit={save}>
        <fieldset
          className="org-fieldset"
          disabled={write.busy || write.pending || saved}
        >
          <Field label="Collection name">
            <input
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label="Description">
            <textarea
              maxLength={2000}
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </Field>
          <fieldset className="org-fieldset">
            <legend>Boxes in this collection</legend>
            <p className="muted">
              {selected.length} selected. Archived membership stays unchanged;
              restore a box before adding or removing it.
            </p>
            <ErrorNote error={boxes.error} />
            {boxes.error && (
              <button type="button" onClick={() => boxes.refetch()}>
                Retry box list
              </button>
            )}
            {boxes.isPending ? (
              <Loading label="Loading all boxes…" />
            ) : (
              <>
                <Field label="Filter boxes">
                  <input
                    type="search"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  />
                </Field>
                <div className="org-checklist">
                  {[...available.values()]
                    .filter((box) =>
                      `${box.name} ${box.code}`
                        .toLocaleLowerCase()
                        .includes(filter.toLocaleLowerCase()),
                    )
                    .map((box) => (
                      <label className="org-check" key={box.code}>
                        <input
                          type="checkbox"
                          aria-label={`${box.name} (${box.code})`}
                          checked={selected.includes(box.code)}
                          disabled={
                            box.lifecycle === "archived" ||
                            !!boxes.error ||
                            (!selected.includes(box.code) &&
                              selected.length >= 500)
                          }
                          onChange={(e) =>
                            setSelected(
                              toggleMembership(
                                selected,
                                box.code,
                                e.target.checked,
                                box.lifecycle === "archived",
                              ),
                            )
                          }
                        />
                        <span>
                          {box.name}
                          <small>
                            <code>{box.code}</code>
                            {box.lifecycle === "archived" &&
                              " · Archived — restore to change"}
                          </small>
                        </span>
                      </label>
                    ))}
                </div>
                {!available.size && !boxes.error && (
                  <p className="muted">
                    No boxes yet. Create a box, then add it here.
                  </p>
                )}
              </>
            )}
          </fieldset>
        </fieldset>
        <WriteNotice write={write} reload={reload} />
        <div className="form-footer">
          <span className="muted">
            {dirty ? "Unsaved changes" : "No unsaved changes"}
          </span>
          <div className="actions">
            <button type="button" disabled={write.busy} onClick={cancel}>
              Cancel
            </button>
            <button
              type="submit"
              className="primary"
              disabled={
                write.busy ||
                write.conflict ||
                saved ||
                !name.trim() ||
                (membershipChanged && (!!boxes.error || boxes.isPending))
              }
            >
              {write.busy
                ? "Saving…"
                : write.pending
                  ? "Retry save collection"
                  : "Save collection"}
            </button>
          </div>
        </div>
      </form>
      <Unsaved dirty={dirty} />
    </>
  );
}

function DeleteCollection({
  collection,
  close,
  reload,
}: {
  collection: CollectionDetail;
  close: () => void;
  reload: () => Promise<void>;
}) {
  const write = useOrganizationWrite();
  const navigate = useNavigate();
  const [deleted, setDeleted] = useState(false);
  return (
    <Modal
      title="Delete this collection?"
      close={() => {
        if (
          !write.busy &&
          (!write.pending ||
            confirm(
              "This request may have completed. Close without resolving its outcome?",
            ))
        )
          close();
      }}
    >
      <p>
        Delete “{collection.name}”? Only the group is removed. All boxes,
        contents, tags, and photos remain.
      </p>
      <WriteNotice write={write} reload={reload} />
      <div className="actions">
        <button disabled={write.busy || write.pending} onClick={close}>
          Cancel
        </button>
        <button
          className="danger"
          disabled={write.busy || write.conflict || deleted}
          onClick={async () => {
            const result = await write.run<void>({
              path: "/collections/" + collection.id,
              method: "DELETE",
              etag: tag("collection", collection.id, collection.version),
            });
            if (result) {
              setDeleted(true);
              await changed();
              setTimeout(() => navigate("/collections"), 0);
            }
          }}
        >
          {write.busy
            ? "Deleting…"
            : write.pending
              ? "Retry delete collection"
              : "Delete collection"}
        </button>
      </div>
      <Unsaved dirty={!deleted && write.pending} />
    </Modal>
  );
}
