import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  cache,
  changed,
  query,
  setSession,
  tag,
  type Session,
  type Schema,
} from "./api";
import { useSession } from "./session";
import {
  authOrder,
  authValues,
  authServerErrors,
  validateAuth,
  type AuthErrors,
  type AuthField,
} from "./auth-validation";
import {
  Empty,
  ErrorNote,
  Field,
  Icon,
  Loading,
  Modal,
  PageHead,
  Submit,
  type SubmitEvent,
} from "./components";
import "./auth-admin.css";

export function Login({ setup = false }: { setup?: boolean }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const [fields, setFields] = useState<AuthErrors>({});
  const [complete, setComplete] = useState(false);
  const running = useRef(false);
  const status = useQuery(query<Schema<"SetupStatusView">>("/setup/status"));
  const providers = useQuery({
    ...query<{ items: { id: string; label: string }[] }>("/auth/providers"),
    enabled: !setup,
  });
  const oauthError = params.has("oauth_error")
    ? new Error(
        "Provider sign-in could not be completed. Try again, or use your local username and password. If it continues, ask an owner to check your provider link.",
      )
    : null;
  async function signInWithProvider(id: string) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ authorization_url: string }>(
        `/auth/oidc/${encodeURIComponent(id)}/start`,
        { method: "POST", body: {} },
      );
      const target = new URL(result.authorization_url);
      if (!["https:", "http:"].includes(target.protocol))
        throw new Error("The sign-in provider returned an invalid address.");
      window.location.assign(target.href);
    } catch (e) {
      setError(e);
      running.current = false;
      setBusy(false);
    }
  }
  if (!complete && status.data?.setup_required && !setup)
    return <Navigate to="/setup" replace />;
  if (!complete && status.data && !status.data.setup_required && setup)
    return <Navigate to="/login" replace />;
  function showFields(form: HTMLFormElement, errors: AuthErrors) {
    setFields(errors);
    const first = authOrder.find((name) => errors[name]);
    if (first)
      requestAnimationFrame(() => {
        const input = form.elements.namedItem(first);
        if (input instanceof HTMLElement && input.isConnected) input.focus();
      });
  }
  function clearField(name: AuthField) {
    setFields((current) => ({ ...current, [name]: undefined }));
    setError(null);
  }
  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (running.current || complete || !status.data) return;
    const form = event.currentTarget;
    // Read what is actually visible, including password-manager/autofill values.
    // Password bytes are never trimmed or normalized.
    const values = authValues(new FormData(form));
    const invalid = validateAuth(values, setup);
    showFields(form, invalid);
    if (Object.keys(invalid).length) {
      setError(new Error("Correct the marked fields, then try again."));
      return;
    }
    running.current = true;
    setBusy(true);
    setError(null);
    try {
      const session = await api<Session>(
        setup ? "/setup/owner" : "/auth/login",
        {
          method: "POST",
          headers: setup ? { "X-Boxen-Setup-Token": values.token } : undefined,
          body: setup
            ? {
                username: values.username,
                display_name: values.display_name,
                password: values.password,
              }
            : { username: values.username, password: values.password },
        },
      );
      setSession(session);
      setComplete(true);
      if (setup)
        cache.setQueryData(["/setup/status"], { setup_required: false });
      void changed();
      const next = params.get("next");
      navigate(
        next?.startsWith("/") &&
          !next.startsWith("//") &&
          !/[\\\u0000-\u001f]/.test(next)
          ? next
          : "/",
        {
          replace: true,
        },
      );
    } catch (e) {
      setError(e);
      showFields(form, authServerErrors(e, setup));
    } finally {
      running.current = false;
      setBusy(false);
    }
  }
  return (
    <main className="auth">
      <Link className="brand" to="/">
        <Icon size={38} />
        <span>
          BOXEN<small>LOCAL INVENTORY NODE</small>
        </span>
      </Link>
      <section className="panel">
        <div className="eyebrow">PRIVATE BY DESIGN</div>
        <h1>{setup ? "Set up your local inventory" : "Welcome back."}</h1>
        <p className="muted">
          {setup
            ? "Create the core administrator for this Boxen installation. This protected local sign-in keeps system management available."
            : "Sign in for the permissions assigned to your local account."}
        </p>
        {!setup && <ErrorNote error={oauthError} />}
        {status.isPending ? (
          <Loading label="Checking local account setup…" />
        ) : status.error ? (
          <>
            <ErrorNote error={status.error} />
            <button onClick={() => status.refetch()}>Retry setup status</button>
          </>
        ) : (
          <form onSubmit={submit} noValidate>
            <fieldset disabled={busy || complete} className="auth-fields">
              {setup && (
                <Field
                  label="One-time setup token"
                  help="Shown by the boxen init command on your host."
                  error={fields.token}
                >
                  <input
                    name="token"
                    onInput={() => clearField("token")}
                    required
                    type="password"
                    autoComplete="off"
                    autoCapitalize="none"
                    spellCheck={false}
                  />
                </Field>
              )}
              <Field
                label="Username"
                error={fields.username}
                help={
                  setup
                    ? "3–64 letters, numbers, underscores, dots, or hyphens. This is a local username, not an email address."
                    : undefined
                }
              >
                <input
                  name="username"
                  defaultValue={setup ? "admin" : ""}
                  onInput={() => clearField("username")}
                  required
                  minLength={3}
                  autoComplete="username"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  autoFocus
                />
              </Field>
              {setup && (
                <Field label="Display name" error={fields.display_name}>
                  <input
                    name="display_name"
                    onInput={() => clearField("display_name")}
                    required
                    autoComplete="name"
                  />
                </Field>
              )}
              <Field
                label="Password"
                error={fields.password}
                help={
                  setup
                    ? "Choose a unique password of at least 12 characters (up to 1024 UTF-8 bytes). There is no factory password. Password managers and paste are supported."
                    : undefined
                }
              >
                <input
                  name="password"
                  onInput={() => clearField("password")}
                  required
                  type="password"
                  minLength={setup ? 12 : 1}
                  autoComplete={setup ? "new-password" : "current-password"}
                />
              </Field>
            </fieldset>
            <ErrorNote error={error} />
            <Submit busy={busy}>
              {setup ? "Create owner account" : "Sign in"}
              <Icon name="arrow" />
            </Submit>
          </form>
        )}
        {!setup && status.data && !status.data.setup_required && (
          <section className="provider-sign-in" aria-label="Provider sign-in">
            {providers.isPending ? (
              <Loading label="Checking sign-in providers…" />
            ) : providers.error ? (
              <>
                <p className="muted">
                  Provider sign-in is unavailable. You can still use your local
                  account.
                </p>
                <button onClick={() => providers.refetch()}>
                  Retry sign-in providers
                </button>
              </>
            ) : (
              providers.data?.items.map((provider) => (
                <button
                  key={provider.id}
                  disabled={busy || complete}
                  onClick={() => signInWithProvider(provider.id)}
                >
                  Continue with {provider.label}
                </button>
              ))
            )}
          </section>
        )}
        {setup && (
          <details>
            <summary>Where do I find the setup token?</summary>
            <p>
              This is the one-time token generated on the computer hosting
              Boxen, not the password you are creating. If you missed the
              original init output, it is stored in{" "}
              <code>secrets/setup-token</code> inside your configured Boxen data
              directory until setup succeeds. Read it privately on that
              computer; do not share it in chat.
            </p>
          </details>
        )}
        {setup && (
          <details>
            <summary>Local AI and phone access</summary>
            <p>
              AI is optional: install a model profile later on your host. For
              phones, run the HTTPS deployment and trust its local certificate.
              The deployment guide includes these steps.
            </p>
          </details>
        )}
      </section>
      <p className="auth-foot">
        <Icon name="shield" size={16} />
        Local inventory. Sign-in options controlled by your host.
      </p>
      <Link to="/help">Setup and sign-in help</Link>
      <Link to="/">Return to inventory</Link>
    </main>
  );
}
export function Account() {
  const session = useSession();
  const navigate = useNavigate();
  const [name, setName] = useState(session.user.display_name),
    [current, setCurrent] = useState(""),
    [password, setPassword] = useState(""),
    [message, setMessage] = useState(""),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  async function save(e: SubmitEvent, changePassword = false) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (changePassword) {
        const s = await api<Session>("/session/password", {
          method: "POST",
          body: { current_password: current, new_password: password },
        });
        setSession(s);
        setCurrent("");
        setPassword("");
        setMessage("Password changed. Other sessions have been revoked.");
      } else {
        const user = await api<Schema<"UserView">>("/session/profile", {
          method: "PATCH",
          etag: tag("user", session.user.id, session.user.version),
          body: { display_name: name },
        });
        setSession({ ...session, user });
        setMessage("Your display name was updated.");
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (session.anonymous)
    return (
      <>
        <PageHead title="Local access" />
        <section className="panel">
          <h2>No account required</h2>
          <p>
            This host allows anonymous{" "}
            {session.user.role === "viewer"
              ? "viewing and searching"
              : "viewing and editing"}
            . Your browser receives a local security cookie, but no personal
            account is needed.
          </p>
          <p>
            System administration stays protected. The host owner controls
            anonymous permissions.
          </p>
          <Link className="button primary" to="/login">
            Sign in to a local account
          </Link>
        </section>
      </>
    );
  return (
    <>
      <PageHead title="Your account">
        <button
          onClick={() =>
            window.dispatchEvent(new Event("boxen-session-expired"))
          }
        >
          Sign in again
        </button>
        <button
          onClick={async () => {
            try {
              await api("/auth/logout", { method: "POST" });
            } finally {
              cache.clear();
              setSession(null);
              cache.removeQueries({ queryKey: ["session"] });
              navigate("/");
            }
          }}
        >
          Sign out
        </button>
      </PageHead>
      <div className="admin-grid">
        <form className="panel" onSubmit={(e) => save(e)}>
          <h2>Profile</h2>
          <p>
            {session.user.username} · {session.user.role}
          </p>
          <Field label="Display name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={120}
            />
          </Field>
          <Submit busy={busy}>Save profile</Submit>
          <p className="muted">
            Session expires {new Date(session.expires_at).toLocaleString()}.
          </p>
        </form>
        <form className="panel" onSubmit={(e) => save(e, true)}>
          <h2>Change password</h2>
          <Field label="Current password">
            <input
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              type="password"
              autoComplete="current-password"
              required
            />
          </Field>
          <Field label="New password">
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              autoComplete="new-password"
              minLength={12}
              required
            />
          </Field>
          <Submit busy={busy}>Change password</Submit>
        </form>
      </div>
      <ErrorNote error={error} />
      {message && (
        <div className="notice success" role="status">
          {message}
        </div>
      )}
    </>
  );
}
export function System() {
  const session = useSession();
  const status = useQuery({
    ...query<Schema<"SystemStatusView">>("/system"),
    refetchInterval: 15_000,
  });
  return (
    <>
      <PageHead
        title="Your local system"
        eyebrow={
          status.data?.runtime_offline === false
            ? "REMOTE AI CONFIGURED"
            : "YOUR INVENTORY NODE"
        }
      />
      <ErrorNote error={status.error} />
      {status.isPending ? (
        <Loading />
      ) : (
        <>
          <div className="admin-grid">
            {Object.entries(status.data?.components ?? {}).map(
              ([key, value]) => (
                <section className="panel" key={key}>
                  <div className="section-head">
                    <h2 className="capitalize">{key}</h2>
                    <span
                      className={
                        "badge " +
                        (value.status === "ready" ? "success" : "caution")
                      }
                    >
                      {value.status}
                    </span>
                  </div>
                  <p className="muted">
                    {value.message ??
                      (value.status === "ready"
                        ? "Operating normally."
                        : "Owner attention may be needed.")}
                  </p>
                </section>
              ),
            )}
          </div>
          <p className="muted">
            Boxen {status.data?.application_version} · Database schema{" "}
            {status.data?.schema_version} ·{" "}
            {status.data?.runtime_offline === false
              ? "Inventory is stored here. Requested photo analyses use the configured remote AI server."
              : "All runtime resources are local."}
          </p>
        </>
      )}
      {session.user.role === "owner" && (
        <>
          <div className="actions">
            <Link className="button" to="/system/users">
              Manage users
            </Link>
            <Link className="button" to="/system/authentication">
              Authentication & sign-ins
            </Link>
            <Link className="button" to="/system/backups">
              Backups
            </Link>
            <Link className="button" to="/system/maintenance">
              Integrity & maintenance
            </Link>
            <Link className="button" to="/help">
              System help
            </Link>
          </div>
          <section className="panel">
            <h2>Phones and local HTTPS</h2>
            <p>
              Connect phones to the same local network and open your configured
              Boxen HTTPS address. Review its local certificate warning or
              install the verified local CA for warning-free access. Camera
              permission is controlled separately by your browser and device.
            </p>
            <p className="muted">
              {status.data?.runtime_offline === false
                ? "Remote AI is explicitly enabled by this installation's administrator. Photos selected for analysis are sent to that server; its model identity is operator-reported."
                : "Local AI requires a provisioned, checksum-verified model and projector plus the local inference service. See the installation guide on your host."}
            </p>
          </section>
        </>
      )}
    </>
  );
}
export function Users() {
  const session = useSession();
  const users = useQuery({
    ...query<{ items: Schema<"UserView">[] }>("/users"),
    enabled: session.user.role === "owner",
  });
  const [editing, setEditing] = useState<Schema<"UserView"> | "new" | null>(
    null,
  );
  if (session.user.role !== "owner")
    return <Empty title="Owner access required" />;
  return (
    <>
      <PageHead title="Local users">
        <Link className="button" to="/system/authentication">
          Authentication & sign-ins
        </Link>
        <button className="primary" onClick={() => setEditing("new")}>
          Add user
        </button>
      </PageHead>
      <p className="muted">
        Viewers read. Editors manage contents. Owners also manage users,
        backups, and deletion. Sensitive changes require a sign-in within the
        last 15 minutes.
      </p>
      <ErrorNote error={users.error} />
      {users.error && (
        <button onClick={() => users.refetch()}>Retry users</button>
      )}
      {users.isPending ? (
        <Loading />
      ) : users.data?.items.length === 0 ? (
        <Empty title="No local users" />
      ) : (
        <div className="panel">
          {users.data?.items.map((user) => (
            <article key={user.id} className="inventory-row">
              <div className="item-content">
                <h2>{user.display_name}</h2>
                {user.is_system_admin && (
                  <span className="badge">Core administrator</span>
                )}
                <p>
                  {user.username} · {user.role} · {user.status}
                </p>
                <small>
                  {user.local_password
                    ? "Local password available"
                    : "Provider sign-in only"}
                </small>
              </div>
              <button
                aria-label={`Edit user ${user.username}`}
                onClick={() => setEditing(user)}
              >
                Edit user
              </button>
            </article>
          ))}
        </div>
      )}
      {editing && (
        <Modal
          title={editing === "new" ? "Add local user" : "Edit local user"}
          close={() => setEditing(null)}
        >
          <UserForm
            existing={editing === "new" ? undefined : editing}
            close={() => setEditing(null)}
          />
        </Modal>
      )}
    </>
  );
}
function UserForm({
  existing,
  close,
}: {
  existing?: Schema<"UserView">;
  close: () => void;
}) {
  const [name, setName] = useState(existing?.display_name ?? ""),
    [username, setUsername] = useState(existing?.username ?? ""),
    [role, setRole] = useState(existing?.role ?? "viewer"),
    [status, setStatus] = useState(existing?.status ?? "active"),
    [password, setPassword] = useState(""),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          const body = existing
            ? {
                display_name: name,
                ...(!existing.is_system_admin && role !== existing.role
                  ? { role }
                  : {}),
                ...(!existing.is_system_admin && status !== existing.status
                  ? { status }
                  : {}),
                ...(password ? { password } : {}),
              }
            : { display_name: name, username, role, password };
          await api(existing ? "/users/" + existing.id : "/users", {
            method: existing ? "PATCH" : "POST",
            etag: existing
              ? tag("user", existing.id, existing.version)
              : undefined,
            body,
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
      <Field label="Username">
        <input
          value={username}
          disabled={!!existing}
          onChange={(e) => setUsername(e.target.value)}
          required
          minLength={3}
          maxLength={64}
          pattern={"[A-Za-z0-9_.\\-]+"}
          autoComplete="off"
        />
      </Field>
      <Field label="Display name">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={120}
        />
      </Field>
      <Field label="Role">
        <select
          value={role}
          disabled={existing?.is_system_admin}
          onChange={(e) => setRole(e.target.value as typeof role)}
        >
          <option>viewer</option>
          <option>editor</option>
          <option>owner</option>
        </select>
      </Field>
      {existing && (
        <Field label="Status">
          <select
            value={status}
            disabled={existing?.is_system_admin}
            onChange={(e) => setStatus(e.target.value as typeof status)}
          >
            <option>active</option>
            <option>disabled</option>
          </select>
        </Field>
      )}
      <Field label={existing ? "Reset password (optional)" : "Password"}>
        <input
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required={!existing}
          minLength={12}
        />
      </Field>
      <p className="muted">
        Role, status, or password changes revoke this user’s sessions.{" "}
        {existing?.is_system_admin
          ? "The core administrator must remain active, keep its owner role, and use a local password."
          : "The last active owner cannot be disabled or demoted."}
      </p>
      <ErrorNote error={error} />
      <Submit busy={busy}>Save user</Submit>
    </form>
  );
}
export function Backups() {
  const session = useSession();
  const backups = useQuery({
    ...query<{ items: Schema<"BackupView">[] }>("/backups"),
    enabled: session.user.role === "owner",
    refetchInterval: 3000,
  });
  const [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  if (session.user.role !== "owner")
    return <Empty title="Owner access required" />;
  async function run(id?: string) {
    setBusy(true);
    try {
      await api("/backups" + (id ? "/" + id + "/verify" : ""), {
        method: "POST",
      });
      await changed();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHead title="Local backups">
        <button className="primary" disabled={busy} onClick={() => run()}>
          Create backup
        </button>
      </PageHead>
      <p className="intro">
        Backups include a consistent SQLite snapshot and every referenced
        original photo, with checksums. The worker verifies each backup before
        it becomes usable.
      </p>
      <ErrorNote error={error ?? backups.error} />
      {backups.isPending ? (
        <Loading />
      ) : backups.data?.items.length ? (
        <div className="panel">
          {backups.data.items.map((b) => (
            <article key={b.id} className="inventory-row">
              <div className="item-content">
                <h2>{new Date(b.created_at).toLocaleString()}</h2>
                <span
                  className={
                    "badge " + (b.status === "verified" ? "success" : "caution")
                  }
                >
                  {b.status}
                </span>
                <p>
                  {b.file_count ?? "—"} files ·{" "}
                  {b.total_bytes
                    ? Math.round(b.total_bytes / 1024 / 1024) + " MB"
                    : "Awaiting worker"}
                </p>
                {b.error && <ErrorNote error={new Error(b.error.summary)} />}
              </div>
              <button
                disabled={busy || ["creating", "verifying"].includes(b.status)}
                onClick={() => run(b.id)}
              >
                Verify backup
              </button>
            </article>
          ))}
        </div>
      ) : (
        <Empty title="No backups yet">
          <p>Create one before making destructive changes.</p>
        </Empty>
      )}
      <section className="panel">
        <h2>Restore safely</h2>
        <p>
          Restore is an offline owner operation, not a web action. Stop the web
          and worker processes, run the documented preflight, then apply the
          selected backup. The previous data directory is quarantined for
          recovery. Sessions are revoked after restore.
        </p>
        <p className="muted">
          Keep a verified copy on a separate local disk. A backup on the same
          disk cannot protect against disk failure.
        </p>
      </section>
    </>
  );
}
export function Maintenance() {
  const session = useSession();
  const [jobId, setJobId] = useState(""),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const job = useQuery({
    ...query<Schema<"MaintenanceJobView">>("/maintenance/" + jobId),
    enabled: !!jobId,
    refetchInterval: (q) =>
      ["queued", "running"].includes(q.state.data?.state ?? "queued")
        ? 2000
        : false,
  });
  useEffect(() => {
    if (job.data?.state === "succeeded") void changed();
  }, [job.data?.state]);
  if (session.user.role !== "owner")
    return <Empty title="Owner access required" />;
  return (
    <>
      <PageHead title="Integrity & maintenance" />
      <div className="panel">
        <p>
          Verify authoritative data and its derived search index. Rebuilding
          search does not change your boxes or inventory.
        </p>
        <div className="actions">
          {[
            ["search/verify", "Verify search"],
            ["search/rebuild", "Rebuild search"],
            ["media/verify", "Verify photo integrity"],
          ].map(([path, label]) => (
            <button
              key={path}
              disabled={
                busy || ["queued", "running"].includes(job.data?.state ?? "")
              }
              onClick={async () => {
                setBusy(true);
                try {
                  const j = await api<Schema<"MaintenanceJobView">>(
                    "/maintenance/" + path,
                    { method: "POST" },
                  );
                  setJobId(j.id);
                } catch (e) {
                  setError(e);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <ErrorNote error={error ?? job.error} />
        {job.data && (
          <div className="notice" role="status">
            <h2>
              {job.data.kind.replaceAll("_", " ")} · {job.data.state}
            </h2>
            {job.data.error && (
              <ErrorNote error={new Error(job.data.error.summary)} />
            )}
            <pre>
              {job.data.result
                ? JSON.stringify(job.data.result, null, 2)
                : "Waiting for the local worker…"}
            </pre>
          </div>
        )}
      </div>
    </>
  );
}
