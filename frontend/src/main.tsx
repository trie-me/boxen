import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import {
  createBrowserRouter,
  RouterProvider,
  NavLink,
  Link,
  Outlet,
  Navigate,
  useLocation,
  useNavigate,
  useRouteError,
} from "react-router-dom";
import { api, cache, setSession, type Session, type Schema } from "./api";
import { SessionContext, useSession } from "./session";
import {
  authValues,
  authServerErrors,
  validateAuth,
  type AuthErrors,
} from "./auth-validation";
import {
  ErrorNote,
  Field,
  Icon,
  Loading,
  Modal,
  SearchBar,
} from "./components";
import { Login, Account, System, Users, Backups, Maintenance } from "./system";
import { Home, Boxes, BoxEditor, BoxDetail, Search, Labels } from "./catalog";
import { Collections, CollectionDetailPage } from "./organization";
import { Review } from "./review";
import { Scan } from "./scan";
import "./tokens.css";
import "./style.css";

function Shell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [expired, setExpired] = useState(false);
  const session = useQuery({
    queryKey: ["session"],
    queryFn: async () => {
      try {
        const result = await api<Session>("/session");
        setSession(result);
        return result;
      } catch (e) {
        if (e instanceof Error && "status" in e && e.status === 401)
          return null;
        throw e;
      }
    },
    retry: false,
    refetchOnWindowFocus: false,
  });
  const status = useQuery({
    ...{
      queryKey: ["/system"],
      queryFn: () => api<Schema<"SystemStatusView">>("/system"),
    },
    enabled: !!session.data,
    refetchInterval: 30_000,
  });
  const [effects, setEffects] = useState(
    localStorage.getItem("boxen.reduce-effects") === "true",
  );
  useEffect(() => {
    document.documentElement.dataset.reduced = String(effects);
    localStorage.setItem("boxen.reduce-effects", String(effects));
  }, [effects]);
  useEffect(() => {
    const requestSignIn = () => setExpired(true);
    window.addEventListener("boxen-session-expired", requestSignIn);
    return () =>
      window.removeEventListener("boxen-session-expired", requestSignIn);
  }, []);
  useEffect(() => {
    document.querySelector("main h1")?.scrollIntoView({ block: "nearest" });
    (document.querySelector("main h1") as HTMLElement)?.focus({
      preventScroll: true,
    });
  }, [location.pathname]);
  useEffect(() => {
    function shortcut(e: KeyboardEvent) {
      if (
        e.key === "/" &&
        !/input|textarea|select/i.test((e.target as HTMLElement).tagName)
      ) {
        e.preventDefault();
        document.getElementById("global-search")?.focus();
      }
    }
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, []);
  if (session.isPending) return <Loading />;
  if (session.error)
    return (
      <main className="auth">
        <ErrorNote error={session.error} />
        <button onClick={() => session.refetch()}>Retry connection</button>
      </main>
    );
  if (!session.data)
    return (
      <Navigate
        to={
          "/login?next=" +
          encodeURIComponent(location.pathname + location.search)
        }
        replace
      />
    );
  const user = session.data.user,
    anonymous = !!session.data.anonymous,
    editor = user.role !== "viewer";
  const links = [
    ["/", "Home", "home"],
    ["/boxes", "Boxes", "box"],
    ["/scan", "Scan", "scan"],
    ...(editor ? [["/review", "Review", "review"]] : []),
    ["/system", "System", "system"],
  ];
  const degraded =
    status.error ||
    (status.data &&
      Object.entries(status.data.components).some(
        ([key, item]) => key !== "ai" && item.status !== "ready",
      ));
  return (
    <SessionContext.Provider value={session.data}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className="rail">
        <Link className="brand" to="/">
          <Icon size={32} />
          <span>
            BOXEN<small>LOCAL INVENTORY NODE</small>
          </span>
        </Link>
        <div className="rail-caption">WORKSPACE / 01</div>
        <nav aria-label="Primary">
          {links.map(([to, label, icon]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              <Icon name={icon} />
              <span>{label}</span>
            </NavLink>
          ))}
          <NavLink
            to="/collections"
            className="org-desktop-nav"
            aria-label="Collections"
          >
            <Icon name="box" />
            <span>Collections</span>
          </NavLink>
        </nav>
        <div className="rail-bottom">
          <div className={"local-state " + (degraded ? "caution" : "")}>
            <Icon name="shield" size={18} />
            <span>
              {degraded ? "Local system degraded" : "Local system ready"}
            </span>
          </div>
          <label className="effect-toggle">
            <input
              type="checkbox"
              checked={effects}
              onChange={(e) => setEffects(e.target.checked)}
            />
            Reduce visual effects
          </label>
          <Link className="user-link" to="/account">
            <span className="avatar">{user.display_name.charAt(0)}</span>
            <span>
              {anonymous ? "Local access" : user.display_name}
              <small>
                {anonymous
                  ? `Anonymous · ${editor ? "can edit" : "view only"}`
                  : user.role}
              </small>
            </span>
          </Link>
          {anonymous ? (
            <Link className="button" to="/login">
              Sign in
            </Link>
          ) : (
            <button
              className="ghost"
              onClick={async () => {
                await api("/auth/logout", { method: "POST" });
                cache.clear();
                setSession(null);
                cache.removeQueries({ queryKey: ["session"] });
                navigate("/");
              }}
            >
              <Icon name="logout" size={18} />
              Sign out
            </button>
          )}
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span className="eyebrow">
            BOXEN <span className="muted">/ PRIVATE BY DESIGN</span>
          </span>
          <SearchBar compact />
          <Link className="button" to="/scan">
            <Icon name="scan" />
            Scan code
          </Link>
          <Link
            className="button account-link"
            to={anonymous ? "/login" : "/account"}
          >
            {anonymous ? "Sign in" : "Account"}
          </Link>
        </header>
        {status.error && (
          <div className="host-banner">
            <ErrorNote error={status.error} />
            <button onClick={() => status.refetch()}>Retry</button>
          </div>
        )}
        <main id="main">
          <Outlet />
        </main>
        <footer className="footer">
          <span>STORED HERE. FOUND HERE.</span>
          <span>LOCAL STORAGE · NO CLOUD</span>
        </footer>
      </div>
      {expired && (
        <Reauthenticate
          username={anonymous ? "" : user.username}
          anonymous={anonymous}
          close={() => setExpired(false)}
        />
      )}
    </SessionContext.Provider>
  );
}
function Reauthenticate({
  username,
  anonymous,
  close,
}: {
  username: string;
  anonymous: boolean;
  close: () => void;
}) {
  const [password, setPassword] = useState(""),
    [loginName, setLoginName] = useState(username),
    [error, setError] = useState<unknown>(),
    [busy, setBusy] = useState(false);
  const [fields, setFields] = useState<AuthErrors>({});
  return (
    <Modal title="Confirm your local sign-in" close={() => !busy && close()}>
      <p>
        Your form is still open. Sign in again to continue saving or perform a
        sensitive action.
      </p>
      {anonymous && (
        <button
          className="primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const fresh = await api<Session>("/session");
              setSession(fresh);
              await cache.invalidateQueries({
                predicate: (q) => q.queryKey[0] !== "session",
              });
              close();
            } catch (e) {
              setError(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          Resume anonymous access
        </button>
      )}
      <form
        noValidate
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy) return;
          const values = authValues(new FormData(e.currentTarget));
          const invalid = validateAuth(values, false);
          setFields(invalid);
          setError(null);
          if (Object.keys(invalid).length) {
            setError(new Error("Correct the marked fields, then try again."));
            const first = e.currentTarget.elements.namedItem(
              invalid.username ? "username" : "password",
            );
            if (first instanceof HTMLElement) first.focus();
            return;
          }
          setBusy(true);
          try {
            const session = await api<Session>("/auth/login", {
              method: "POST",
              body: { username: values.username, password: values.password },
            });
            setSession(session);
            await cache.invalidateQueries({
              predicate: (q) => q.queryKey[0] !== "session",
            });
            close();
          } catch (e) {
            setError(e);
            setFields(authServerErrors(e, false));
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="Username" error={fields.username}>
          <input
            name="username"
            value={loginName}
            onChange={(e) => {
              setLoginName(e.target.value);
              setFields((fields) => ({ ...fields, username: undefined }));
              setError(null);
            }}
            readOnly={!anonymous}
            autoComplete="username"
            required
          />
        </Field>
        <Field label="Password" error={fields.password}>
          <input
            name="password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setFields((fields) => ({ ...fields, password: undefined }));
              setError(null);
            }}
            type="password"
            autoComplete="current-password"
            required
            autoFocus
          />
        </Field>
        <ErrorNote error={error} />
        <button className="primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in and continue"}
        </button>
      </form>
    </Modal>
  );
}
function RouteError() {
  const error = useRouteError();
  return (
    <main className="auth">
      <h1>Unable to open this page</h1>
      <ErrorNote error={error} />
      <a className="button" href="/">
        Return home
      </a>
    </main>
  );
}
const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  { path: "/setup", element: <Login setup /> },
  {
    element: <Shell />,
    errorElement: <RouteError />,
    children: [
      { path: "/", element: <Home /> },
      { path: "/boxes", element: <Boxes /> },
      { path: "/boxes/new", element: <BoxEditor /> },
      { path: "/boxes/:boxCode", element: <BoxDetail /> },
      { path: "/boxes/:boxCode/edit", element: <BoxEditor /> },
      { path: "/boxes/:boxCode/label", element: <Labels /> },
      { path: "/search", element: <Search /> },
      { path: "/collections", element: <Collections /> },
      { path: "/collections/:collectionId", element: <CollectionDetailPage /> },
      { path: "/scan", element: <Scan /> },
      { path: "/review", element: <Review /> },
      { path: "/account", element: <Account /> },
      { path: "/system", element: <System /> },
      { path: "/system/users", element: <Users /> },
      { path: "/system/backups", element: <Backups /> },
      { path: "/system/maintenance", element: <Maintenance /> },
      {
        path: "*",
        element: (
          <>
            <h1>Page not found</h1>
            <Link to="/">Return home</Link>
          </>
        ),
      },
    ],
  },
]);
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={cache}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
