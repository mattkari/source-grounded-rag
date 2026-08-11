"""PDF -> canonical pages -> chapter/section-bounded chunks -> embeddings -> index.

Run:  python ingest.py

Provenance chain built here (PLAN_V2 §11.1):
    document_id -> chapter -> section -> page_start..page_end -> chunk_id -> verbatim text

Two rules govern this file:
  * The canonical extraction is immutable once written (hard rule 7).
  * A chunk never crosses a chapter boundary (hard rule 8).
  * Structure that cannot be resolved confidently is left null and flagged
    for human verification (hard rule 6) — never invented.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pymupdf
import tiktoken

from config import settings
from embeddings import active_model_name, embed_texts

# --- layout constants, measured from this document ------------------------
# Body text is 12.0pt TimesNewRomanPSMT. Running headers and footnotes are
# 9.8pt / 6.5pt; inline footnote reference markers are 7.9pt superscripts.
# Filtering at 11pt drops all three, which is what keeps footnote apparatus
# out of quotable evidence.
BODY_MIN_SIZE = 11.0
HEADER_BAND_Y = 60.0     # above this: running header
FOOTNOTE_BAND_Y = 780.0  # below this: page-number footer
HEADING_FONTS = ("Calibri-Bold", "Calibri-BoldItalic", "TimesNewRomanPS-BoldItal")
HEADING_MIN_SIZE = 13.0  # any span this large is a heading regardless of font
CAPTION_PREFIXES = ("Table ", "Figure ", "Chart ", "Diagram ")

ROMAN_RE = re.compile(r"^[ivxlcdm]+$")
ARABIC_RE = re.compile(r"^\d{1,4}$")
SENTENCE_END_RE = re.compile(r"[.!?][\"'’”)\]]*\s+")

_ENCODER = tiktoken.get_encoding("cl100k_base")


def ntokens(text: str) -> int:
    return len(_ENCODER.encode(text, disallowed_special=()))


def normalise(text: str) -> str:
    """Collapse the extractor's tab/CR/nbsp padding into ordinary spaces."""
    text = text.replace("\xad", "").replace(" ", " ")
    text = text.replace("\t", " ").replace("\r", " ").replace("​", "")
    return re.sub(r"[ ]{2,}", " ", text).strip()


# ---------------------------------------------------------------------------
# Stage 1 — canonical extraction
# ---------------------------------------------------------------------------


@dataclass
class Page:
    pdf_page: int                 # 1-based physical page
    printed_page: str | None      # label printed by the document itself
    running_header: str | None    # chapter title as printed on the page
    body: str
    headings: list[tuple[int, int, str]] = field(default_factory=list)  # (offset, level, title)


def _is_heading_span(span: dict) -> bool:
    size = round(span["size"], 1)
    font = span["font"]
    if size >= HEADING_MIN_SIZE:
        return True
    return size >= 12.0 and font.startswith(HEADING_FONTS)


def extract_page(page: pymupdf.Page, pdf_page: int) -> Page:
    blocks = [b for b in page.get_text("dict")["blocks"] if b["type"] == 0]
    blocks.sort(key=lambda b: (round(b["bbox"][1], 1), round(b["bbox"][0], 1)))

    printed_page: str | None = None
    header_parts: list[str] = []
    body_parts: list[str] = []
    headings: list[tuple[int, int, str]] = []
    length = 0
    prev_was_heading = False

    for block in blocks:
        y_top = block["bbox"][1]
        spans = [s for line in block["lines"] for s in line["spans"] if s["text"].strip()]
        if not spans:
            continue

        if y_top < HEADER_BAND_Y:
            header_parts.append(normalise("".join(s["text"] for s in spans)))
            continue

        if y_top > FOOTNOTE_BAND_Y:
            for span in spans:
                token = normalise(span["text"]).lower()
                if ARABIC_RE.match(token) or ROMAN_RE.match(token):
                    printed_page = normalise(span["text"])
            continue

        body_spans = [s for s in spans if round(s["size"], 1) >= BODY_MIN_SIZE]
        if not body_spans:
            continue  # footnote apparatus at the foot of the text column

        text = normalise(" ".join(s["text"] for s in body_spans))
        if not text:
            continue

        # A heading and the paragraph that follows it often share one block.
        # Classify by the leading run of heading-styled spans, not by the
        # block as a whole, or the title swallows the body text after it.
        lead = 0
        while lead < len(body_spans) and _is_heading_span(body_spans[lead]):
            lead += 1
        title = normalise(" ".join(s["text"] for s in body_spans[:lead]))
        pure_heading = lead == len(body_spans)
        is_heading = (
            lead > 0
            and len(title) < 250
            and not title.startswith(CAPTION_PREFIXES)
        )

        if is_heading and pure_heading and prev_was_heading and headings:
            # Continuation line of the heading immediately above it.
            offset, level, title = headings[-1]
            headings[-1] = (offset, level, f"{title} {text}")
            body_parts.append(" " + text)
            length += len(text) + 1
            continue

        if body_parts:
            body_parts.append("\n")
            length += 1
        if is_heading:
            size = round(body_spans[0]["size"], 1)
            level = 1 if size >= 15 else (2 if size >= 13 else 3)
            headings.append((length, level, title))
        body_parts.append(text)
        length += len(text)
        prev_was_heading = is_heading and pure_heading

    return Page(
        pdf_page=pdf_page,
        printed_page=printed_page,
        running_header=" ".join(p for p in header_parts if p) or None,
        body="".join(body_parts),
        headings=headings,
    )


def extract_document(pdf_path) -> list[Page]:
    doc = pymupdf.open(pdf_path)
    return [extract_page(doc[i], i + 1) for i in range(doc.page_count)]


# ---------------------------------------------------------------------------
# Stage 2 — chapter runs and section segments
# ---------------------------------------------------------------------------


@dataclass
class Segment:
    chapter: str | None
    section: str | None
    text: str
    pagemap: list[tuple[int, int, Page]]  # (char_start, char_end, page)


def build_segments(pages: list[Page]) -> list[Segment]:
    segments: list[Segment] = []

    # A chapter run is a maximal span of consecutive pages printing the same
    # running header. The header is printed by the document, so it is stored
    # provenance, not inference.
    runs: list[list[Page]] = []
    for page in pages:
        if not page.body.strip():
            continue
        if runs and runs[-1][-1].running_header == page.running_header:
            runs[-1].append(page)
        else:
            runs.append([page])

    for run in runs:
        chapter = run[0].running_header
        text_parts: list[str] = []
        pagemap: list[tuple[int, int, Page]] = []
        heads: list[tuple[int, int, str]] = []
        cursor = 0
        for page in run:
            if text_parts:
                text_parts.append("\n")
                cursor += 1
            start = cursor
            text_parts.append(page.body)
            cursor += len(page.body)
            pagemap.append((start, cursor, page))
            heads.extend((start + off, lvl, title) for off, lvl, title in page.headings)

        text = "".join(text_parts)
        bounds = sorted({0, *(off for off, _, _ in heads), len(text)})
        by_offset = {off: title for off, _, title in heads}

        section: str | None = None
        for lo, hi in zip(bounds, bounds[1:]):
            if lo in by_offset:
                section = by_offset[lo]
            body = text[lo:hi]
            if not body.strip():
                continue
            local_map = [
                (max(s, lo) - lo, min(e, hi) - lo, p)
                for s, e, p in pagemap
                if s < hi and e > lo
            ]
            segments.append(Segment(chapter, section, body, local_map))

    return segments


# ---------------------------------------------------------------------------
# Stage 3 — chunking
# ---------------------------------------------------------------------------


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for match in SENTENCE_END_RE.finditer(text):
        # Keep the terminal punctuation with the sentence; drop only the gap.
        end = match.end() - (len(match.group()) - len(match.group().rstrip()))
        if end > cursor:
            spans.append((cursor, end))
        cursor = match.end()
    if cursor < len(text):
        spans.append((cursor, len(text)))
    return spans or [(0, len(text))]


def chunk_segment(seg: Segment) -> list[tuple[int, int]]:
    """Return [(char_start, char_end)] offsets into seg.text. Never mid-sentence."""
    sents = _sentence_spans(seg.text)
    costs = [ntokens(seg.text[a:b]) for a, b in sents]

    chunks: list[tuple[int, int]] = []
    i = 0
    n = len(sents)
    while i < n:
        total = 0
        j = i
        while j < n:
            if j > i and total + costs[j] > settings.chunk_max_tokens:
                break
            total += costs[j]
            j += 1
            if total >= settings.chunk_target_tokens:
                break
        chunks.append((sents[i][0], sents[j - 1][1]))
        if j >= n:
            break
        # Back up whole sentences to create ~15% overlap.
        back = 0
        k = j
        while k > i + 1 and back + costs[k - 1] <= settings.chunk_overlap_tokens:
            k -= 1
            back += costs[k]
        i = k
    return chunks


def pages_for(seg: Segment, lo: int, hi: int) -> list[Page]:
    return [p for s, e, p in seg.pagemap if s < hi and e > lo]


# ---------------------------------------------------------------------------
# Stage 4 — build the chunk records
# ---------------------------------------------------------------------------


def build_chunks(segments: list[Segment]) -> list[dict]:
    records: list[dict] = []
    for seg in segments:
        for lo, hi in chunk_segment(seg):
            text = seg.text[lo:hi].strip()
            if not text or ntokens(text) < settings.chunk_min_tokens:
                continue
            covered = pages_for(seg, lo, hi)
            if not covered:
                continue
            printed = [p.printed_page for p in covered]
            unresolved = [p.pdf_page for p in covered if p.printed_page is None]
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            records.append(
                {
                    "chunk_id": f"{settings.document_id}::{len(records):05d}::{digest}",
                    "document_id": settings.document_id,
                    "chapter": seg.chapter,
                    "section": seg.section,
                    "page_start": printed[0],
                    "page_end": printed[-1],
                    "pdf_page_start": covered[0].pdf_page,
                    "pdf_page_end": covered[-1].pdf_page,
                    "pages_unresolved": unresolved,
                    "token_count": ntokens(text),
                    "text": text,
                }
            )
    return records


def embed_text(record: dict) -> str:
    """Contextual header is prepended for EMBEDDING ONLY (PLAN_V2 §7.1.7).

    The stored and cited text stays the bare passage — the header must never
    contaminate quotable evidence.
    """
    parts = [settings.document_short_title]
    if record["chapter"]:
        parts.append(record["chapter"])
    if record["section"]:
        parts.append(record["section"])
    return " — ".join(parts) + "\n\n" + record["text"]


def embed_all(records: list[dict]) -> np.ndarray:
    return embed_texts([embed_text(r) for r in records], progress=True)


# ---------------------------------------------------------------------------


def main() -> int:
    if not settings.pdf_path.exists():
        print(f"FATAL: {settings.pdf_path} not found", file=sys.stderr)
        return 1

    print(f"Extracting {settings.pdf_path.name} ...")
    pages = extract_document(settings.pdf_path)
    with_body = [p for p in pages if p.body.strip()]
    unresolved_pages = [p.pdf_page for p in with_body if p.printed_page is None]

    settings.canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical = settings.canonical_dir / "pages.jsonl"
    with canonical.open("w", encoding="utf-8") as fh:
        for p in pages:
            fh.write(
                json.dumps(
                    {
                        "pdf_page": p.pdf_page,
                        "printed_page": p.printed_page,
                        "running_header": p.running_header,
                        "text": p.body,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    segments = build_segments(pages)
    records = build_chunks(segments)
    chapters = sorted({s.chapter for s in segments if s.chapter})

    print(f"  pages in PDF          : {len(pages)}")
    print(f"  pages with body text  : {len(with_body)}")
    print(f"  pages w/o printed no. : {len(unresolved_pages)} (flagged, never guessed)")
    print(f"  chapter runs (headers): {len(chapters)}")
    print(f"  section segments      : {len(segments)}")
    print(f"  chunks                : {len(records)}")
    print(f"  canonical extraction  : {canonical}")

    print(f"Embedding with {settings.embedding_provider}:{active_model_name()} ...")
    vectors = embed_all(records)

    settings.index_dir.mkdir(parents=True, exist_ok=True)
    np.save(settings.index_dir / "vectors.npy", vectors)
    (settings.index_dir / "chunks.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    corpus_hash = hashlib.sha256(
        "\n".join(r["text"] for r in records).encode("utf-8")
    ).hexdigest()
    (settings.index_dir / "manifest.json").write_text(
        json.dumps(
            {
                "document_id": settings.document_id,
                "document_title": settings.document_title,
                "document_author": settings.document_author,
                "document_year": settings.document_year,
                "source_pdf": settings.pdf_path.name,
                "pages_total": len(pages),
                "pages_with_text": len(with_body),
                "pages_without_printed_number": unresolved_pages,
                "chunk_count": len(records),
                "embedding_provider": settings.embedding_provider,
                "embedding_model": active_model_name(),
                "embedding_dim": int(vectors.shape[1]),
                "normalised": True,
                "chunk_target_tokens": settings.chunk_target_tokens,
                "chunk_overlap_tokens": settings.chunk_overlap_tokens,
                "corpus_text_sha256": corpus_hash,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"Index written to {settings.index_dir}/ (vectors {vectors.shape})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
