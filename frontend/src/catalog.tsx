import { PinLabel, PrintListLink, usePrintList } from "./print-list";
import { lazy, Suspense, useEffect, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
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
  type Box,
  type Schema,
} from "./api";
import { useSession } from "./session";
import {
  BoxCard,
  Code,
  Empty,
  ErrorNote,
  Field,
  Icon,
  Loading,
  Markdown,
  MarkdownEditor,
  Modal,
  OrganizationBadges,
  PageHead,
  SearchBar,
  Unsaved,
  type SubmitEvent,
} from "./components";
import { Inventory, Photos } from "./contents";
import {
  TagInput,
  CollectionChecklist,
  OrganizationFilters,
} from "./organization";
import {
  addTag,
  organizationQuery,
  sameSelection,
  uncertainWrite,
  updateParams,
} from "./organization-helpers";
const PdfPreview = lazy(() => import("./pdf-preview"));

export function Home() {
  const session = useSession();
  const boxes = useQuery(query<Schema<"BoxPage">>("/boxes?limit=6"));
  return (
    <>
      <section className="hero">
        <div className="eyebrow">
          <span className="signal-dot" /> YOUR THINGS. YOUR SPACE. YOUR DATA.
        </div>
        <h1 tabIndex={-1}>
          Find what
          <br />
          you <span>stored.</span>
        </h1>
        <p>
          Every box has a story.
          <br className="mobile-break" /> Know exactly what’s inside.
        </p>
        <SearchBar />
        <div className="hero-meta">
          <Icon name="shield" size={16} />
          Private inventory, running on your Boxen host.
          <Link to="/scan">
            Or scan a label <Icon name="arrow" size={16} />
          </Link>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="orbit" />
          <Icon size={180} />
          <span>INDEX / LOCATE / RETRIEVE</span>
        </div>
      </section>
      <div className="section-head">
        <div>
          <div className="eyebrow">YOUR COLLECTION</div>
          <h2>Recently updated</h2>
        </div>
        <div className="actions">
          <Link className="button" to="/boxes">
            View all
          </Link>
          {session.user.role !== "viewer" && (
            <Link className="button primary" to="/boxes/new">
              <Icon name="plus" />
              New box
            </Link>
          )}
        </div>
      </div>
      <ErrorNote error={boxes.error} />
      {boxes.isPending ? (
        <Loading />
      ) : boxes.data?.items.length ? (
        <div className="box-grid">
          {boxes.data.items.map((box) => (
            <BoxCard key={box.code} box={box} />
          ))}
        </div>
      ) : (
        <Empty title="No boxes yet">
          <p>A place for everything starts with your first box.</p>
          {session.user.role !== "viewer" && (
            <Link className="button primary" to="/boxes/new">
              Create your first box
            </Link>
          )}
        </Empty>
      )}
    </>
  );
}

export function Boxes() {
  const printList = usePrintList();
  const session = useSession();
  const [params, setParams] = useSearchParams();
  const lifecycle = params.get("lifecycle") ?? "active",
    sort = params.get("sort") ?? "updated_desc";
  const filters = organizationQuery(params);
  const boxes = useInfiniteQuery({
    queryKey: ["boxes", lifecycle, sort, filters],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Schema<"BoxPage">>(
        `/boxes?limit=24&lifecycle=${encodeURIComponent(lifecycle)}&sort=${encodeURIComponent(sort)}${filters}${pageParam ? "&cursor=" + encodeURIComponent(pageParam) : ""}`,
      ),
    getNextPageParam: (page) => page.page.next_cursor ?? undefined,
  });
  return (
    <>
      <PageHead title="Your boxes">
        <Link className="button" to="/collections">
          Collections
        </Link>
        {session.user.role !== "viewer" && (
          <Link className="button primary" to="/boxes/new">
            <Icon name="plus" />
            New box
          </Link>
        )}
      </PageHead>
      <div className="filters">
        <SearchBar params={params} />
        <Field label="Show">
          <select
            value={lifecycle}
            onChange={(e) =>
              setParams(updateParams(params, "lifecycle", e.target.value))
            }
          >
            <option value="active">Active boxes</option>
            <option value="archived">Archived boxes</option>
            <option value="all">All boxes</option>
          </select>
        </Field>
        <Field label="Sort">
          <select
            value={sort}
            onChange={(e) =>
              setParams(updateParams(params, "sort", e.target.value))
            }
          >
            <option value="updated_desc">Recently updated</option>
            <option value="name_asc">Name A–Z</option>
            <option value="created_desc">Newest first</option>
          </select>
        </Field>
      </div>
      <OrganizationFilters params={params} onChange={setParams} />
      {session.user.role !== "viewer" && (
        <div className="print-toolbar">
          <PrintListLink />
          <button
            disabled={!boxes.data?.pages.some((p) => p.items.length)}
            onClick={() =>
              printList.add(
                boxes.data?.pages.flatMap((p) =>
                  p.items.map((box) => box.code),
                ) ?? [],
              )
            }
          >
            Pin all loaded boxes
          </button>
          {printList.notice && <span role="status">{printList.notice}</span>}
        </div>
      )}
      <ErrorNote error={boxes.error} />
      {boxes.isPending ? (
        <Loading />
      ) : boxes.data?.pages[0].items.length ? (
        <>
          <div className="box-grid">
            {boxes.data.pages
              .flatMap((p) => p.items)
              .map((box) => (
                <BoxCard key={box.code} box={box} />
              ))}
          </div>
          {boxes.hasNextPage && (
            <button
              className="load-more"
              disabled={boxes.isFetchingNextPage}
              onClick={() => boxes.fetchNextPage()}
            >
              {boxes.isFetchingNextPage ? "Loading…" : "Load more"}
            </button>
          )}
        </>
      ) : (
        <Empty title="No boxes here">
          <p>Try another filter or create a new box.</p>
        </Empty>
      )}
    </>
  );
}

export function BoxEditor() {
  const { boxCode } = useParams();
  const existing = useQuery({
    ...query<Box>("/boxes/" + boxCode),
    enabled: !!boxCode,
  });
  if (boxCode && existing.isPending) return <Loading />;
  if (existing.error) return <ErrorNote error={existing.error} />;
  return <EditorForm key={boxCode ?? "new"} existing={existing.data} />;
}
function EditorForm({ existing: initial }: { existing?: Box }) {
  // Keep the version that the draft was based on. Background refreshes must not
  // silently advance its precondition and overwrite somebody else's edit.
  const [existing] = useState(initial);
  const navigate = useNavigate();
  const session = useSession();
  const [name, setName] = useState(existing?.name ?? ""),
    [description, setDescription] = useState(
      existing?.description.source ?? "",
    );
  const [tags, setTags] = useState(existing?.tags.map((tag) => tag.name) ?? []);
  const [tagInput, setTagInput] = useState("");
  const [collectionIds, setCollectionIds] = useState(
    existing?.collections.map((collection) => collection.id) ?? [],
  );
  const [pending, setPending] = useState<{
    key: string;
    body: {
      name: string;
      description_markdown: string;
      tags: string[];
      collection_ids: string[];
    };
  }>();
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(),
    [saved, setSaved] = useState(false),
    [latest, setLatest] = useState<Box>();
  const dirty =
    !saved &&
    (name !== (existing?.name ?? "") ||
      description !== (existing?.description.source ?? "") ||
      !!tagInput ||
      !sameSelection(tags, existing?.tags.map((tag) => tag.name) ?? []) ||
      !sameSelection(
        collectionIds,
        existing?.collections.map((collection) => collection.id) ?? [],
      ) ||
      !!pending);
  async function save(e: SubmitEvent) {
    e.preventDefault();
    if (busy || conflict || saved) return;
    setBusy(true);
    setError(null);
    try {
      const submission = pending ?? {
        key: randomId(),
        body: {
          name,
          description_markdown: description,
          tags: addTag(tags, tagInput),
          collection_ids: [...collectionIds],
        },
      };
      setPending(submission);
      setTags(submission.body.tags);
      setTagInput("");
      const result = await api<Box>(
        existing ? "/boxes/" + existing.code : "/boxes",
        {
          method: existing ? "PATCH" : "POST",
          etag: existing
            ? tag("box", existing.code, existing.version)
            : undefined,
          ...submission,
        },
      );
      setSaved(true);
      setPending(undefined);
      await changed();
      setTimeout(() => navigate("/boxes/" + result.code), 0);
    } catch (e) {
      setError(e);
      if (!uncertainWrite(e)) setPending(undefined);
      if (e instanceof ApiError && e.status === 412 && existing) {
        setConflict(true);
        void api<Box>("/boxes/" + existing.code)
          .then(setLatest)
          .catch(() => {});
      }
    } finally {
      setBusy(false);
    }
  }
  if (session.user.role === "viewer")
    return (
      <Empty title="Editing is unavailable">
        <p>Ask an editor or owner to update the inventory.</p>
      </Empty>
    );
  if (existing?.lifecycle === "archived")
    return (
      <Empty title="Archived box is read only">
        <p>Restore this box before changing its tags or collections.</p>
        <Link to={"/boxes/" + existing.code}>Back to box</Link>
      </Empty>
    );
  return (
    <>
      <PageHead
        title={existing ? "Edit box" : "Create a box"}
        eyebrow="GIVE IT A PLACE"
      />
      <form className="panel form-panel" onSubmit={save}>
        <fieldset
          className="org-fieldset"
          disabled={busy || !!pending || saved}
        >
          <Field
            label="Box name"
            help="A short, recognizable name for the box and its printed label."
          >
            <input
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              placeholder="e.g. Workshop · cables & adapters"
            />
          </Field>
          <MarkdownEditor value={description} onChange={setDescription} />
          <TagInput
            value={tags}
            onChange={setTags}
            input={tagInput}
            onInput={setTagInput}
          />
          <CollectionChecklist
            value={collectionIds}
            onChange={setCollectionIds}
          />
        </fieldset>
        <ErrorNote error={error} />
        {pending && !busy && (
          <p className="notice caution">
            The outcome is unknown. Retry the same request to safely finish
            saving this box.
          </p>
        )}
        {conflict && (
          <div className="notice caution">
            <h2>The server has a newer version</h2>
            <p>
              Your draft is still above. Compare and copy it before reloading.
            </p>
            {latest && (
              <>
                <h3>{latest.name}</h3>
                <pre>{latest.description.source}</pre>
                <OrganizationBadges
                  tags={latest.tags}
                  collections={latest.collections}
                />
              </>
            )}
            <button
              type="button"
              onClick={() => {
                if (
                  confirm("Discard this local draft and reload the latest box?")
                )
                  window.location.reload();
              }}
            >
              Reload latest version
            </button>
          </div>
        )}
        <div className="form-footer">
          <span className="muted">
            {dirty ? "Unsaved changes" : "Saved locally when you submit"}
          </span>
          <div className="actions">
            <Link
              className="button"
              to={existing ? "/boxes/" + existing.code : "/boxes"}
            >
              Cancel
            </Link>
            <button
              className="primary"
              type="submit"
              disabled={busy || conflict || saved}
            >
              {busy
                ? "Saving…"
                : pending
                  ? "Retry save"
                  : existing
                    ? "Save changes"
                    : "Create box"}
            </button>
          </div>
        </div>
      </form>
      <Unsaved dirty={dirty} />
    </>
  );
}

export function BoxDetail() {
  const { boxCode } = useParams();
  const box = useQuery(query<Box>("/boxes/" + boxCode));
  const [action, setAction] = useState(""),
    [confirmation, setConfirmation] = useState(""),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  if (box.isPending) return <Loading />;
  if (box.error || !box.data) return <ErrorNote error={box.error} />;
  const b = box.data,
    editable = b.allowed_actions.includes("box.edit");
  async function lifecycle() {
    setBusy(true);
    try {
      await api("/boxes/" + b.code + "/" + action, {
        method: "POST",
        etag: tag("box", b.code, b.version),
        body:
          action === "purge" ? { confirmation_code: confirmation } : undefined,
      });
      setAction("");
      await changed();
      if (action === "purge") navigate("/boxes");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHead
        title={b.name}
        eyebrow={
          b.lifecycle === "archived"
            ? "ARCHIVED BOX · READ ONLY"
            : "BOX CONTENTS"
        }
      >
        {editable && (
          <Link className="button" to={"/boxes/" + b.code + "/edit"}>
            Edit box
          </Link>
        )}
        {b.allowed_actions.includes("label.render") && (
          <Link className="button primary" to={"/boxes/" + b.code + "/label"}>
            Print label
          </Link>
        )}
      </PageHead>
      <PinLabel box={b} />
      <Code code={b.code} />
      <OrganizationBadges tags={b.tags} collections={b.collections} />
      <div className="detail-layout">
        <div>
          <section className="panel">
            <div className="section-head">
              <h2>Description</h2>
              <span className="eyebrow">01 / CONTEXT</span>
            </div>
            {b.description.source ? (
              <Markdown html={b.description.html} />
            ) : (
              <p className="muted">
                No description yet. Add a note to make this box easier to find.
              </p>
            )}
          </section>
          <Photos box={b} editable={editable} />
          <Inventory box={b} editable={editable} />
        </div>
        <aside className="detail-rail">
          <section className="panel box-manifest">
            <div className="eyebrow">BOX MANIFEST</div>
            <Icon size={74} />
            <dl>
              <div>
                <dt>Confirmed items</dt>
                <dd>{b.item_count}</dd>
              </div>
              <div>
                <dt>Photos</dt>
                <dd>{b.image_count}</dd>
              </div>
              <div>
                <dt>AI suggestions</dt>
                <dd>{b.pending_observation_count}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{b.lifecycle}</dd>
              </div>
            </dl>
            {b.pending_observation_count > 0 &&
              b.allowed_actions.includes("observation.review") && (
                <Link className="button ai" to={"/review?box=" + b.code}>
                  Review suggestions
                </Link>
              )}
            <p>
              <small>
                Created {new Date(b.created_at).toLocaleString()}
                <br />
                Updated {new Date(b.updated_at).toLocaleString()}
              </small>
            </p>
          </section>
          <section className="panel">
            <h2>Keep it findable.</h2>
            <p className="muted">
              A label connects this box to everything inside. Scan it later, or
              type its code.
            </p>
            {b.allowed_actions.includes("label.render") && (
              <Link className="button" to={"/boxes/" + b.code + "/label"}>
                <Icon name="scan" />
                Make a label
              </Link>
            )}
          </section>
          <section className="panel">
            <h2>Box lifecycle</h2>
            <p className="muted">
              Archiving preserves every item and photo. Restore the box to edit
              it again.
            </p>
            {["archive", "restore", "purge"]
              .filter((a) =>
                b.allowed_actions.some((allowed) => allowed === "box." + a),
              )
              .map((a) => (
                <button
                  key={a}
                  className={a === "purge" ? "danger" : "button"}
                  onClick={() => {
                    setAction(a);
                    setError(null);
                    setConfirmation("");
                  }}
                >
                  {a === "purge"
                    ? "Permanently delete"
                    : a === "archive"
                      ? "Archive box"
                      : "Restore box"}
                </button>
              ))}
          </section>
        </aside>
      </div>
      {action && (
        <Modal
          title={
            action === "purge"
              ? "Permanently delete this box?"
              : action === "archive"
                ? "Archive this box?"
                : "Restore this box?"
          }
          close={() => !busy && setAction("")}
        >
          <p>
            {action === "purge"
              ? "This permanently removes the box, contents, and photo references. Recovery requires a verified backup. A backup verified within the past 24 hours is required."
              : action === "archive"
                ? "The box remains searchable but becomes read-only. Pending analysis will be cancelled."
                : "This box and its contents will be editable again."}
          </p>
          {action === "purge" && (
            <Field label={"Type " + b.code + " to confirm"}>
              <input
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
              />
            </Field>
          )}
          <ErrorNote error={error} />
          <div className="actions">
            <button disabled={busy} onClick={() => setAction("")}>
              Cancel
            </button>
            <button
              disabled={busy || (action === "purge" && confirmation !== b.code)}
              className={action === "purge" ? "danger" : "primary"}
              onClick={lifecycle}
            >
              {busy ? "Working…" : "Confirm " + action}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}

export function Search() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "",
    archived = params.get("archived") === "true";
  const filters = organizationQuery(params);
  const results = useInfiniteQuery({
    queryKey: ["search", q, archived, filters],
    initialPageParam: "",
    queryFn: ({ pageParam }) =>
      api<Schema<"SearchPage">>(
        `/search?q=${encodeURIComponent(q)}&include_archived=${archived}${filters}${pageParam ? "&cursor=" + encodeURIComponent(pageParam) : ""}`,
      ),
    getNextPageParam: (p) => p.page.next_cursor ?? undefined,
    enabled: !!q,
  });
  return (
    <>
      <PageHead title="Find your contents" eyebrow="SEARCH THE LOCAL INDEX" />
      <SearchBar initial={q} params={params} />
      <OrganizationFilters params={params} onChange={setParams} />
      <label className="check">
        <input
          type="checkbox"
          checked={archived}
          onChange={(e) =>
            setParams(
              updateParams(params, "archived", String(e.target.checked)),
            )
          }
        />
        Include archived boxes
      </label>
      <ErrorNote error={results.error} />
      {q && results.isPending ? (
        <Loading label="Searching boxes and contents…" />
      ) : results.data?.pages[0].items.length ? (
        <div className="search-results">
          {results.data.pages
            .flatMap((p) => p.items)
            .map((r) => (
              <article key={r.box.code} className="panel search-result">
                <Link to={"/boxes/" + r.box.code}>
                  {r.box.representative_thumbnail_url ? (
                    <img
                      src={r.box.representative_thumbnail_url}
                      alt=""
                      loading="lazy"
                      decoding="async"
                    />
                  ) : (
                    <Icon size={60} />
                  )}
                  <div>
                    <code>{r.box.code}</code>
                    <h2>{r.box.name}</h2>
                  </div>
                  <Icon name="arrow" />
                </Link>
                <OrganizationBadges
                  tags={r.box.tags}
                  collections={r.box.collections}
                />
                {r.exact_code && <span className="badge">Exact code</span>}
                {r.matches.slice(0, 3).map((match, i) => (
                  <p key={i}>
                    <span className="eyebrow">
                      {match.field.replace("_", " ")}{" "}
                    </span>
                    <Highlighted text={match.snippet} ranges={match.ranges} />
                  </p>
                ))}
                <PinLabel box={r.box} />
                {r.matching_items.length > 0 && (
                  <small>
                    Matching items:{" "}
                    {r.matching_items.map((i) => i.name).join(", ")}
                  </small>
                )}
              </article>
            ))}
          {results.hasNextPage && (
            <button onClick={() => results.fetchNextPage()}>Load more</button>
          )}
        </div>
      ) : (
        <Empty title={q ? "Nothing found yet" : "What are you looking for?"}>
          <p>Search a box name, an item, notes, or its printed code.</p>
          <Link className="button" to="/scan">
            Scan a label
          </Link>
        </Empty>
      )}
    </>
  );
}
function Highlighted({
  text,
  ranges,
}: {
  text: string;
  ranges: { start: number; end: number }[];
}) {
  const units = Array.from(text);
  return (
    <>
      {units.map((char, i) =>
        ranges.some((r) => i >= r.start && i < r.end) ? (
          <mark key={i}>{char}</mark>
        ) : (
          char
        ),
      )}
    </>
  );
}

export function Labels() {
  const { boxCode } = useParams();
  const profiles = useQuery(
    query<{ items: Schema<"LabelProfileView">[] }>("/label-profiles"),
  );
  const box = useQuery(query<Box>("/boxes/" + boxCode));
  const [profile, setProfile] = useState("roll-62x29-mm-v1");
  const url = `/api/v1/boxes/${boxCode}/label.pdf?profile=${profile}`;
  return (
    <>
      <PageHead title="Print a box label" eyebrow="FROM DIGITAL TO PHYSICAL">
        <PrintListLink />
      </PageHead>
      {box.data && <PinLabel box={box.data} />}
      <ErrorNote error={profiles.error ?? box.error} />
      <div className="panel">
        <Field label="Label size">
          <select value={profile} onChange={(e) => setProfile(e.target.value)}>
            {profiles.data?.items.map((p) => (
              <option key={p.key} value={p.key}>
                {p.display_name}
              </option>
            ))}
          </select>
        </Field>
        <p className="notice">
          Print at <strong>100% / actual size</strong>. Turn off “Fit to page.”
          Keep the white border around the QR code clear.
        </p>
        <div className="label-paper">
          <Suspense fallback={<Loading label="Loading local PDF preview…" />}>
            <PdfPreview url={url} />
          </Suspense>
          <a
            className="button primary"
            href={url}
            target="_blank"
            rel="noreferrer"
          >
            Open exact-size PDF preview
          </a>
        </div>
        <div className="actions">
          <a className="button primary" href={url} download>
            Download PDF
          </a>
          <Link className="button" to={"/boxes/" + boxCode}>
            Back to box
          </Link>
        </div>
        <p className="muted">
          Labels contain only the box name and code—never the inventory. Anyone
          on your local network can open the box according to this host’s access
          settings.
        </p>
      </div>
    </>
  );
}
