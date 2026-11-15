"""What an article may be drafted from — PLAN_V6 §7.

A footnote or a reference-list entry is never presented as the thesis author's
own view. This module builds the *filtered view* of an index that the article
writer drafts from:

  * reference-list passages (`kind: "apparatus"`) are left out;
  * footnote text inside a body passage is cut out of the text the model sees;
  * a passage that is mostly footnote text is left out.

The index itself is never changed (hard rule 7). The filter is a list of
character spans per passage, held in a side file of ids and numbers only — no
text of the thesis — so it can be committed for the built-in thesis and used
where the PDF is not present. It is tied to the index it was measured on by
that index's corpus hash, and is ignored if the hash differs.

Every exclusion is counted (`SourceReport`) and shown to the researcher. The
filter is a heuristic about shape (hard rule 12): it can miss a footnote or cut
body text in a layout it was not tested on, and the counts are how that is seen.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from article import footnotes
from documents import Document

SIDE_DIR = Path(__file__).resolve().parent.parent / "footnote_maps"
SCHEMA_VERSION = 1
MOSTLY_FOOTNOTE = 0.5      # a passage that loses more than this share of its text is not used
MIN_SPLIT = 15             # shortest footnote fragment recognised at the edge of a passage
_IGNORED = {"\xad", "​", "\xa0"}


class NoFootnoteMap(RuntimeError):
    """The document's footnotes cannot be told apart, so nothing may be drafted from it."""


def _squash_with_offsets(text: str) -> tuple[str, list[int]]:
    """`footnotes._squash`, plus where each kept character sits in `text`."""
    kept, offsets = [], []
    for position, char in enumerate(text):
        if char.isspace() or char in _IGNORED:
            continue
        kept.append(char)
        offsets.append(position)
    return "".join(kept), offsets


def _merge(spans: list[tuple[int, int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def footnote_spans(chunk: dict, footnote_map: footnotes.FootnoteMap) -> list[list[int]]:
    """Character spans of `chunk["text"]` that are footnote text.

    A footnote held whole is found wherever it sits. One cut in two by the
    boundary between passages is found as its opening at the end of one passage
    and its remainder at the start of the next.
    """
    squashed, offsets = _squash_with_offsets(chunk["text"])
    found: list[tuple[int, int]] = []
    for pdf_page in range(chunk["pdf_page_start"], chunk["pdf_page_end"] + 1):
        for text in footnote_map.by_page.get(pdf_page, []):
            note = footnotes._squash(text)
            if not note:
                continue
            start = squashed.find(note)
            if start >= 0:
                while start >= 0:
                    found.append((start, start + len(note)))
                    start = squashed.find(note, start + len(note))
                continue
            for size in range(len(note) - 1, MIN_SPLIT - 1, -1):      # its opening, at the end
                if squashed.endswith(note[:size]):
                    found.append((len(squashed) - size, len(squashed)))
                    break
            for size in range(len(note) - 1, MIN_SPLIT - 1, -1):      # its remainder, at the start
                if squashed.startswith(note[-size:]):
                    found.append((0, size))
                    break
    return [[offsets[start], offsets[end - 1] + 1] for start, end in _merge(found)]


def cut(text: str, spans: list[list[int]]) -> str:
    """`text` without the given spans."""
    pieces, position = [], 0
    for start, end in spans:
        pieces.append(text[position:start])
        position = end
    pieces.append(text[position:])
    return "\n".join(piece.strip() for piece in pieces if piece.strip())


# ---------------------------------------------------------------------------
# The side file: ids and numbers only
# ---------------------------------------------------------------------------


def side_path(document: Document) -> Path:
    return SIDE_DIR / f"{document.document_id}.json"


def measure(document: Document, chunks: list[dict], corpus_hash: str | None) -> dict:
    """Read the PDF and measure the spans. Raises if the PDF is not there."""
    if not document.pdf_path.exists():
        raise NoFootnoteMap(
            f"The PDF of {document.document_id} is not on this machine, and no footnote map was "
            "stored for it. Without one, footnotes cannot be told from the author's own text, so "
            "no article is drafted from this document."
        )
    footnote_map = footnotes.build(document)
    spans = {chunk["chunk_id"]: footnote_spans(chunk, footnote_map) for chunk in chunks}
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": document.document_id,
        "corpus_text_sha256": corpus_hash,
        "footnotes_found": footnote_map.count,
        "pages_with_footnotes": footnote_map.pages,
        "unclear_foot_blocks": footnote_map.unclear,
        "spans": {chunk_id: found for chunk_id, found in spans.items() if found},
    }


def load_or_measure(document: Document, chunks: list[dict], corpus_hash: str | None, *, store: bool = True) -> dict:
    """The stored map if it belongs to this index; otherwise measured from the PDF."""
    path = side_path(document)
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        if stored.get("schema_version") == SCHEMA_VERSION and stored.get("corpus_text_sha256") == corpus_hash:
            return stored
    measured = measure(document, chunks, corpus_hash)
    if store:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(measured, indent=1) + "\n", encoding="utf-8")
    return measured


# ---------------------------------------------------------------------------
# The filtered view
# ---------------------------------------------------------------------------


@dataclass
class SourceReport:
    passages_in_index: int = 0
    reference_list_excluded: int = 0
    footnote_text_removed_from: int = 0
    dropped_mostly_footnote: int = 0
    passages_available: int = 0
    footnotes_found: int = 0
    unclear_foot_blocks: int = 0
    dropped_chunk_ids: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)

    def lines(self) -> list[str]:
        return [
            f"passages in the index              {self.passages_in_index}",
            f"reference-list passages left out   {self.reference_list_excluded}",
            f"footnote text cut from             {self.footnote_text_removed_from}",
            f"left out as mostly footnote        {self.dropped_mostly_footnote}",
            f"passages the article may draw on   {self.passages_available}",
            f"footnotes found in the document    {self.footnotes_found}",
            f"foot blocks of unclear kind (kept) {self.unclear_foot_blocks}",
        ]


@dataclass
class Sources:
    """Vectors and passages to hand to `ask.run_query` in place of the full index."""
    vectors: np.ndarray
    chunks: list[dict]
    report: SourceReport
    removed: dict[str, int]          # chunk id -> number of footnote spans cut from it


def filtered(vectors: np.ndarray, chunks: list[dict], side: dict) -> Sources:
    """Copies only: the lists and arrays passed in are left as they were."""
    report = SourceReport(
        passages_in_index=len(chunks),
        footnotes_found=side.get("footnotes_found", 0),
        unclear_foot_blocks=side.get("unclear_foot_blocks", 0),
    )
    rows, kept, removed = [], [], {}
    for row, chunk in enumerate(chunks):
        if chunk.get("kind") == "apparatus":
            report.reference_list_excluded += 1
            continue
        spans = side["spans"].get(chunk["chunk_id"], [])
        if spans:
            text = cut(chunk["text"], spans)
            lost = sum(end - start for start, end in spans) / max(len(chunk["text"]), 1)
            if lost > MOSTLY_FOOTNOTE or not text:
                report.dropped_mostly_footnote += 1
                report.dropped_chunk_ids.append(chunk["chunk_id"])
                continue
            report.footnote_text_removed_from += 1
            removed[chunk["chunk_id"]] = len(spans)
            chunk = {**chunk, "text": text}
        rows.append(row)
        kept.append(chunk)
    report.passages_available = len(kept)
    return Sources(vectors=vectors[rows], chunks=kept, report=report, removed=removed)


def open_sources(document: Document, vectors: np.ndarray, chunks: list[dict], manifest: dict, *, store: bool = True) -> Sources:
    side = load_or_measure(document, chunks, manifest.get("corpus_text_sha256"), store=store)
    return filtered(vectors, chunks, side)
