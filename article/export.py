"""The article as it is published — ADR 0008.

What leaves the app is what the record shows: the export is built from the
reviewed article, and only from that. It differs from the working draft in
form, not in content:

  * an AI disclosure is the first paragraph, and it names the source;
  * there is no draft banner;
  * sources are compact: author, year, section number, printed pages;
  * the text this module adds holds no em dash.

Pages come from `ask.page_phrase`, which reads stored provenance. Nothing here
resolves or writes a page number.
"""

from __future__ import annotations

import html
import re

import ask
from article import assemble

SOURCES_HEADING = "Sources"
_NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+\S")
LOCATOR_MAX = 60


def is_owner(document, owner_name: str | None) -> bool | None:
    """Whether the source is the configured owner's own work. None when no owner is
    configured: the export then names the source and claims nothing about whose it is."""
    if not owner_name or not owner_name.strip():
        return None
    surname = document.author.split(",")[0].strip().lower()
    return bool(surname) and surname in owner_name.lower()


def disclosure(document, owner_name: str | None) -> str:
    """The first paragraph. It says an AI system drafted the text and names the source.
    When the source is another author's work it says so in plain words."""
    source = f"{document.author} ({document.year}), {document.title}"
    mine = is_owner(document, owner_name)
    if mine is True:
        return (f"This article was drafted with an AI system from my own work, {source}. "
                "I checked every sentence against the pages cited.")
    if mine is False:
        return (f"This article was drafted with an AI system. It summarises the work of another author: {source}. "
                "Every sentence was checked against the pages cited, and the ideas are that author's.")
    return (f"This article was drafted with an AI system from {source}. "
            "Every sentence was checked against the pages cited.")


def _locator(chunk: dict) -> str:
    """Where in the document, briefly: the section number if the section is numbered,
    otherwise the section or chapter title, shortened."""
    section, chapter = (chunk.get("section") or "").strip(), (chunk.get("chapter") or "").strip()
    numbered = _NUMBERED.match(section)
    if numbered:
        return f"§ {numbered.group(1)}"
    title = section or chapter
    if not title:
        return ""
    if title.isupper():
        title = title[0] + title[1:].lower()
    return title if len(title) <= LOCATOR_MAX else title[: LOCATOR_MAX - 1].rstrip() + "…"


def source_line(entry: dict) -> str:
    """ "[4] Author (year), § 5.2, pp. 202–203." """
    chunk = entry["chunk"]
    document = ask._document(entry["document"])
    parts = [f"{document.author} ({document.year})", _locator(chunk), ask.page_phrase(chunk)]
    return f"[{entry['n']}] " + ", ".join(part for part in parts if part) + "."


def markdown(article: assemble.Article, document, owner_name: str | None) -> str:
    out: list[str] = []
    limits = [text for kind, text in article.blocks if kind == "limit"]
    for kind, text in article.blocks:
        if kind == "title":
            out += [f"# {text}", "", disclosure(document, owner_name), ""]
        elif kind == "heading":
            out += [f"## {text}", ""]
        elif kind != "limit":
            out += [text, ""]
    if limits:
        out += [f"## {assemble.NOT_COVERED_HEADING}", ""] + [f"- {line}" for line in limits] + [""]
    if article.sources:
        out += [f"## {SOURCES_HEADING}", ""]
        for entry in article.sources:
            out += [source_line(entry), ""]
    return "\n".join(out).rstrip() + "\n"


def as_html(article: assemble.Article, document, owner_name: str | None) -> str:
    """The same content as `markdown`, as plain HTML that an editor such as Medium's
    keeps on paste: headings, paragraphs and one list."""
    escape = html.escape
    out: list[str] = []
    limits = [text for kind, text in article.blocks if kind == "limit"]
    for kind, text in article.blocks:
        if kind == "title":
            out += [f"<h1>{escape(text)}</h1>", f"<p>{escape(disclosure(document, owner_name))}</p>"]
        elif kind == "heading":
            out.append(f"<h2>{escape(text)}</h2>")
        elif kind != "limit":
            out += [f"<p>{escape(part)}</p>" for part in text.split("\n") if part.strip()]
    if limits:
        out.append(f"<h2>{escape(assemble.NOT_COVERED_HEADING)}</h2>")
        out.append("<ul>" + "".join(f"<li>{escape(line)}</li>" for line in limits) + "</ul>")
    if article.sources:
        out.append(f"<h2>{SOURCES_HEADING}</h2>")
        out += [f"<p>{escape(source_line(entry))}</p>" for entry in article.sources]
    return "\n".join(out) + "\n"
