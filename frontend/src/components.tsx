import { PinLabel } from "./print-list";
import {
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
  type ReactElement,
  type FormEvent,
} from "react";
import { Link, useBlocker, useNavigate, useLocation } from "react-router-dom";
import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";
import { api, ApiError, type Schema } from "./api";
import {
  searchIntent,
  suggestionHref,
  suggestionLabels,
  suggestionParams,
  type Suggestion,
} from "./search-suggestions";

export function Icon({
  name = "box",
  size = 22,
}: {
  name?: string;
  size?: number;
}) {
  const paths: Record<string, string> = {
    box: "M3 6l9-4 9 4v12l-9 4-9-4V6zm0 0l9 4 9-4M12 10v12",
    home: "M3 10l9-8 9 8M5 9v12h5v-7h4v7h5V9",
    scan: "M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5M7 7h3v3H7zM14 7h3v3h-3zM7 14h3v3H7zM14 14h3v3h-3z",
    review: "M12 2l2.8 6.4L22 11l-7.2 2.6L12 21l-2.8-7.4L2 11l7.2-2.6L12 2z",
    system: "M3 5h18v6H3zM3 15h18v6H3zM6 8h1M6 18h1M15 8h3M15 18h3",
    search: "M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14zm5 12l6 6",
    plus: "M12 4v16M4 12h16",
    arrow: "M4 12h16M14 6l6 6-6 6",
    photo: "M3 5h18v15H3zM3 16l5-5 5 5 3-3 5 5M15 9h.01",
    logout: "M10 3H3v18h7M9 12h12M16 7l5 5-5 5",
    shield: "M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6l9-4zM8 12l3 3 5-6",
  };
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={paths[name] ?? paths.box} />
    </svg>
  );
}
export function ErrorNote({ error }: { error: unknown }) {
  return error ? (
    <div role="alert" className="notice error">
      {error instanceof Error
        ? error.message
        : "The operation could not complete."}
      {error instanceof ApiError && error.fields.length > 0 && (
        <ul>
          {error.fields.map((field, index) => (
            <li key={field.path + index}>
              {fieldLabel(field.path)}: {field.message}
            </li>
          ))}
        </ul>
      )}
      {error instanceof ApiError && error.requestId && (
        <small>Request {error.requestId}</small>
      )}
    </div>
  ) : null;
}

function fieldLabel(path: string) {
  const name = path.split("/").filter(Boolean).at(-1);
  if (name?.toLowerCase() === "x-boxen-setup-token")
    return "One-time setup token";
  return name
    ? name
        .replace(/~1/g, "/")
        .replace(/~0/g, "~")
        .replace(/_/g, " ")
        .replace(/^./, (c) => c.toUpperCase())
    : "Request";
}
export function Loading({
  label = "Loading local inventory…",
}: {
  label?: string;
}) {
  return (
    <div className="loading" role="status">
      <span className="loading-line" />
      {label}
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <Icon size={44} />
      <h2>{title}</h2>
      {children}
    </div>
  );
}
export function PageHead({
  eyebrow,
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        <div className="eyebrow">{eyebrow ?? "YOUR LOCAL INVENTORY"}</div>
        <h1 tabIndex={-1}>{title}</h1>
      </div>
      <div className="actions">{children}</div>
    </header>
  );
}
export function Field({
  label,
  help,
  error,
  children,
}: {
  label: string;
  help?: string;
  error?: string;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div className={"field" + (error ? " invalid" : "")}>
      <label htmlFor={id}>{label}</label>
      {isValidElement(children)
        ? cloneElement(children as ReactElement<Record<string, unknown>>, {
            id,
            "aria-invalid": error
              ? true
              : (children.props as Record<string, unknown>)["aria-invalid"],
            "aria-describedby":
              [
                (children.props as Record<string, unknown>)["aria-describedby"],
                help ? id + "-help" : "",
                error ? id + "-error" : "",
              ]
                .filter(Boolean)
                .join(" ") || undefined,
          })
        : children}
      {help && <small id={id + "-help"}>{help}</small>}
      {error && (
        <small id={id + "-error"} className="field-error">
          {error}
        </small>
      )}
    </div>
  );
}
export function SearchBar({
  initial = "",
  compact = false,
  params,
}: {
  initial?: string;
  compact?: boolean;
  params?: URLSearchParams;
}) {
  const [value, setValue] = useState(initial);
  const navigate = useNavigate();
  const location = useLocation();
  const popupId = useId();
  // Tie focus to the route synchronously. A delayed navigation effect must not
  // close suggestions after the user has already started typing on the new page.
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const focused = focusKey === location.key;
  function setFocused(value: boolean) {
    setFocusKey(value ? location.key : null);
  }
  const [dismissed, setDismissed] = useState(false);
  const [composing, setComposing] = useState(false);
  const [active, setActive] = useState(-1);
  const [result, setResult] = useState<{
    key: string;
    items: Suggestion[];
    phase: "loading" | "ready" | "error";
  } | null>(null);
  const filters =
    params ??
    new URLSearchParams(
      ["/search", "/boxes"].includes(location.pathname) ? location.search : "",
    );
  const intent = searchIntent(value);
  const requestKey = suggestionParams(value, filters).toString();
  const eligible = focused && !dismissed && !composing && intent !== "none";
  const current = result?.key === requestKey ? result : null;
  const items = eligible && current?.phase === "ready" ? current.items : [];
  const expanded = eligible && !!current;
  const status = !expanded
    ? ""
    : current?.phase === "loading"
      ? "Looking for suggestions…"
      : current?.phase === "error"
        ? "Suggestions unavailable. You can still submit Search."
        : items.length
          ? `${items.length} suggestions. Use arrow keys, then Enter, or tap a result.`
          : "No suggestions. Submit Search to search all names and descriptions.";
  useEffect(() => setValue(initial), [initial]);
  useEffect(() => {
    setActive(-1);
    if (!eligible) return;
    const controller = new AbortController();
    let cancelled = false;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    const timer = setTimeout(() => {
      setResult({ key: requestKey, items: [], phase: "loading" });
      deadline = setTimeout(() => {
        if (cancelled) return;
        controller.abort();
        setResult({ key: requestKey, items: [], phase: "error" });
      }, 5_000);
      void api<Schema<"SearchSuggestions">>(
        "/search/suggestions?" + requestKey,
        {
          signal: controller.signal,
        },
      )
        .then((data) => {
          if (!cancelled && !controller.signal.aborted)
            setResult({
              key: requestKey,
              items: data.suggestions,
              phase: "ready",
            });
        })
        .catch(() => {
          if (!cancelled && !controller.signal.aborted)
            setResult({ key: requestKey, items: [], phase: "error" });
        })
        .finally(() => clearTimeout(deadline));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      clearTimeout(deadline);
      controller.abort();
    };
  }, [requestKey, eligible]);
  useEffect(() => {
    if (active >= 0 && items[active])
      document
        .getElementById(`${popupId}-${active}`)
        ?.scrollIntoView({ block: "nearest" });
  }, [active, popupId, items]);
  function choose(item: Suggestion) {
    setDismissed(true);
    setFocused(false);
    setActive(-1);
    navigate(suggestionHref(item, filters));
  }
  return (
    <form
      className={"searchbar " + (compact ? "compact" : "")}
      role="search"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setFocused(false);
          setActive(-1);
        }
      }}
      onSubmit={(e) => {
        e.preventDefault();
        if (composing) return;
        if (value.trim()) {
          const next = new URLSearchParams(filters);
          next.set("q", value.trim());
          next.delete("cursor");
          if (
            next.get("lifecycle") === "archived" ||
            next.get("lifecycle") === "all"
          )
            next.set("archived", "true");
          setDismissed(true);
          setActive(-1);
          navigate("/search?" + next.toString());
        }
      }}
    >
      <Icon name="search" />
      <label
        className="sr-only"
        htmlFor={compact ? "global-search" : "page-search"}
      >
        Search boxes and contents
      </label>
      <input
        id={compact ? "global-search" : "page-search"}
        value={value}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={expanded}
        aria-controls={expanded ? popupId : undefined}
        aria-activedescendant={
          expanded && items[active] ? `${popupId}-${active}` : undefined
        }
        aria-describedby={popupId + "-help"}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="none"
        spellCheck={false}
        onFocus={() => {
          setFocused(true);
          setDismissed(false);
        }}
        onChange={(e) => {
          setValue(e.target.value);
          setFocused(true);
          setDismissed(false);
          setActive(-1);
        }}
        onCompositionStart={() => {
          setComposing(true);
          setActive(-1);
        }}
        onCompositionEnd={() => setComposing(false)}
        onKeyDown={(event) => {
          if (composing || event.nativeEvent.isComposing) return;
          if (event.key === "Escape") {
            event.preventDefault();
            setDismissed(true);
            setActive(-1);
          } else if (["ArrowDown", "ArrowUp"].includes(event.key)) {
            if (!eligible) {
              setDismissed(false);
              return;
            }
            if (!items.length) return;
            event.preventDefault();
            setActive((index) =>
              event.key === "ArrowDown"
                ? Math.min(index + 1, items.length - 1)
                : index < 0
                  ? items.length - 1
                  : Math.max(index - 1, 0),
            );
          } else if (event.key === "Enter" && items[active]) {
            event.preventDefault();
            choose(items[active]);
          } else if (event.key === "Tab") {
            setDismissed(true);
            setActive(-1);
          } else if (
            ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
          ) {
            setActive(-1);
          }
        }}
        placeholder="Search boxes, contents, or a code…"
        maxLength={200}
      />
      <button className="primary" type="submit">
        Search
        <Icon name="arrow" size={18} />
      </button>
      <span className="sr-only" id={popupId + "-help"}>
        Box suggestions start at BX- plus two code characters. Other text
        suggests items, tags and collections after two letters or numbers. Enter
        searches all fields unless you select a suggestion.
      </span>
      <span className="sr-only" role="status" aria-live="polite">
        {status}
      </span>
      {expanded && (
        <div className="search-suggestions">
          <div className="search-suggestions-heading">
            {intent === "box_code"
              ? "Matching box codes"
              : "Items · Tags · Collections"}
          </div>
          <ul
            id={popupId}
            role="listbox"
            aria-label="Search suggestions"
            aria-busy={current?.phase === "loading"}
          >
            {items.map((item, index) => (
              <li
                id={`${popupId}-${index}`}
                key={item.kind + ":" + item.id}
                role="option"
                aria-selected={active === index}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(item)}
                className="search-suggestion"
              >
                <span className="search-suggestion-kind">
                  {suggestionLabels[item.kind]}
                </span>
                <span className="search-suggestion-copy">
                  <strong>{item.label}</strong>
                  <small>{item.detail}</small>
                </span>
              </li>
            ))}
          </ul>
          {!items.length && (
            <p className="search-suggestions-message">{status}</p>
          )}
          {!!items.length && (
            <p className="search-suggestions-footer">
              Enter searches everything · ↑↓ to choose
            </p>
          )}
        </div>
      )}
    </form>
  );
}
export function Code({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const [manual, setManual] = useState(false);
  const codeElement = useRef<HTMLElement>(null);
  return (
    <div className="code-row">
      <code ref={codeElement} tabIndex={0}>
        {code}
      </code>
      <button
        className="ghost"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(code);
            setCopied(true);
            setManual(false);
            setTimeout(() => setCopied(false), 2000);
          } catch {
            setCopied(false);
            if (codeElement.current) {
              codeElement.current.focus();
              const range = document.createRange();
              range.selectNodeContents(codeElement.current);
              const selection = window.getSelection();
              selection?.removeAllRanges();
              selection?.addRange(range);
            }
            setManual(true);
          }
        }}
      >
        {copied ? "Copied" : "Copy code"}
      </button>
      {manual && (
        <span role="status">
          Code selected. Use your device’s Copy command.
        </span>
      )}
    </div>
  );
}
export function BoxCard({ box }: { box: Schema<"BoxSummary"> }) {
  return (
    <article className="box-card">
      <Link to={"/boxes/" + box.code} className="box-link">
        <div className="box-visual">
          {box.representative_thumbnail_url ? (
            <img
              src={box.representative_thumbnail_url}
              alt=""
              loading="lazy"
              decoding="async"
            />
          ) : (
            <>
              <Icon size={74} />
              <span className="visual-caption">NO PHOTOS YET</span>
            </>
          )}
          <span className="box-code">{box.code}</span>
        </div>
        <div className="card-body">
          <h2>{box.name}</h2>
          <div className="card-meta">
            <span>{box.item_count} items</span>
            <span>{box.image_count} photos</span>
            <Icon name="arrow" size={18} />
          </div>
          {box.lifecycle === "archived" && (
            <span className="badge caution">Archived</span>
          )}
          {box.pending_observation_count > 0 && (
            <span className="badge ai">
              {box.pending_observation_count} to review
            </span>
          )}
          <small>
            Updated{" "}
            <time
              dateTime={box.updated_at}
              title={new Date(box.updated_at).toLocaleString()}
            >
              {new Date(box.updated_at).toLocaleDateString()}
            </time>
          </small>
        </div>
      </Link>
      <OrganizationBadges tags={box.tags} collections={box.collections} />
      <PinLabel box={box} />
    </article>
  );
}
export function OrganizationBadges({
  tags = [],
  collections = [],
}: {
  tags?: { id: string; name: string }[];
  collections?: { id: string; name: string }[];
}) {
  if (!tags.length && !collections.length) return null;
  return (
    <div className="org-badges" aria-label="Tags and collections">
      {tags.map((tag) => (
        <Link
          className="org-badge"
          key={tag.id}
          to={"/boxes?tag_id=" + encodeURIComponent(tag.id)}
          aria-label={"Boxes tagged " + tag.name}
        >
          #{tag.name}
        </Link>
      ))}
      {collections.map((collection) => (
        <Link
          className="org-badge collection"
          key={collection.id}
          to={"/collections/" + collection.id}
          aria-label={"Collection " + collection.name}
        >
          {collection.name}
        </Link>
      ))}
    </div>
  );
}
export function Markdown({ html }: { html: string }) {
  return (
    <div
      className="markdown"
      dangerouslySetInnerHTML={{
        __html: DOMPurify.sanitize(html, {
          FORBID_TAGS: ["img", "style", "iframe", "object", "form"],
        }),
      }}
    />
  );
}
const parser = new MarkdownIt({ html: false, linkify: false, breaks: false });
export function MarkdownEditor({
  value,
  onChange,
  max = 65536,
  label = "Description",
}: {
  value: string;
  onChange: (value: string) => void;
  max?: number;
  label?: string;
}) {
  const [preview, setPreview] = useState(false);
  const id = useId();
  const ref = useRef<HTMLTextAreaElement>(null);
  function insert(before: string, after = "") {
    const area = ref.current;
    if (!area) return;
    const a = area.selectionStart,
      b = area.selectionEnd;
    onChange(
      value.slice(0, a) + before + value.slice(a, b) + after + value.slice(b),
    );
    setTimeout(() => {
      area.focus();
      area.setSelectionRange(a + before.length, b + before.length);
    }, 0);
  }
  return (
    <section className="editor">
      <div className="section-head">
        <label htmlFor={id}>{label}</label>
        <div className="tabs">
          <button
            type="button"
            aria-pressed={!preview}
            onClick={() => setPreview(false)}
          >
            Write
          </button>
          <button
            type="button"
            aria-pressed={preview}
            onClick={() => setPreview(true)}
          >
            Preview
          </button>
        </div>
      </div>
      {preview ? (
        <div className="editor-preview">
          <Markdown html={parser.render(value)} />
        </div>
      ) : (
        <>
          <div className="toolbar">
            <button type="button" onClick={() => insert("**", "**")}>
              Bold
            </button>
            <button type="button" onClick={() => insert("*", "*")}>
              Italic
            </button>
            <button type="button" onClick={() => insert("\n- ")}>
              List
            </button>
            <button type="button" onClick={() => insert("\n## ")}>
              Heading
            </button>
          </div>
          <textarea
            ref={ref}
            id={id}
            rows={8}
            value={value}
            maxLength={max}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Describe what is inside this box…"
          />
        </>
      )}
      <small>
        Markdown supported · Raw HTML and remote images are disabled.{" "}
        <span>
          {value.length.toLocaleString()} / {max.toLocaleString()}
        </span>
      </small>
    </section>
  );
}
export function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    ref.current?.showModal();
    return () => previous?.focus();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={id}
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
    >
      <div className="section-head">
        <h2 id={id}>{title}</h2>
        <button onClick={close} aria-label="Close dialog">
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Unsaved({ dirty }: { dirty: boolean }) {
  const blocker = useBlocker(dirty);
  useEffect(() => {
    function guard(e: BeforeUnloadEvent) {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    }
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  return blocker.state === "blocked" ? (
    <Modal title="Keep your changes?" close={() => blocker.reset()}>
      <p>You have unsaved changes. Stay to save them or leave this page.</p>
      <div className="actions">
        <button onClick={() => blocker.reset()}>Keep editing</button>
        <button className="danger" onClick={() => blocker.proceed()}>
          Leave without saving
        </button>
      </div>
    </Modal>
  ) : null;
}
export function Submit({
  busy,
  children,
}: {
  busy: boolean;
  children: ReactNode;
}) {
  return (
    <button className="primary" disabled={busy} type="submit">
      {busy ? "Saving…" : children}
    </button>
  );
}
export type SubmitEvent = FormEvent<HTMLFormElement>;
