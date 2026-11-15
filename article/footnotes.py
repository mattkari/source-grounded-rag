"""Find the footnotes of a thesis from its PDF — PLAN_V6 §7.

A footnote usually cites another writer. If its text is drafted from as if it
were body text, an article says "the author argues…" about something the
author only cites. This module builds a *footnote map*: for each PDF page, the
text of the blocks that have a footnote's shape.

A block has a footnote's shape when it sits at the foot of the column, below
the last body-size text on its page, and opens with a small numeral (the same
test `layout.py` applies when it counts them).

The map is derived and held apart. It is never written into the canonical
extraction or the index (hard rule 7) and the evaluation never reads it. It is
a heuristic about shape, not proof (hard rule 12): blocks at the foot of the
column that do not open with a numeral are counted separately as *unclear*,
for the researcher to see.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import layout
from documents import Document

_SPACES = re.compile(r"\s+")


def _squash(text: str) -> str:
    """Text with all white space removed, so matching does not depend on line breaks."""
    return _SPACES.sub("", text.replace("\xad", "").replace(" ", " ").replace("​", ""))


@dataclass
class FootnoteMap:
    by_page: dict[int, list[str]] = field(default_factory=dict)   # pdf page -> footnote texts
    unclear_by_page: dict[int, int] = field(default_factory=dict) # pdf page -> foot blocks with no numeral

    @property
    def count(self) -> int:
        return sum(len(texts) for texts in self.by_page.values())

    @property
    def pages(self) -> int:
        return len(self.by_page)

    @property
    def unclear(self) -> int:
        return sum(self.unclear_by_page.values())


def build(document: Document) -> FootnoteMap:
    """Read the document's PDF and map its footnote-shaped blocks."""
    profile = document.layout
    found = FootnoteMap()
    for blocks in layout.read_blocks(document.pdf_path):
        zone = [b for b in blocks if layout._in_zone(b, profile.header_band_y, profile.footnote_band_y)]
        body_rows = [b.y0 for b in zone if b.dominant_size() == profile.body_size]
        if not body_rows:
            continue
        last_body = max(body_rows)
        for block in zone:
            if block.y0 <= last_body or block.dominant_size() >= profile.body_size:
                continue
            # What the extractor would have kept of this block: spans at or above the body floor.
            kept = " ".join(s["text"] for s in block.spans if s["size"] >= profile.body_min_size)
            if not _squash(kept):
                continue  # already dropped by the extractor; nothing reaches the index
            if layout._is_marker_led(block):
                found.by_page.setdefault(block.pdf_page, []).append(kept)
            else:
                found.unclear_by_page[block.pdf_page] = found.unclear_by_page.get(block.pdf_page, 0) + 1
    return found


def footnotes_in(chunk: dict, footnotes: FootnoteMap) -> list[str]:
    """The footnote texts that appear inside a passage, from the pages it covers."""
    haystack = _squash(chunk["text"])
    present = []
    for pdf_page in range(chunk["pdf_page_start"], chunk["pdf_page_end"] + 1):
        for text in footnotes.by_page.get(pdf_page, []):
            if _squash(text) and _squash(text) in haystack:
                present.append(text)
    return present


def touched(chunks: list[dict], footnotes: FootnoteMap) -> list[str]:
    """Chunk ids of the passages that contain footnote text."""
    return [chunk["chunk_id"] for chunk in chunks if footnotes_in(chunk, footnotes)]
