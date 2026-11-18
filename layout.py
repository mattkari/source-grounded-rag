"""Measure a thesis PDF's layout profile — PLAN_V4 §7.

This reproduces in code the manual pass that ADR 0001 describes: a census of
type sizes and faces, an analysis of where furniture (running header, page
number) sits, and a decision about which printed feature carries the chapter.
It reads only what the document prints.

Three rules hold throughout:

  * Every value comes back **with its evidence** — how many pages, which
    positions, how many characters — so the review report can show why.
  * A value that cannot be measured is **None and flagged**, never defaulted
    (hard rule 6). The extractor reads nothing from a None value.
  * When a choice is ambiguous the measurement takes the reading that invents
    less structure. A missed heading costs a coarser section label; an invented
    one puts a false title on a citation.

The cut-offs below are calibrated, not derived. They are recorded with their
justification in docs/decisions/0003-automatic-layout-measurement.md and must
be re-examined whenever a real thesis is measured wrongly.

Nothing here writes to disk or calls a model.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import median

import pymupdf

from documents import HEADING, RUNNING_HEADER, LayoutProfile

# --- calibrated cut-offs (ADR 0003) -----------------------------------------
# Furniture (a running header, a page number) must be found on at least this
# share of the pages that carry text before a band is declared.
FURNITURE_PAGE_SHARE = 0.5
# Furniture is the same line at the same height on neighbouring pages; "the
# same height" allows this many points of drift.
POSITION_TOLERANCE = 2.0
# A height counts as a furniture position only if furniture sits there on at
# least this share of the pages (and never on fewer than two).
POSITION_PAGE_SHARE = 0.02
# A lone page label is one line; a running header may wrap onto a second or
# third. Heights are in multiples of the block's own type size.
SINGLE_LINE = 2.2
HEADER_MAX_LINES = 3.6
# Furniture lines at one edge are stacked: the next one starts within this
# many line-heights of the one before.
FURNITURE_LINE_GAP = 1.6
# Page labels are accepted only if, on consecutive numbered pages, the label
# advances in step with the PDF page at least this often.
SEQUENCE_CONSISTENCY = 0.9
# Text set at least this many points above body size is a heading, whatever
# its face.
HEADING_SIZE_STEP = 1.0
# A heading size, or a bold face at body size, must appear on at least this
# many pages to be treated as part of the document's structure.
RECURRING_PAGES = 3
# A sub-body size is footnote apparatus when at least this share of its blocks
# sit at the foot of the column, below the last body-size text on the page.
FOOT_SHARE = 0.8
# A size below body that carries less than this share of the text is not
# running prose (table and figure text, labels) and is read as apparatus.
MINOR_SIZE_SHARE = 0.05
# A footnote opens with a numeral no larger than this fraction of its own size.
MARKER_SIZE_RATIO = 0.75
# A running header carries the chapter only if it changes: at least this many
# different headers, each typically printed on at least two consecutive pages.
MIN_DISTINCT_HEADERS = 2
MIN_MEDIAN_HEADER_RUN = 2
# Calibrated on real articles (ADR 0015). A journal justifies its lines by scaling them, so
# body text is set at sizes a hair apart (8.1 to 8.4pt for "8.2"). A size within this
# fraction of the body size is the body size itself when at least `NEAR_BODY_IN_BLOCK` of
# its characters sit inside blocks of body text.
NEAR_BODY = 0.05
NEAR_BODY_IN_BLOCK = 0.8
# Chapter titles that mark reference apparatus rather than the author's claims.
APPARATUS_TITLES = ("bibliography", "references", "reference list", "works cited", "list of references")

ROMAN_RE = re.compile(r"^[ivxlcdm]+$")
ARABIC_RE = re.compile(r"^\d{1,4}$")
_STYLE_SUFFIX = re.compile(r"(MT|PS)$")


@dataclass
class Block:
    pdf_page: int
    y0: float
    y1: float
    x0: float
    spans: list[dict]          # {"text", "font", "size", "bold"}
    text: str
    x1: float = 0.0

    @property
    def lead(self) -> dict:
        return self.spans[0]

    @property
    def label(self) -> str | None:
        """A page label printed in this block, if one opens or closes it."""
        for span in (self.spans[-1], self.spans[0]):
            if is_page_label(span["text"]):
                return _normalise(span["text"])
        return None

    @property
    def key(self) -> str:
        """The block's text without any page label — what a running header
        repeats from page to page even when the page number shares its line."""
        return _normalise(" ".join(s["text"] for s in self.spans if not is_page_label(s["text"])))

    @property
    def height_in_lines(self) -> float:
        return (self.y1 - self.y0) / max(span["size"] for span in self.spans)

    def dominant_size(self) -> float:
        sizes: Counter[float] = Counter()
        for span in self.spans:
            sizes[span["size"]] += len(span["text"].strip())
        return sizes.most_common(1)[0][0]


@dataclass
class Measurement:
    layout: LayoutProfile | None
    evidence: dict = field(default_factory=dict)   # profile value -> how it was reached
    flags: list[str] = field(default_factory=list) # what could not be measured, and its cost
    pages_total: int = 0
    pages_with_text: int = 0


def _normalise(text: str) -> str:
    text = text.replace("\xad", "").replace(" ", " ").replace("\t", " ").replace("\r", " ")
    return re.sub(r"\s{2,}", " ", text).strip()


def near_body(size: float, body_size: float) -> bool:
    """Whether a size is the body size, give or take the scaling of a justified line."""
    return abs(size - body_size) <= NEAR_BODY * body_size


def upright(line: dict) -> bool:
    """A line set left to right. Text turned on its side (a repository's stamp in the
    margin) is not part of what a reader reads down the page."""
    direction = line.get("dir") or (1.0, 0.0)
    return abs(direction[0] - 1.0) < 0.01 and abs(direction[1]) < 0.01


_FURNITURE_EDGES = " |·•–—-,:"


def edge_numbers(text: str) -> list[str]:
    """Arabic numbers standing at the start or the end of a line of furniture: where a
    journal prints the page number beside its name."""
    tokens = _normalise(text).replace("|", " | ").split()
    found = [token for token in (tokens[:1] + tokens[-1:] if len(tokens) > 1 else tokens) if ARABIC_RE.match(token)]
    return list(dict.fromkeys(found))


def furniture_key(text: str) -> str:
    """A line of furniture without the numbers at its ends, so that "584 | Journal" and
    "586 | Journal" are seen to be the same line."""
    tokens = _normalise(text).replace("|", " | ").split()
    if len(tokens) > 1 and ARABIC_RE.match(tokens[0]):
        tokens = tokens[1:]
    if len(tokens) > 1 and ARABIC_RE.match(tokens[-1]):
        tokens = tokens[:-1]
    return " ".join(tokens).strip(_FURNITURE_EDGES)


def is_page_label(text: str) -> bool:
    token = _normalise(text).lower()
    return bool(ARABIC_RE.match(token) or ROMAN_RE.match(token))


def font_family(font: str) -> str:
    """"TimesNewRomanPS-BoldMT" and "TimesNewRomanPSMT" -> "TimesNewRomanPS"."""
    name = font.split("+", 1)[-1]            # drop a subset prefix such as "ABCDEF+"
    name = re.split(r"[-,]", name, maxsplit=1)[0]
    previous = None
    while previous != name:
        previous = name
        name = _STYLE_SUFFIX.sub("", name)
    return name


def read_blocks(pdf_path) -> list[list[Block]]:
    """Every text block of every page, in the order the extractor reads them."""
    doc = pymupdf.open(pdf_path)
    pages: list[list[Block]] = []
    for index in range(doc.page_count):
        raw = [b for b in doc[index].get_text("dict")["blocks"] if b["type"] == 0]
        raw.sort(key=lambda b: (round(b["bbox"][1], 1), round(b["bbox"][0], 1)))
        blocks: list[Block] = []
        for block in raw:
            spans = [
                {
                    "text": s["text"],
                    "font": s["font"],
                    "size": round(s["size"], 1),
                    "bold": bool(s["flags"] & 16) or "bold" in s["font"].lower(),
                }
                for line in block["lines"]
                if upright(line)
                for s in line["spans"]
                if s["text"].strip()
            ]
            if spans:
                blocks.append(
                    Block(
                        pdf_page=index + 1,
                        y0=block["bbox"][1],
                        y1=block["bbox"][3],
                        x0=block["bbox"][0],
                        x1=block["bbox"][2],
                        spans=spans,
                        text=_normalise(" ".join(s["text"] for s in spans)),
                    )
                )
        pages.append(blocks)
    return pages


# ---------------------------------------------------------------------------
# Census
# ---------------------------------------------------------------------------


def _body_size(pages: list[list[Block]]) -> tuple[float | None, dict]:
    chars: Counter[float] = Counter()
    fonts: Counter[tuple[str, float]] = Counter()
    for blocks in pages:
        for block in blocks:
            for span in block.spans:
                count = len(span["text"].strip())
                chars[span["size"]] += count
                fonts[(span["font"], span["size"])] += count
    if not chars:
        return None, {}
    size, count = chars.most_common(1)[0]
    total = sum(chars.values())
    body_font = max(
        ((font, n) for (font, s), n in fonts.items() if s == size), key=lambda pair: pair[1]
    )[0]
    return size, {
        "rule": "the type size carrying the most characters",
        "characters_at_this_size": count,
        "characters_total": total,
        "body_font": body_font,
        "sizes_by_characters": {str(s): n for s, n in chars.most_common(8)},
    }


# ---------------------------------------------------------------------------
# Bands: where the furniture sits
# ---------------------------------------------------------------------------


def _repeats_on_neighbour(block: Block, neighbours: list[list[Block]]) -> bool:
    """The same line, at the same height, on a neighbouring page. "The same" allows a
    number at either end to differ: that is where a journal prints its page number."""
    mine = furniture_key(block.key)
    return any(
        (other.key == block.key or (mine and furniture_key(other.key) == mine))
        and abs(other.y0 - block.y0) <= POSITION_TOLERANCE
        for blocks in neighbours
        for other in blocks
    )


def _is_furniture(block: Block, neighbours: list[list[Block]]) -> bool:
    if not block.key:  # nothing but a page label
        return block.label is not None and block.height_in_lines < SINGLE_LINE
    return block.height_in_lines < HEADER_MAX_LINES and _repeats_on_neighbour(block, neighbours)


def _furniture(pages: list[list[Block]], *, top: bool) -> list[Block]:
    """Furniture at one edge of the page: page labels, and short lines that the
    neighbouring page prints again at the same height.

    Each page is read inward from the edge. The scan stops at the first block
    that is not furniture, and at the first gap: a wrapped header's second line
    sits directly under its first, whereas a heading that happens to repeat on
    the next page sits further down, in the text column.
    """
    found: list[Block] = []
    for index, blocks in enumerate(pages):
        # The page before and after, and the next of the same side: a journal sets its
        # running head on left-hand pages only, and its footer on alternate sides.
        neighbours = [pages[i] for i in (index - 1, index + 1, index - 2, index + 2) if 0 <= i < len(pages)]
        ordered = sorted(blocks, key=lambda b: b.y0, reverse=not top)
        previous: Block | None = None
        for block in ordered:
            if previous is not None:
                gap = abs(block.y0 - previous.y0)
                if gap > FURNITURE_LINE_GAP * max(span["size"] for span in previous.spans):
                    break
            if not _is_furniture(block, neighbours):
                break
            found.append(block)
            previous = block
    return found


def _recurring_positions(furniture: list[Block], text_pages: int) -> dict[int, int]:
    """Heights at which furniture recurs. A lone label that happens to sit at a
    page edge once (a chapter number on a divider page) is not a position."""
    counts = Counter(round(block.y0) for block in furniture)
    needed = max(2, POSITION_PAGE_SHARE * text_pages)
    return {y: n for y, n in counts.items() if n >= needed}


def _label_sequence(labelled: list[tuple[int, str]]) -> tuple[int, int]:
    """(consistent steps, steps checked) between consecutive arabic-numbered pages."""
    arabic = [(pdf, int(label)) for pdf, label in labelled if label.isdecimal()]
    steps = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(arabic, arabic[1:])]
    return sum(1 for pdf_step, label_step in steps if pdf_step == label_step), len(steps)


def _inline_page_numbers(furniture: list[Block], text_pages: int) -> tuple[int | None, dict]:
    """Page numbers printed inside a line of furniture ("584 | Journal | Vol 12").

    Every number at an end of such a line is a candidate. The page number is the one
    that keeps a constant distance from the PDF page: the offset shared by the most
    pages. It is accepted when at least half the pages with text agree on it, and never
    on fewer than three. Pages that do not agree (a form appended with its own
    numbering) simply get no label: the extractor takes a number only where it equals
    the PDF page plus this offset.
    """
    by_page: dict[int, set[int]] = {}
    for block in furniture:
        for token in edge_numbers(block.text):
            by_page.setdefault(block.pdf_page, set()).add(int(token) - block.pdf_page)
    offsets = Counter(offset for found in by_page.values() for offset in found)
    if not offsets:
        return None, {}
    offset, agreeing = offsets.most_common(1)[0]
    detail = {
        "rule": "a number at an end of a furniture line that keeps a constant distance from the PDF page",
        "pages_with_a_candidate": len(by_page), "pages_agreeing": agreeing,
        "pages_with_text": text_pages, "printed_minus_pdf_page": offset,
    }
    accepted = agreeing >= max(RECURRING_PAGES, FURNITURE_PAGE_SHARE * text_pages)
    return (offset if accepted else None), detail


def _on_enough_pages(with_furniture: set[int], pages: list[list[Block]]) -> bool:
    """Furniture is on enough pages when it is on half of all pages with text, or on
    half of the left-hand pages, or of the right-hand ones (never fewer than three)."""
    with_text = {index + 1 for index, blocks in enumerate(pages) if blocks}
    if len(with_furniture) >= FURNITURE_PAGE_SHARE * len(with_text):
        return True
    for parity in (0, 1):
        side = {page for page in with_text if page % 2 == parity}
        found = {page for page in with_furniture if page % 2 == parity}
        if len(found) >= RECURRING_PAGES and len(found) >= FURNITURE_PAGE_SHARE * len(side):
            return True
    return False


def _measure_bands(pages: list[list[Block]], text_pages: int, evidence: dict, flags: list[str]):
    """Return (header_band_y, footnote_band_y, page_number_band, page_label_offset).
    The offset is set only when the page number shares its line with other furniture."""
    header_band_y = footnote_band_y = page_number_band = None
    page_label_offset = None
    needed = FURNITURE_PAGE_SHARE * text_pages

    # --- top of the page -----------------------------------------------------
    top = _furniture(pages, top=True)
    top_positions = _recurring_positions(top, text_pages)
    top = [b for b in top if round(b.y0) in top_positions]
    top_pages = len({b.pdf_page for b in top})
    top_labels = [b for b in top if b.label is not None]
    if _on_enough_pages({b.pdf_page for b in top}, pages):
        limit = max(top_positions) + POSITION_TOLERANCE
        below = [b.y0 for blocks in pages for b in blocks if b.y0 > limit]
        if below:
            header_band_y = round((max(b.y0 for b in top) + min(below)) / 2, 1)
            evidence["header_band_y"] = {
                "rule": "midway between the lowest running-header line and the highest other text",
                "pages_with_header_furniture": top_pages,
                "pages_with_text": text_pages,
                "header_lines_start_at_y": {str(y): n for y, n in sorted(top_positions.items())},
                "other_text_starts_at_or_below_y": round(min(below), 1),
            }
    if header_band_y is None:
        evidence["header_band_y"] = {
            "rule": "no line recurs at the top of consecutive pages on enough pages",
            "pages_with_header_furniture": top_pages,
            "pages_with_text": text_pages,
        }

    # --- bottom of the page ----------------------------------------------------
    bottom = _furniture(pages, top=False)
    bottom_positions = _recurring_positions(bottom, text_pages)
    bottom = [b for b in bottom if round(b.y0) in bottom_positions]
    bottom_pages = len({b.pdf_page for b in bottom})
    bottom_labels = [b for b in bottom if b.label is not None]
    if _on_enough_pages({b.pdf_page for b in bottom}, pages):
        limit = min(bottom_positions) - POSITION_TOLERANCE
        above = [b.y0 for blocks in pages for b in blocks if b.y0 < limit]
        if above:
            footnote_band_y = round((max(above) + min(b.y0 for b in bottom)) / 2, 1)
            evidence["footnote_band_y"] = {
                "rule": "midway between the lowest other text and the highest footer line",
                "pages_with_footer_furniture": bottom_pages,
                "pages_with_text": text_pages,
                "footer_lines_start_at_y": {str(y): n for y, n in sorted(bottom_positions.items())},
                "other_text_starts_at_or_above_y": round(max(above), 1),
            }
    if footnote_band_y is None:
        evidence["footnote_band_y"] = {
            "rule": "no page label or repeated line recurs at the foot of enough pages",
            "pages_with_footer_furniture": bottom_pages,
            "pages_with_text": text_pages,
        }

    # --- the page number ---------------------------------------------------------
    candidates = []
    if footnote_band_y is not None and len({b.pdf_page for b in bottom_labels}) >= needed:
        candidates.append(("footer", bottom_labels))
    if header_band_y is not None and len({b.pdf_page for b in top_labels}) >= needed:
        candidates.append(("header", top_labels))
    for band, labels in candidates:
        consistent, checked = _label_sequence([(b.pdf_page, b.label.lower()) for b in labels])
        detail = {
            "rule": "a lone roman or arabic token at the page edge, in step with the PDF page",
            "band": band,
            "pages_with_a_label": len({b.pdf_page for b in labels}),
            "pages_with_text": text_pages,
            "consistent_steps": consistent,
            "steps_checked": checked,
        }
        if checked == 0 or consistent / checked >= SEQUENCE_CONSISTENCY:
            page_number_band = band
            evidence["page_number_band"] = detail
            break
        evidence["page_number_band"] = {**detail, "rejected": "labels do not advance with the pages"}
    if page_number_band is None:
        # No lone label: look for a number inside a line of furniture (ADR 0015).
        for band, furniture in (("footer", bottom if footnote_band_y is not None else []),
                                ("header", top if header_band_y is not None else [])):
            offset, detail = _inline_page_numbers(furniture, text_pages)
            if offset is not None:
                page_number_band, page_label_offset = band, offset
                evidence["page_number_band"] = {**detail, "band": band}
                break
    if page_number_band is None:
        evidence.setdefault(
            "page_number_band",
            {"rule": "no lone page label recurs at either edge of enough pages"},
        )
        flags.append(
            "No printed page number was found. Every citation of this document will read "
            "'PDF p. N [VERIFY]' instead of a page number."
        )
    return header_band_y, footnote_band_y, page_number_band, page_label_offset


def _in_zone(block: Block, header_band_y, footnote_band_y) -> bool:
    if header_band_y is not None and block.y0 < header_band_y:
        return False
    if footnote_band_y is not None and block.y0 > footnote_band_y:
        return False
    return True


# ---------------------------------------------------------------------------
# Sizes below and above body
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Columns (PLAN_V7 §5)
# ---------------------------------------------------------------------------

# A document is read as two columns when at least this share of its pages with body
# text set two blocks of it side by side.
COLUMN_PAGE_SHARE = 0.5
# Shorter blocks are table cells and labels, not a column of prose.
MIN_COLUMN_CHARS = 80
# How far past the split, in points, a block must reach on both sides to lie across it.
COLUMN_GUTTER = 6.0


def column_of(x0: float, x1: float, split_x: float | None) -> int:
    return 0 if split_x is None or (x0 + x1) / 2 < split_x else 1


def lies_across(x0: float, x1: float, split_x: float) -> bool:
    return x0 < split_x - COLUMN_GUTTER and x1 > split_x + COLUMN_GUTTER


def _page_split(blocks: list[Block], body_size: float) -> tuple[float | None, bool]:
    """The x between two columns of body text on one page, and whether the page is
    regular. (None, True) is a page in one column. (None, False) is a page whose
    side-by-side text does not divide at one x: three columns, or something else."""
    prose = [b for b in blocks if near_body(b.dominant_size(), body_size) and len(b.text) >= MIN_COLUMN_CHARS]
    pairs = [(left, right) for left in prose for right in prose
             if left.x1 < right.x0 and min(left.y1, right.y1) > max(left.y0, right.y0)]
    if not pairs:
        return None, True
    left_edge, right_edge = max(left.x1 for left, _ in pairs), min(right.x0 for _, right in pairs)
    if left_edge >= right_edge:
        return None, False
    return (left_edge + right_edge) / 2, True


def _columns(zone_pages: list[list[Block]], body_size: float, evidence: dict, flags: list[str]):
    """How many columns the body text is set in: 1 or 2, and where 2 divide."""
    with_body = [blocks for blocks in zone_pages if any(near_body(b.dominant_size(), body_size) for b in blocks)]
    splits, irregular = [], []
    for blocks in with_body:
        split, regular = _page_split(blocks, body_size)
        if split is not None:
            splits.append(split)
        elif not regular:
            irregular.append(blocks[0].pdf_page)
    share = len(splits) / len(with_body) if with_body else 0.0
    two = share >= COLUMN_PAGE_SHARE
    split_x = round(sorted(splits)[len(splits) // 2], 1) if two else None
    evidence["columns"] = {
        "rule": f"two columns if at least {COLUMN_PAGE_SHARE:.0%} of pages with body text set blocks of it side by side",
        "pages_with_body_text": len(with_body),
        "pages_set_side_by_side": len(splits),
        "pages_set_in_some_other_arrangement": irregular,
        "split_x": split_x,
    }
    if irregular:
        flags.append(
            f"{len(irregular)} page(s) set text side by side in a way that does not divide into two columns "
            f"(PDF page {', '.join(map(str, irregular[:8]))}{'…' if len(irregular) > 8 else ''}). "
            "The reading order on those pages may be wrong; read the passages from them before citing."
        )
    return (2 if two else 1), split_x


def _is_body_block(block: Block, body_size: float) -> bool:
    """A block of body text: its commonest size is the body size, or a hair above it."""
    return body_size <= block.dominant_size() <= body_size * (1 + NEAR_BODY)


def last_body_row(blocks: list[Block], body_size: float, block: Block, split_x: float | None) -> float | None:
    """The top of the last body-size block in the same column as `block`: what a
    footnote sits below. None when that column has no body text on the page."""
    column = column_of(block.x0, block.x1, split_x)
    rows = [b.y0 for b in blocks if _is_body_block(b, body_size) and column_of(b.x0, b.x1, split_x) == column]
    return max(rows) if rows else None


def unclear_column_pages(pages: list[list[Block]], profile: LayoutProfile) -> list[int]:
    """PDF pages of a two-column document whose reading order cannot be established:
    a block lies across the split while other text sits beside it. A title or an
    abstract across both columns, with nothing beside it, is not unclear."""
    if profile.columns != 2 or profile.column_split_x is None:
        return []
    unclear = []
    for blocks in pages:
        zone = [b for b in blocks if _in_zone(b, profile.header_band_y, profile.footnote_band_y)
                and b.dominant_size() >= profile.body_min_size]
        for block in zone:
            if lies_across(block.x0, block.x1, profile.column_split_x) and any(
                    other is not block and min(other.y1, block.y1) - max(other.y0, block.y0) > 1.0 for other in zone):
                unclear.append(block.pdf_page)
                break
    return unclear


def _is_marker_led(block: Block) -> bool:
    """A footnote's shape: it opens with a numeral set well below its own size."""
    lead = block.lead
    return lead["text"].strip().isdigit() and lead["size"] <= MARKER_SIZE_RATIO * block.dominant_size()


def _body_min_size(zone_pages: list[list[Block]], body_size: float, evidence: dict, flags: list[str],
                   split_x: float | None = None) -> float:
    """The smallest size still read as body text.

    The extractor separates body from apparatus by type size alone, so the
    question for each size below body is which side of that line it falls on:

      * a size carrying only a sliver of the text is apparatus (table and
        figure text, stray labels);
      * a size whose blocks nearly all sit at the foot of the column, below the
        last body-size text on the page, is footnote apparatus;
      * anything else is body text set smaller — block quotations.

    When footnotes share a size with block quotations the two cannot be told
    apart by size. They are then kept, and that is flagged with a count.
    """
    chars: Counter[float] = Counter()
    at_foot: Counter[float] = Counter()
    blocks_seen: Counter[float] = Counter()
    footnote_shaped: Counter[float] = Counter()
    footnote_pages: dict[float, set[int]] = {}
    in_body_blocks: Counter[float] = Counter()
    for blocks in zone_pages:
        for block in blocks:
            for span in block.spans:
                chars[span["size"]] += len(span["text"].strip())
                if _is_body_block(block, body_size):
                    in_body_blocks[span["size"]] += len(span["text"].strip())
        if not any(_is_body_block(b, body_size) for b in blocks):
            continue  # nothing to be "below" on this page
        for block in blocks:
            size = block.dominant_size()
            if size < body_size:
                # In two columns a footnote sits at the foot of its own column.
                last_body = last_body_row(blocks, body_size, block, split_x)
                if last_body is None:
                    continue
                blocks_seen[size] += 1
                if block.y0 > last_body:
                    at_foot[size] += 1
                    if _is_marker_led(block):
                        footnote_shaped[size] += 1
                        footnote_pages.setdefault(size, set()).add(block.pdf_page)

    total_chars = sum(chars.values()) or 1
    detail = {}
    body_min = body_size
    for size in sorted((s for s in chars if s < body_size), reverse=True):
        share = chars[size] / total_chars
        foot_share = at_foot[size] / blocks_seen[size] if blocks_seen[size] else 0.0
        inside = in_body_blocks[size] / chars[size] if chars[size] else 0.0
        if near_body(size, body_size) and inside >= NEAR_BODY_IN_BLOCK:
            # Lines of the body text itself, scaled a little to justify them (ADR 0015).
            reading = "body text"
        elif near_body(size, body_size):
            # As close to the body size, but not inside the body text: figure panel
            # letters, furniture, an appended form. Not running prose.
            reading = "apparatus (close to the body size, but set apart from the body text)"
        elif share < MINOR_SIZE_SHARE:
            reading = "apparatus (too little text to be running prose)"
        elif foot_share >= FOOT_SHARE:
            reading = "footnote apparatus (sits at the foot of the column)"
        else:
            reading = "body text"
        detail[str(size)] = {
            "share_of_characters": round(share, 4),
            "blocks_on_pages_with_body_text": blocks_seen[size],
            "of_which_at_the_foot_of_the_column": at_foot[size],
            "of_which_open_with_a_footnote_numeral": footnote_shaped[size],
            "share_inside_blocks_of_body_text": round(inside, 3),
            "read_as": reading,
        }
        if reading != "body text":
            break  # the extractor has one threshold: everything smaller goes too
        body_min = size
        if footnote_shaped[size]:
            flags.append(
                f"Footnotes appear to share a type size ({size:g}pt) with block quotations: "
                f"{footnote_shaped[size]} blocks on {len(footnote_pages[size])} pages open with a "
                "footnote numeral at the foot of the column. They cannot be separated by size, "
                "so footnote text is kept and can be cited as if it were body text."
            )
    evidence["body_min_size"] = {
        "rule": "the smallest size carrying running prose that is not confined to the foot of the column",
        "sizes_below_body": detail,
    }
    return body_min


def _headings(zone_pages: list[list[Block]], body_size: float, body_font: str, evidence: dict, flags: list[str]):
    """Return (heading_min_size, heading_fonts, chapter_min, section_min, chapter_tier_pages)."""
    heading_min_size = body_size + HEADING_SIZE_STEP

    size_pages: dict[float, set[int]] = {}
    face_pages: dict[str, set[int]] = {}
    for blocks in zone_pages:
        for block in blocks:
            lead = block.lead
            if lead["size"] >= heading_min_size:
                size_pages.setdefault(lead["size"], set()).add(block.pdf_page)
            elif lead["bold"] and lead["size"] >= body_size:
                face_pages.setdefault(lead["font"], set()).add(block.pdf_page)

    evidence["heading_min_size"] = {
        "rule": f"body size plus {HEADING_SIZE_STEP:g} point",
        "sizes_at_or_above_it": {str(s): len(p) for s, p in sorted(size_pages.items())},
    }

    # Bold at body size: only the body family's own bold, and only if it recurs.
    family = font_family(body_font)
    recurring = {face: pages for face, pages in face_pages.items() if len(pages) >= RECURRING_PAGES}
    adopted = tuple(sorted(face for face in recurring if font_family(face) == family))
    passed_over = {face: len(pages) for face, pages in recurring.items() if face not in adopted}
    evidence["heading_fonts"] = {
        "rule": "bold faces of the body family that open a block at body size on several pages",
        "body_family": family,
        "adopted": {face: len(recurring[face]) for face in adopted},
        "bold_faces_not_adopted": passed_over,
    }
    if passed_over:
        names = ", ".join(f"{face} ({count} pages)" for face, count in sorted(passed_over.items()))
        flags.append(
            f"Bold text in another face opens blocks at body size: {names}. It was not treated "
            "as headings, so any sub-headings set in it are read as ordinary text."
        )

    # Size tiers: the largest recurring heading size is the chapter tier.
    tiers = sorted((s for s, pages in size_pages.items() if len(pages) >= RECURRING_PAGES), reverse=True)
    if tiers:
        chapter_min = tiers[0]
        section_min = tiers[1] if len(tiers) > 1 else tiers[0]
    else:
        # No recurring heading size: nothing reaches level 1 or 2 by size.
        chapter_min = section_min = max(size_pages, default=heading_min_size) + HEADING_SIZE_STEP
    evidence["heading_tiers"] = {
        "rule": "the largest heading size that recurs is the chapter tier, the next the section tier",
        "recurring_heading_sizes": {str(s): len(size_pages[s]) for s in tiers},
        "chapter_heading_min_size": chapter_min,
        "section_heading_min_size": section_min,
    }
    chapter_pages = len(size_pages.get(tiers[0], ())) if tiers else 0
    return heading_min_size, adopted, chapter_min, section_min, chapter_pages


# ---------------------------------------------------------------------------
# Which printed feature carries the chapter
# ---------------------------------------------------------------------------


def _chapter_source(pages, header_band_y, text_pages, chapter_tier_pages, evidence, flags) -> str | None:
    headers: list[str] = []
    if header_band_y is not None:
        for blocks in pages:
            if not blocks:
                continue
            parts = [b.key for b in blocks if b.y0 < header_band_y and b.key]
            headers.append(" ".join(parts))
    printed = [h for h in headers if h]

    runs: list[int] = []
    previous = None
    for header in printed:
        if header == previous:
            runs[-1] += 1
        else:
            runs.append(1)
            previous = header
    distinct = len(set(printed))
    detail = {
        "pages_with_a_running_header": len(printed),
        "pages_with_text": text_pages,
        "distinct_headers": distinct,
        "median_pages_per_header": median(runs) if runs else 0,
        "pages_with_a_chapter_size_heading": chapter_tier_pages,
    }

    if (
        len(printed) >= FURNITURE_PAGE_SHARE * text_pages
        and distinct >= MIN_DISTINCT_HEADERS
        and median(runs) >= MIN_MEDIAN_HEADER_RUN
    ):
        evidence["chapter_source"] = {
            "rule": "a running header that changes from chapter to chapter",
            **detail,
        }
        return RUNNING_HEADER

    if chapter_tier_pages >= RECURRING_PAGES:
        evidence["chapter_source"] = {
            "rule": "no chapter-bearing running header; chapters open with a recurring large heading",
            **detail,
        }
        return HEADING

    evidence["chapter_source"] = {
        "rule": "neither a changing running header nor a recurring chapter-size heading was found",
        **detail,
    }
    flags.append(
        "No chapter structure was found. Passages will carry no chapter, and citations will "
        "name the section (if any) and page only."
    )
    return None


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


def measure(pdf_path) -> Measurement:
    """Derive a layout profile from a PDF. Apparatus chapters are filled in
    afterwards, once the chapters are known (see `apparatus_prefixes`)."""
    pages = read_blocks(pdf_path)
    text_pages = sum(1 for blocks in pages if blocks)
    evidence: dict = {}
    flags: list[str] = []

    body_size, body_evidence = _body_size(pages)
    if body_size is None:
        return Measurement(
            layout=None,
            evidence={},
            flags=["The PDF has no text layer, so there is nothing to measure."],
            pages_total=len(pages),
            pages_with_text=0,
        )
    evidence["body_size"] = body_evidence

    header_band_y, footnote_band_y, page_number_band, page_label_offset = _measure_bands(
        pages, text_pages, evidence, flags)
    zone_pages = [
        [b for b in blocks if _in_zone(b, header_band_y, footnote_band_y)] for blocks in pages
    ]

    columns, split_x = _columns(zone_pages, body_size, evidence, flags)
    body_min_size = _body_min_size(zone_pages, body_size, evidence, flags, split_x)
    heading_min_size, heading_fonts, chapter_min, section_min, chapter_pages = _headings(
        zone_pages, body_size, body_evidence["body_font"], evidence, flags
    )
    chapter_source = _chapter_source(pages, header_band_y, text_pages, chapter_pages, evidence, flags)

    layout = LayoutProfile(
        body_size=body_size,
        body_min_size=body_min_size,
        header_band_y=header_band_y,
        footnote_band_y=footnote_band_y,
        page_number_band=page_number_band,
        heading_min_size=heading_min_size,
        heading_fonts=heading_fonts,
        chapter_heading_min_size=chapter_min,
        section_heading_min_size=section_min,
        chapter_source=chapter_source,
        apparatus_chapter_prefixes=(),
        columns=columns,
        column_split_x=split_x,
        page_number_inline=page_label_offset is not None,
        page_label_offset=page_label_offset,
    )
    return Measurement(layout, evidence, flags, pages_total=len(pages), pages_with_text=text_pages)


def apparatus_prefixes(chapters: list[str]) -> tuple[str, ...]:
    """Chapter titles, as printed, that mark a bibliography or reference list."""
    found = []
    for chapter in chapters:
        if chapter and chapter.strip().lower().startswith(APPARATUS_TITLES) and chapter not in found:
            found.append(chapter)
    return tuple(found)
