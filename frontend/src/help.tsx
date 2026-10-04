import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import MarkdownIt from "markdown-it";
import { Markdown } from "./components";
import gettingStarted from "../../docs/help/getting-started.md?raw";
import authentication from "../../docs/help/authentication.md?raw";
import administration from "../../docs/help/administration.md?raw";
import inventory from "../../docs/help/inventory.md?raw";
import deployment from "../../docs/operations/deployment.md?raw";
import development from "../../docs/operations/development.md?raw";
import configuration from "../../docs/operations/container-storage.md?raw";
import recovery from "../../docs/operations/recovery.md?raw";
import models from "../../docs/operations/models.md?raw";
import remoteAI from "../../docs/operations/remote-ai.md?raw";
import nativeHTTPS from "../../docs/operations/native-https.md?raw";
import containerTailnet from "../../docs/operations/container-tailnet.md?raw";
import nativeTailnet from "../../docs/operations/native-tailnet.md?raw";
import "./help.css";

const topics = [
  { id: "getting-started", title: "Start here", source: gettingStarted },
  {
    id: "authentication",
    title: "Authentication setup",
    source: authentication,
  },
  { id: "administration", title: "Users and sign-ins", source: administration },
  { id: "inventory", title: "Using your inventory", source: inventory },
  { id: "deployment", title: "Container quick start", source: deployment },
  { id: "development", title: "Native development", source: development },
  {
    id: "container-tailnet",
    title: "Tailscale containers",
    source: containerTailnet,
  },
  {
    id: "native-tailnet",
    title: "Previous native Tailscale setup",
    source: nativeTailnet,
  },
  {
    id: "container-storage",
    title: "Storage and configuration",
    source: configuration,
  },
  { id: "native-https", title: "Native HTTPS and phones", source: nativeHTTPS },
  { id: "recovery", title: "Backups and recovery", source: recovery },
  { id: "models", title: "Local AI", source: models },
  { id: "remote-ai", title: "Remote AI", source: remoteAI },
];
const parser = new MarkdownIt({ html: false, linkify: false });
const renderLink =
  parser.renderer.rules.link_open ??
  ((tokens, i, options, _env, self) => self.renderToken(tokens, i, options));
parser.renderer.rules.link_open = (tokens, i, options, env, self) => {
  const href = tokens[i].attrGet("href") ?? "";
  if (
    !href.startsWith("/") &&
    !href.startsWith("#") &&
    !/^https?:/.test(href)
  ) {
    const filename = href.split("#")[0].split("/").at(-1)?.replace(/\.md$/, "");
    const target = topics.find((topic) => topic.id === filename);
    if (target) {
      tokens[i].attrSet(
        "href",
        `/help/${target.id}${href.includes("#") ? "#" + href.split("#")[1] : ""}`,
      );
    } else {
      // Runbook evidence references live in the checkout, not under an app route.
      tokens[i].attrs =
        tokens[i].attrs?.filter(([name]) => name !== "href") ?? null;
      tokens[i].attrSet("title", `Repository reference: ${href}`);
    }
  }
  return renderLink(tokens, i, options, env, self);
};
// Stable section anchors allow the operations runbooks' existing deep links to work.
parser.renderer.rules.heading_open = (tokens, i, options, _env, self) => {
  const heading = tokens[i + 1]?.content ?? "";
  tokens[i].attrSet(
    "id",
    heading
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-"),
  );
  return self.renderToken(tokens, i, options);
};

export function Help() {
  const { topic = "getting-started" } = useParams();
  const [search, setSearch] = useState("");
  const current = topics.find((entry) => entry.id === topic);
  const html = useMemo(
    () => (current ? parser.render(current.source) : ""),
    [current],
  );
  const visible = topics.filter((entry) =>
    `${entry.title} ${entry.source}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  useEffect(() => {
    document.title = `${current?.title ?? "Help"} · Boxen`;
    const heading = document.querySelector<HTMLElement>(".help-article h1");
    heading?.setAttribute("tabindex", "-1");
    if (window.location.hash)
      document
        .getElementById(decodeURIComponent(window.location.hash.slice(1)))
        ?.scrollIntoView();
    else {
      heading?.focus({ preventScroll: true });
      window.scrollTo(0, 0);
    }
  }, [topic, current]);
  return (
    <div className="help-layout">
      <a className="skip-link" href="#help-content">
        Skip to help content
      </a>
      <header className="help-header">
        <Link className="brand" to="/">
          BOXEN <small>HELP & SETUP</small>
        </Link>
        <div className="actions">
          <Link className="button" to="/">
            Open inventory
          </Link>
          <Link className="button" to="/login">
            Sign in
          </Link>
        </div>
      </header>
      <div className="help-body">
        <aside className="help-navigation">
          <label htmlFor="help-search">Find a help topic</label>
          <input
            id="help-search"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search help…"
          />
          <nav aria-label="Help topics">
            {visible.map((entry) => (
              <NavLink
                key={entry.id}
                to={`/help/${entry.id}`}
                aria-current={entry.id === topic ? "page" : undefined}
              >
                {entry.title}
              </NavLink>
            ))}
          </nav>
          {visible.length === 0 && (
            <p role="status">
              No matching topics. Try “password”, “backup” or “phone”.
            </p>
          )}
        </aside>
        <main id="help-content" className="help-article panel">
          {current ? (
            <Markdown html={html} />
          ) : (
            <>
              <h1>Help topic not found</h1>
              <Link to="/help">Start here</Link>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
