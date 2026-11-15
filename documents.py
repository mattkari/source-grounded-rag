"""The document a question is asked of — PLAN_V4 §5 and §11.

Until now the pipeline read one thesis's identity, layout and index location
from the global settings object. That made "another thesis" a code edit. This
module carries those three things in one small object, `Document`, which is
passed in explicitly.

Two kinds of document exist:

  * The **built-in** thesis. Its profile is the hand-measured one in config.py
    and its index is the committed `index/`. It is the default everywhere, it is
    the only corpus the evaluation runs against, and nothing in this module can
    move, re-ingest or remove it.
  * An **uploaded** thesis. Its record lives in `library/<document_id>/` (see
    upload.py) and becomes a `Document` only once the researcher has approved
    it and its index is built.

No behaviour changes for the built-in thesis: `default_document()` is built
from the same settings values the code used to read directly.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

from config import settings as _settings

RUNNING_HEADER = "running_header"
HEADING = "heading"


@dataclass(frozen=True)
class LayoutProfile:
    """What is true of one particular PDF. Every value is measured, never guessed.

    A value of None means "this document does not print that feature, or it
    could not be measured": the extractor then reads nothing from it, and the
    gap is reported to the researcher rather than filled in (hard rule 6).
    """

    # Type size of ordinary body text. Bold text at this size or above, in a
    # heading face, is a heading.
    body_size: float
    # Smallest size still read as body text (block quotations sit here).
    # Anything smaller is footnote apparatus and is dropped.
    body_min_size: float
    # Blocks starting above this y are the running header; None = no header band.
    header_band_y: float | None
    # Blocks starting below this y are the page footer; None = no footer band.
    footnote_band_y: float | None
    # Which band prints the page number: "footer", "header", or None.
    page_number_band: str | None
    # Any text at or above this size is a heading, whatever its face.
    heading_min_size: float
    # Faces that mark a heading when set at body size.
    heading_fonts: tuple[str, ...]
    # Size thresholds for heading levels: >= chapter -> 1, >= section -> 2, else 3.
    chapter_heading_min_size: float
    section_heading_min_size: float
    # Which printed feature carries the chapter: RUNNING_HEADER, HEADING, or None
    # when the document prints neither (chunks then carry no chapter).
    chapter_source: str | None
    # Chapters indexed as reference apparatus rather than as source claims.
    apparatus_chapter_prefixes: tuple[str, ...]

    def to_json(self) -> dict:
        data = dataclasses.asdict(self)
        data["heading_fonts"] = list(self.heading_fonts)
        data["apparatus_chapter_prefixes"] = list(self.apparatus_chapter_prefixes)
        return data

    @classmethod
    def from_json(cls, data: dict) -> "LayoutProfile":
        fields = {f.name for f in dataclasses.fields(cls)}
        values = {key: value for key, value in data.items() if key in fields}
        values["heading_fonts"] = tuple(values.get("heading_fonts") or ())
        values["apparatus_chapter_prefixes"] = tuple(values.get("apparatus_chapter_prefixes") or ())
        return cls(**values)


@dataclass(frozen=True)
class Document:
    document_id: str
    author: str          # as it appears in a citation, e.g. "Surname, I."
    year: str
    title: str
    short_title: str     # shown to the model above each passage, and embedded with it
    layout: LayoutProfile
    pdf_path: Path
    canonical_dir: Path
    index_dir: Path
    builtin: bool = False


def default_layout(settings=_settings) -> LayoutProfile:
    """The hand-measured profile of the built-in thesis, from config.py."""
    return LayoutProfile(
        body_size=settings.body_size,
        body_min_size=settings.body_min_size,
        header_band_y=settings.header_band_y,
        footnote_band_y=settings.footnote_band_y,
        page_number_band="footer",
        heading_min_size=settings.heading_min_size,
        heading_fonts=tuple(settings.heading_fonts),
        chapter_heading_min_size=settings.chapter_heading_min_size,
        section_heading_min_size=settings.section_heading_min_size,
        chapter_source=settings.chapter_source,
        apparatus_chapter_prefixes=tuple(settings.apparatus_chapter_prefixes),
    )


def default_document(settings=_settings) -> Document:
    """The built-in thesis: frozen, read-only, and the default everywhere.

    `settings` is a parameter so a caller holding its own settings object (as
    the tests do, to point at a fixture index) gets a document built from it.
    """
    return Document(
        document_id=settings.document_id,
        author=settings.document_author,
        year=settings.document_year,
        title=settings.document_title,
        short_title=settings.document_short_title,
        layout=default_layout(settings),
        pdf_path=settings.pdf_path,
        canonical_dir=settings.canonical_dir,
        index_dir=settings.index_dir,
        builtin=True,
    )
