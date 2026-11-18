"""Provenance audit — check an extraction against the PDF itself (PLAN_V4 §8).

ADR 0001 states the principle: provenance is audited "against the PDF itself
rather than against the pipeline that produced it". This module is that audit
as committed, tested code. It re-reads the PDF through a different PyMuPDF
interface from the one the extractor uses (plain words and text, no layout
profile, no bands) and asks three questions of every chunk:

  1. Is the page label it stores the label actually printed on that page?
  2. Does every word of it appear on the pages it claims?
  3. Does it stay inside one chapter (hard rule 8)?

The result is counts and lists, never a score. Whether a thesis is good enough
to use is the researcher's decision (hard rule 12). One outcome is not a
judgement call: a chunk whose words are not on its claimed pages would make a
citation false, so it is reported as a hard stop.

The audit never prints or stores passage text: it reports chunk ids and page
numbers only.
"""

from __future__ import annotations

import re

import pymupdf

import layout as layout_module
from documents import HEADING, RUNNING_HEADER, LayoutProfile

_WHITESPACE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """The same character clean-up the extractor applies, and nothing more."""
    return text.replace("\xad", "").replace(" ", " ").replace("​", "")


def _stream(text: str) -> str:
    """Page text as one run of characters with all whitespace removed, so the
    comparison does not depend on how either reader split lines or words."""
    return _WHITESPACE.sub("", _clean(text))


class PdfReader:
    """Independent view of the PDF: words and plain text per page, read lazily."""

    def __init__(self, pdf_path):
        self._doc = pymupdf.open(pdf_path)
        self._streams: dict[int, str] = {}
        self._lone_tokens: dict[int, set[str]] = {}

    @property
    def page_count(self) -> int:
        return self._doc.page_count

    def stream(self, pdf_page: int) -> str:
        if pdf_page not in self._streams:
            self._streams[pdf_page] = _stream(self._doc[pdf_page - 1].get_text("text"))
        return self._streams[pdf_page]

    def has_text(self, pdf_page: int) -> bool:
        return bool(self.stream(pdf_page))

    def edge_tokens(self, pdf_page: int) -> set[str]:
        """The first and last word of each line: where a journal prints a page number
        beside its name (ADR 0015)."""
        lines: dict[tuple[int, int], list[str]] = {}
        for word in self._doc[pdf_page - 1].get_text("words"):
            lines.setdefault((word[5], word[6]), []).append(_clean(word[4]).strip())
        return {words[position] for words in lines.values() for position in (0, -1)}

    def lone_tokens(self, pdf_page: int) -> set[str]:
        """Words that stand alone on their line — where a page number is printed."""
        if pdf_page not in self._lone_tokens:
            lines: dict[tuple[int, int], list[str]] = {}
            for word in self._doc[pdf_page - 1].get_text("words"):
                lines.setdefault((word[5], word[6]), []).append(_clean(word[4]).strip())
            self._lone_tokens[pdf_page] = {words[0] for words in lines.values() if len(words) == 1}
        return self._lone_tokens[pdf_page]


def _ratio(passing: int, total: int, failing: list) -> dict:
    return {"n": passing, "N": total, "failing": failing}


def audit(pdf_path, pages: list[dict], chunks: list[dict], layout: LayoutProfile) -> dict:
    """Audit canonical `pages` (rows of pages.jsonl) and `chunks` against the PDF."""
    reader = PdfReader(pdf_path)
    label_of = {row["pdf_page"]: row["printed_page"] for row in pages}
    header_of = {row["pdf_page"]: row["running_header"] for row in pages}
    has_body = {row["pdf_page"]: bool((row["text"] or "").strip()) for row in pages}

    # --- pages -----------------------------------------------------------------
    with_text = [p for p in label_of if reader.has_text(p)]
    with_body = [p for p in label_of if has_body[p]]
    numbered = [p for p in with_body if label_of[p] is not None]
    page_summary = {
        "total": reader.page_count,
        "with_text": len(with_text),
        "with_body_text": len(with_body),
        "with_printed_number": len(numbered),
        "without_printed_number": [p for p in with_body if label_of[p] is None],
        "text_but_no_body": [p for p in with_text if not has_body[p]],
    }

    # --- every stored label is printed on its page ---------------------------------
    def printed(pdf_page: int) -> bool:
        """The stored label is printed on its page: alone on a line, or, where the
        profile says the number shares its line, at an end of one."""
        label = label_of[pdf_page]
        return label in reader.lone_tokens(pdf_page) or (
            layout.page_number_inline and label in reader.edge_tokens(pdf_page))

    labelled = [p for p in label_of if label_of[p] is not None]
    label_failures = [p for p in labelled if not printed(p)]
    labels = _ratio(len(labelled) - len(label_failures), len(labelled), label_failures)

    arabic = [(p, int(label_of[p])) for p in sorted(labelled) if label_of[p].isdecimal()]
    breaks = [
        {"from_pdf_page": a[0], "to_pdf_page": b[0]}
        for a, b in zip(arabic, arabic[1:])
        if b[0] - a[0] != b[1] - a[1]
    ]
    sequence = {"steps_checked": max(len(arabic) - 1, 0), "breaks": breaks}

    # --- chunks ----------------------------------------------------------------------
    chapter_titles = {c["chapter"] for c in chunks if c["chapter"]}
    label_bad: list[str] = []
    words_bad: list[str] = []
    chapter_bad: list[str] = []
    for chunk in chunks:
        first, last = chunk["pdf_page_start"], chunk["pdf_page_end"]
        claimed = range(first, last + 1)

        # 1. The stored labels are the ones printed on the chunk's first and last page.
        ends_match = chunk["page_start"] == label_of.get(first) and chunk["page_end"] == label_of.get(last)
        printed_ok = all(label_of.get(p) is None or printed(p) for p in (first, last))
        if not (ends_match and printed_ok):
            label_bad.append(chunk["chunk_id"])

        # 2. Every word is on the claimed pages.
        on_pages = "".join(reader.stream(p) for p in claimed if 1 <= p <= reader.page_count)
        if any(word not in on_pages for word in _clean(chunk["text"]).split()):
            words_bad.append(chunk["chunk_id"])

        # 3. One chapter only.
        if layout.chapter_source == RUNNING_HEADER:
            if any(has_body.get(p) and header_of.get(p) != chunk["chapter"] for p in claimed):
                chapter_bad.append(chunk["chunk_id"])
        elif layout.chapter_source == HEADING:
            later_lines = [line.strip() for line in chunk["text"].split("\n")[1:]]
            if any(line in chapter_titles and line != chunk["chapter"] for line in later_lines):
                chapter_bad.append(chunk["chunk_id"])

    total = len(chunks)
    chunk_summary = {
        "total": total,
        "source": sum(1 for c in chunks if c.get("kind") != "apparatus"),
        "apparatus": sum(1 for c in chunks if c.get("kind") == "apparatus"),
        "page_labels_match_the_pdf": _ratio(total - len(label_bad), total, label_bad),
        "words_on_claimed_pages": _ratio(total - len(words_bad), total, words_bad),
        "within_one_chapter": (
            _ratio(total - len(chapter_bad), total, chapter_bad)
            if layout.chapter_source is not None
            else {"n": None, "N": total, "failing": [], "note": "no chapter structure to check against"}
        ),
    }

    # --- columns (PLAN_V7 §5) ---------------------------------------------------------
    # Not a hard stop: the words of such a passage are on its pages, but their order may
    # not be the reader's. The researcher is told which pages to read before citing.
    unclear = layout_module.unclear_column_pages(layout_module.read_blocks(pdf_path), layout) if layout.columns == 2 else []
    columns = {"count": layout.columns, "pages_where_reading_order_is_unclear": unclear}

    hard_stops = []
    if not with_text:
        hard_stops.append("The PDF has no text layer.")
    if words_bad:
        hard_stops.append(
            f"{len(words_bad)} of {total} passages contain words that are not on the pages they "
            "claim. A citation of such a passage would be false."
        )

    return {
        "pages": page_summary,
        "chapters": {
            "source": layout.chapter_source,
            "names": sorted(chapter_titles),
            "count": len(chapter_titles),
        },
        "labels_printed_on_their_page": labels,
        "label_sequence": sequence,
        "chunks": chunk_summary,
        "columns": columns,
        "hard_stops": hard_stops,
    }


def format_report(result: dict) -> str:
    """Plain-text audit report: counts, page numbers and chunk ids only."""
    pages, chunks = result["pages"], result["chunks"]
    out = []

    def listed(values: list, limit: int = 12) -> str:
        if not values:
            return "none"
        shown = ", ".join(str(v) for v in values[:limit])
        return shown + (f", … ({len(values)} in all)" if len(values) > limit else "")

    def check(name: str, ratio: dict) -> None:
        if ratio.get("n") is None:
            out.append(f"  {name:<34} not checked — {ratio.get('note', '')}")
            return
        out.append(f"  {name:<34} {ratio['n']}/{ratio['N']}")
        if ratio["failing"]:
            out.append(f"      failing: {listed(ratio['failing'], 6)}")

    out.append("PAGES")
    out.append(f"  in the PDF                         {pages['total']}")
    out.append(f"  with text                          {pages['with_text']}")
    out.append(f"  with body text                     {pages['with_body_text']}")
    out.append(f"  with a printed page number         {pages['with_printed_number']}/{pages['with_body_text']}")
    out.append(f"  without one (PDF pages)            {listed(pages['without_printed_number'])}")
    out.append(f"  text but no body text (PDF pages)  {listed(pages['text_but_no_body'])}")
    out.append("")
    out.append(f"CHAPTERS — carried by: {result['chapters']['source'] or 'nothing found'}")
    out.append(f"  found                              {result['chapters']['count']}")
    out.append("")
    out.append("PAGE LABELS")
    check("printed on their own page", result["labels_printed_on_their_page"])
    sequence = result["label_sequence"]
    out.append(
        f"  {'in step with the PDF pages':<34} "
        f"{sequence['steps_checked'] - len(sequence['breaks'])}/{sequence['steps_checked']}"
    )
    if sequence["breaks"]:
        out.append(
            "      breaks after PDF pages: " + listed([b["from_pdf_page"] for b in sequence["breaks"]])
        )
    out.append("")
    out.append(
        f"PASSAGES — {chunks['total']} ({chunks['source']} source, {chunks['apparatus']} reference apparatus)"
    )
    check("page labels match the PDF", chunks["page_labels_match_the_pdf"])
    check("every word on the claimed pages", chunks["words_on_claimed_pages"])
    check("stay inside one chapter", chunks["within_one_chapter"])
    out.append("")
    columns = result.get("columns")            # absent from audits made before articles could be ingested
    if columns and columns["count"] == 2:
        unclear = columns["pages_where_reading_order_is_unclear"]
        out.append("COLUMNS — two, read down the left and then the right")
        out.append(f"  pages where the order is unclear   {listed(unclear)}")
        if unclear:
            out.append("      read the passages from these pages against the PDF before citing them")
        out.append("")
    if result["hard_stops"]:
        out.append("CANNOT BE APPROVED")
        out.extend(f"  ✗ {reason}" for reason in result["hard_stops"])
    else:
        out.append("Nothing here blocks approval. Whether it is good enough is your decision.")
    return "\n".join(out)
