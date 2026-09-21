from html.parser import HTMLParser

import nh3
from markdown_it import MarkdownIt

VERSION = "commonmark-nh3-v1"
PARSER = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
TAGS = {
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "em",
    "strong",
    "s",
    "blockquote",
    "pre",
    "code",
    "ul",
    "ol",
    "li",
    "a",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "pre"}:
            self.parts.append("\n")


def render_markdown(source: str) -> dict:
    rendered = PARSER.render(source)
    safe = nh3.clean(
        rendered,
        tags=TAGS,
        attributes={"a": {"href", "title"}, "ol": {"start"}},
        url_schemes={"http", "https"},
        link_rel="noopener noreferrer",
        clean_content_tags={"script", "style", "iframe", "object"},
    )
    parser = PlainText()
    parser.feed(safe)
    return {
        "source": source,
        "html": safe,
        "text": "".join(parser.parts).strip(),
        "renderer_version": VERSION,
    }


def markdown_columns(source: str, prefix: str) -> dict:
    result = render_markdown(source)
    return {
        f"{prefix}_markdown": result["source"],
        f"{prefix}_html": result["html"],
        f"{prefix}_text": result["text"],
        "markdown_renderer_version": VERSION,
    }


def markdown_view(row: dict, prefix: str) -> dict:
    return {
        "source": row[f"{prefix}_markdown"],
        "html": row[f"{prefix}_html"],
        "text": row[f"{prefix}_text"],
        "renderer_version": row["markdown_renderer_version"],
    }
