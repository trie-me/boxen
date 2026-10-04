import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api, cache, changed, query, setSession, type Schema } from "./api";
import {
  Empty,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHead,
  Submit,
} from "./components";
import { useSession } from "./session";
import "./auth-admin.css";

type Provider = {
  id: string;
  label: string;
  issuer: string;
  client_id: string;
  configured: boolean;
  redirect_uri: string;
};
type SignInSession = {
  id: string;
  user_id: string;
  username: string;
  method: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  revoked_at: string | null;
  active: boolean;
  current: boolean;
};
type SignInEvent = {
  id: number;
  occurred_at: string;
  user_id: string | null;
  username: string | null;
  action: string;
  method: string | null;
};
type Identity = {
  id: string;
  user_id: string;
  provider_id: string;
  issuer: string;
  subject: string;
  created_at: string;
};
type Confirmation = {
  title: string;
  detail: string;
  action: string;
  path: string;
  method: "DELETE" | "POST";
  signsOut?: boolean;
};

function date(value: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

export function AuthenticationAdmin() {
  const session = useSession();
  const navigate = useNavigate();
  const owner = session.user.role === "owner";
  const [userId, setUserId] = useState("");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [message, setMessage] = useState("");
  const [linking, setLinking] = useState(false);
  const users = useQuery({
    ...query<{ items: Schema<"UserView">[] }>("/users"),
    enabled: owner,
  });
  const suffix = userId ? `?user_id=${encodeURIComponent(userId)}` : "";
  const sessions = useQuery({
    ...query<{ items: SignInSession[] }>("/auth/sessions" + suffix),
    enabled: owner,
  });
  const events = useQuery({
    ...query<{ items: SignInEvent[] }>("/auth/events?limit=100"),
    enabled: owner,
  });
  const providers = useQuery({
    ...query<{ items: Provider[] }>("/auth/provider-status"),
    enabled: owner,
  });
  const identities = useQuery({
    ...query<{ items: Identity[] }>("/auth/identities" + suffix),
    enabled: owner,
  });
  const selectedUser = users.data?.items.find((user) => user.id === userId);
  const username = (id: string) =>
    users.data?.items.find((user) => user.id === id)?.username ?? id;
  const providerName = (id: string) =>
    providers.data?.items.find((provider) => provider.id === id)?.label ?? id;
  function confirm(value: Confirmation) {
    setError(null);
    setMessage("");
    setConfirmation(value);
  }
  async function perform() {
    if (!confirmation || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api(confirmation.path, { method: confirmation.method });
      if (confirmation.signsOut) {
        cache.clear();
        setSession(null);
        navigate("/login", { replace: true });
        return;
      }
      setMessage(
        confirmation.action === "Unlink identity"
          ? "Provider identity unlinked."
          : "Selected sessions revoked.",
      );
      setConfirmation(null);
      await changed();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (!owner) return <Empty title="Owner access required" />;
  return (
    <div className="auth-admin">
      <PageHead
        title="Authentication & sign-ins"
        eyebrow="SYSTEM ADMINISTRATION"
      >
        <Link className="button" to="/system/users">
          Manage users
        </Link>
        <Link className="button" to="/help">
          System help
        </Link>
      </PageHead>
      <p className="intro">
        Manage local accounts, provider links, and browser sessions. Sensitive
        changes require a sign-in within the last 15 minutes.
      </p>
      <nav
        className="actions auth-section-links"
        aria-label="Authentication sections"
      >
        <a className="button" href="#auth-sessions">
          Sessions
        </a>
        <a className="button" href="#auth-providers">
          Providers
        </a>
        <a className="button" href="#auth-identities">
          Provider links
        </a>
        <a className="button" href="#auth-events">
          Sign-in history
        </a>
      </nav>
      {message && (
        <p className="notice success" role="status">
          {message}
        </p>
      )}
      <section className="panel auth-filter" aria-label="User filter">
        <Field label="Filter sessions and provider links by user">
          <select
            value={userId}
            onChange={(event) => setUserId(event.target.value)}
            disabled={users.isPending || !!users.error}
          >
            <option value="">All users</option>
            {users.data?.items.map((user) => (
              <option key={user.id} value={user.id}>
                {user.username}
                {user.is_system_admin ? " · Core administrator" : ""}
              </option>
            ))}
          </select>
        </Field>
        {users.isPending && <Loading label="Loading users…" />}
        <ErrorNote error={users.error} />
        {users.error && (
          <button onClick={() => users.refetch()}>Retry users</button>
        )}
        {selectedUser && (
          <div className="actions">
            <span>
              {selectedUser.display_name} · {selectedUser.role} ·{" "}
              {selectedUser.status}
            </span>
            <button
              onClick={() =>
                confirm({
                  title: `Revoke sessions for ${selectedUser.username}?`,
                  detail:
                    "Every browser signed in as this user will need to sign in again. Their account and inventory are kept.",
                  action: "Revoke all sessions",
                  method: "POST",
                  path: `/users/${selectedUser.id}/revoke-sessions`,
                  signsOut: selectedUser.id === session.user.id,
                })
              }
            >
              Revoke all sessions
            </button>
          </div>
        )}
      </section>
      <section
        className="panel"
        id="auth-sessions"
        aria-labelledby="sessions-heading"
      >
        <div className="section-head">
          <h2 id="sessions-heading">Browser sessions</h2>
          <button
            disabled={sessions.isFetching}
            onClick={() => sessions.refetch()}
          >
            Refresh sessions
          </button>
        </div>
        <p className="muted">
          Review the latest 500 active, expired, and revoked sign-ins for this
          selection. Revocation takes effect on the browser’s next request.
        </p>
        <ErrorNote error={sessions.error} />
        {sessions.error && (
          <button onClick={() => sessions.refetch()}>Retry sessions</button>
        )}
        {sessions.isPending ? (
          <Loading label="Loading sessions…" />
        ) : sessions.data?.items.length === 0 ? (
          <p>No sessions for this selection.</p>
        ) : (
          <div className="auth-records">
            {sessions.data?.items.map((item) => (
              <article className="auth-record" key={item.id}>
                <div className="auth-record-body">
                  <h3>
                    {item.username}{" "}
                    {item.current && (
                      <span className="badge">This browser</span>
                    )}
                  </h3>
                  <p>
                    <span className={"badge " + (item.active ? "success" : "")}>
                      {item.active
                        ? "Active"
                        : item.revoked_at
                          ? "Revoked"
                          : "Expired"}
                    </span>{" "}
                    <span>{item.method}</span>
                  </p>
                  <dl className="auth-dates">
                    <div>
                      <dt>Signed in</dt>
                      <dd>{date(item.created_at)}</dd>
                    </div>
                    <div>
                      <dt>Last seen</dt>
                      <dd>{date(item.last_seen_at)}</dd>
                    </div>
                    <div>
                      <dt>Expires</dt>
                      <dd>{date(item.expires_at)}</dd>
                    </div>
                    {item.revoked_at && (
                      <div>
                        <dt>Revoked</dt>
                        <dd>{date(item.revoked_at)}</dd>
                      </div>
                    )}
                  </dl>
                </div>
                {item.active && (
                  <button
                    aria-label={`Revoke session for ${item.username}${item.current ? " in this browser" : ""}`}
                    onClick={() =>
                      confirm({
                        title: "Revoke this session?",
                        detail: item.current
                          ? "This is your current browser. You will be signed out immediately."
                          : `${item.username} will need to sign in again in this browser.`,
                        action: "Revoke session",
                        method: "DELETE",
                        path: `/auth/sessions/${item.id}`,
                        signsOut: item.current,
                      })
                    }
                  >
                    Revoke session
                  </button>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
      <section
        className="panel"
        id="auth-providers"
        aria-labelledby="providers-heading"
      >
        <h2 id="providers-heading">Sign-in providers</h2>
        <p className="muted">
          OAuth sign-in uses OpenID Connect. Provider credentials are configured
          on the host; secrets are never shown here.{" "}
          <Link to="/help">View setup and configuration help.</Link>
        </p>
        <ErrorNote error={providers.error} />
        {providers.error && (
          <button onClick={() => providers.refetch()}>Retry providers</button>
        )}
        {providers.isPending ? (
          <Loading label="Loading provider configuration…" />
        ) : providers.data?.items.length === 0 ? (
          <p>
            No providers configured. Local username and password sign-in remains
            available.
          </p>
        ) : (
          <div className="auth-records">
            {providers.data?.items.map((provider) => (
              <article className="auth-record" key={provider.id}>
                <div className="auth-record-body">
                  <h3>{provider.label}</h3>
                  <span
                    className={
                      "badge " + (provider.configured ? "success" : "caution")
                    }
                  >
                    {provider.configured ? "Configured" : "Disabled"}
                  </span>
                  <dl className="auth-provider-details">
                    <div>
                      <dt>Provider ID</dt>
                      <dd>
                        <code>{provider.id}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>Issuer</dt>
                      <dd>{provider.issuer}</dd>
                    </div>
                    <div>
                      <dt>Client ID</dt>
                      <dd>{provider.client_id}</dd>
                    </div>
                    <div>
                      <dt>Redirect URI</dt>
                      <dd>{provider.redirect_uri}</dd>
                    </div>
                  </dl>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      <section
        className="panel"
        id="auth-identities"
        aria-labelledby="identities-heading"
      >
        <div className="section-head">
          <h2 id="identities-heading">Provider identity links</h2>
          <button
            onClick={() => setLinking(true)}
            disabled={
              !users.data ||
              !providers.data?.items.some((provider) => provider.configured)
            }
          >
            Link identity
          </button>
        </div>
        <p className="muted">
          Link a verified provider subject to an existing local user. Email
          addresses never grant access automatically. The core administrator
          always signs in with a local password.
        </p>
        <ErrorNote error={identities.error} />
        {identities.error && (
          <button onClick={() => identities.refetch()}>
            Retry provider links
          </button>
        )}
        {identities.isPending ? (
          <Loading label="Loading provider links…" />
        ) : identities.data?.items.length === 0 ? (
          <p>No linked identities for this selection.</p>
        ) : (
          <div className="auth-records">
            {identities.data?.items.map((identity) => (
              <article className="auth-record" key={identity.id}>
                <div className="auth-record-body">
                  <h3>
                    {username(identity.user_id)} ·{" "}
                    {providerName(identity.provider_id)}
                  </h3>
                  <dl className="auth-provider-details">
                    <div>
                      <dt>Subject</dt>
                      <dd>
                        <code>{identity.subject}</code>
                      </dd>
                    </div>
                    <div>
                      <dt>Issuer</dt>
                      <dd>{identity.issuer}</dd>
                    </div>
                    <div>
                      <dt>Linked</dt>
                      <dd>{date(identity.created_at)}</dd>
                    </div>
                  </dl>
                </div>
                <button
                  aria-label={`Unlink identity for ${username(identity.user_id)} with ${providerName(identity.provider_id)}`}
                  onClick={() =>
                    confirm({
                      title: "Unlink this provider identity?",
                      detail: `${username(identity.user_id)} will no longer be able to sign in through this provider identity. Existing local password access is preserved.`,
                      action: "Unlink identity",
                      method: "DELETE",
                      path: `/auth/identities/${identity.id}`,
                    })
                  }
                >
                  Unlink identity
                </button>
              </article>
            ))}
          </div>
        )}
      </section>
      <section
        className="panel"
        id="auth-events"
        aria-labelledby="events-heading"
      >
        <div className="section-head">
          <h2 id="events-heading">Recent sign-in history</h2>
          <button disabled={events.isFetching} onClick={() => events.refetch()}>
            Refresh history
          </button>
        </div>
        <p className="muted">
          The latest 100 authentication events across all users. Unrecognized
          sign-ins may have no linked local username.
        </p>
        <ErrorNote error={events.error} />
        {events.error && (
          <button onClick={() => events.refetch()}>
            Retry sign-in history
          </button>
        )}
        {events.isPending ? (
          <Loading label="Loading sign-in history…" />
        ) : events.data?.items.length === 0 ? (
          <p>No sign-in events recorded yet.</p>
        ) : (
          <ol className="auth-event-list">
            {events.data?.items.map((event) => (
              <li key={event.id}>
                <div>
                  <strong>{event.action.replace(/[_.]/g, " ")}</strong>
                  <span>
                    {event.username ?? "Unrecognized user"}
                    {event.method ? ` · ${event.method}` : ""}
                  </span>
                </div>
                <time dateTime={event.occurred_at}>
                  {date(event.occurred_at)}
                </time>
              </li>
            ))}
          </ol>
        )}
      </section>
      {confirmation && (
        <Modal
          title={confirmation.title}
          close={() => {
            if (!busy) setConfirmation(null);
          }}
        >
          <p>{confirmation.detail}</p>
          <ErrorNote error={error} />
          <div className="actions">
            <button disabled={busy} onClick={() => setConfirmation(null)}>
              Cancel
            </button>
            <button className="danger" disabled={busy} onClick={perform}>
              {busy ? "Working…" : confirmation.action}
            </button>
          </div>
        </Modal>
      )}
      {linking && (
        <Modal title="Link provider identity" close={() => setLinking(false)}>
          <IdentityForm
            users={users.data?.items ?? []}
            providers={providers.data?.items ?? []}
            selectedUserId={userId}
            close={() => {
              setLinking(false);
              setMessage("Provider identity linked.");
            }}
          />
        </Modal>
      )}
    </div>
  );
}

function IdentityForm({
  users,
  providers,
  selectedUserId,
  close,
}: {
  users: Schema<"UserView">[];
  providers: Provider[];
  selectedUserId: string;
  close: () => void;
}) {
  const eligibleUsers = users.filter(
    (user) => !user.is_system_admin && user.status === "active",
  );
  const eligibleProviders = providers.filter((provider) => provider.configured);
  const [userId, setUserId] = useState(
    eligibleUsers.find((user) => user.id === selectedUserId)?.id ??
      eligibleUsers[0]?.id ??
      "",
  );
  const [providerId, setProviderId] = useState(eligibleProviders[0]?.id ?? "");
  const [subject, setSubject] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  if (!eligibleUsers.length)
    return (
      <p>
        Create an active user in <Link to="/system/users">Manage users</Link>{" "}
        before linking an identity. The core administrator cannot use provider
        sign-in.
      </p>
    );
  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (busy) return;
        setBusy(true);
        setError(null);
        try {
          await api("/auth/identities", {
            method: "POST",
            body: { user_id: userId, provider_id: providerId, subject },
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
      <Field label="Local user">
        <select
          value={userId}
          onChange={(event) => setUserId(event.target.value)}
          disabled={busy}
        >
          {eligibleUsers.map((user) => (
            <option key={user.id} value={user.id}>
              {user.username} · {user.role}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Provider">
        <select
          value={providerId}
          onChange={(event) => setProviderId(event.target.value)}
          disabled={busy}
        >
          {eligibleProviders.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.label}
            </option>
          ))}
        </select>
      </Field>
      <Field
        label="Provider subject"
        help="Copy the exact, case-sensitive sub claim verified with your provider administrator. A matching email address is insufficient."
      >
        <input
          value={subject}
          onChange={(event) => setSubject(event.target.value)}
          required
          maxLength={255}
          autoCapitalize="none"
          autoCorrect="off"
          autoComplete="off"
          spellCheck={false}
          disabled={busy}
        />
      </Field>
      <p className="muted">
        This identity receives the local user’s assigned permissions. Verify the
        subject before granting access.
      </p>
      <ErrorNote error={error} />
      <Submit busy={busy}>Link identity</Submit>
    </form>
  );
}
