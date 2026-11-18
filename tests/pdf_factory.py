"""Synthetic thesis PDFs for the offline tests (PLAN_V4 §14).

Every word these files contain is invented and says so ("FIXTURE ..."). The
layout is what the tests control: type sizes, where the running header and the
page number sit, whether chapters are carried by the header or by a heading,
footnotes, block quotations.

Fonts are PDF base-14 faces, which PyMuPDF reports as "Times-Roman",
"Times-Bold", "Times-Italic" and "Helvetica-Bold".
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

ROMAN = ["i", "ii", "iii", "iv", "v", "vi"]
PAGE_WIDTH, PAGE_HEIGHT = 595, 842
LEFT = 90
HEADER_Y, FOOTER_Y = 42, 805        # text baselines
BODY_TOP = 90
WORDS = ["lighthouse", "orchard", "tramway", "harbour", "viaduct", "ledger", "canal", "beacon",
         "quarry", "meadow", "ferry", "granary", "willow", "anchor", "lantern", "bridge"]


@dataclass
class ThesisSpec:
    chapters: list[tuple[str, int]] = field(
        default_factory=lambda: [
            ("FIXTURE Chapter Alpha", 5),
            ("FIXTURE Chapter Beta", 5),
            ("FIXTURE Chapter Gamma", 5),
            ("Bibliography", 3),
        ]
    )
    body_size: float = 12.0
    header: str = "chapter"            # "chapter" | "constant" | "none"
    header_lines: int = 1              # 2 = a running header that wraps
    page_numbers: str = "footer"       # "footer" | "header" | "none" | "scrambled"
    chapter_heading_size: float | None = 18.0   # heading at each chapter opening; None = no heading
    section_headings: bool = True      # bold, body-size headings inside chapters
    other_face_headings: bool = False  # Helvetica-Bold sub-headings at body size
    quote_size: float | None = None    # a block quotation between paragraphs on body pages
    footnote_size: float | None = None # a footnote at the foot of body pages
    footnote_lines: int = 1            # more lines = footnotes carry more of the text
    front_pages: int = 2               # roman-numbered pages after the title page
    title_page: bool = True
    author_line: str | None = "By Fixture Author"
    year_line: str | None = "March, 2001"
    title: str = "FIXTURE Thesis On Synthetic Lighthouses"
    unnumbered: tuple[int, ...] = ()   # body page numbers whose printed number is left off
    divider_number: bool = False       # a lone "2" low on one page that is not a page number


def _sentence(seed: int) -> str:
    picks = [WORDS[(seed * 7 + i * 3) % len(WORDS)] for i in range(6)]
    return "FIXTURE the " + " and the ".join(picks[:3]) + " stood beside the " + picks[3] + "."


def _paragraph(page, y: float, size: float, seed: int, *, x: float = LEFT, lines: int = 3,
               font: str = "tiro", tag: str = "") -> float:
    """Write one paragraph as a single block; return the y below it."""
    leading = size * 1.25
    for line in range(lines):
        text = _sentence(seed * 10 + line)
        if line == 0 and tag:
            text = f"{tag} {text}"
        page.insert_text((x, y + line * leading), text, fontname=font, fontsize=size)
    return y + lines * leading + size * 1.4


def make_thesis(path, spec: ThesisSpec | None = None) -> dict:
    """Write the PDF and return what a correct extraction must find."""
    spec = spec or ThesisSpec()
    doc = pymupdf.open()
    expected = {"labels": {}, "headers": {}, "chapter_of": {}, "chapter_titles": []}
    pdf_page = 0

    def printed_header(header_text: str) -> str | None:
        """The running header as a correct extraction reads it."""
        if spec.header == "none":
            return None
        return header_text if spec.header_lines == 1 else f"{header_text} FIXTURE continued header"

    def furniture(page, header_text: str | None, label: str | None) -> None:
        if header_text and spec.header != "none":
            lines = [header_text] if spec.header_lines == 1 else [header_text, "FIXTURE continued header"]
            for index, line in enumerate(lines):
                page.insert_text((LEFT, HEADER_Y + index * 12), line, fontname="tiit", fontsize=10)
        if label is not None:
            if spec.page_numbers == "footer":
                page.insert_text((PAGE_WIDTH / 2, FOOTER_Y), label, fontname="tiro", fontsize=spec.body_size)
            elif spec.page_numbers == "header":
                page.insert_text((PAGE_WIDTH - 110, HEADER_Y), label, fontname="tiro", fontsize=10)

    # --- title page: no header, no number -----------------------------------------
    if spec.title_page:
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        pdf_page += 1
        page.insert_text((LEFT, 240), spec.title, fontname="tibo", fontsize=20)
        if spec.author_line:
            page.insert_text((LEFT, 340), spec.author_line, fontname="tiro", fontsize=12)
        page.insert_text((LEFT, 470), "FIXTURE thesis submitted to a synthetic university", fontname="tiro", fontsize=12)
        if spec.year_line:
            page.insert_text((LEFT, 700), spec.year_line, fontname="tiro", fontsize=12)
        expected["labels"][pdf_page] = None
        expected["headers"][pdf_page] = None

    # --- front matter: roman numerals ------------------------------------------------
    for index in range(spec.front_pages):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        pdf_page += 1
        header = spec.title if spec.header == "constant" else "FIXTURE Abstract"
        label = ROMAN[index] if spec.page_numbers in {"footer", "header"} else None
        furniture(page, header, label)
        y = BODY_TOP
        for paragraph in range(5):
            y = _paragraph(page, y, spec.body_size, 900 + index * 10 + paragraph, tag=f"frontword{index}")
        expected["labels"][pdf_page] = label
        expected["headers"][pdf_page] = printed_header(header)
        expected["chapter_of"][pdf_page] = printed_header(header) if spec.header == "chapter" else None

    # --- chapters -----------------------------------------------------------------------
    body_number = 0
    for chapter_index, (title, page_count) in enumerate(spec.chapters):
        expected["chapter_titles"].append(title)
        for page_in_chapter in range(page_count):
            page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            pdf_page += 1
            body_number += 1
            if spec.page_numbers == "scrambled":
                label = str((body_number * 37) % 91 + 1)
                page.insert_text((PAGE_WIDTH / 2, FOOTER_Y), label, fontname="tiro", fontsize=spec.body_size)
                label = None
            elif spec.page_numbers == "none" or body_number in spec.unnumbered:
                label = None
            else:
                label = str(body_number)
            header = spec.title if spec.header == "constant" else title
            furniture(page, header, label)
            expected["labels"][pdf_page] = label
            expected["headers"][pdf_page] = printed_header(header)
            expected["chapter_of"][pdf_page] = title

            y = BODY_TOP
            if page_in_chapter == 0 and spec.chapter_heading_size:
                page.insert_text((LEFT, y + 10), title, fontname="tibo", fontsize=spec.chapter_heading_size)
                y += spec.chapter_heading_size * 2.4
            if spec.section_headings and page_in_chapter in (0, 2):
                page.insert_text(
                    (LEFT, y), f"{chapter_index + 1}.{page_in_chapter + 1} FIXTURE section heading",
                    fontname="tibo", fontsize=spec.body_size,
                )
                y += spec.body_size * 2.2
            if spec.other_face_headings:
                page.insert_text((LEFT, y), "FIXTURE subheading in another face",
                                 fontname="hebo", fontsize=spec.body_size)
                y += spec.body_size * 2.2

            seed = chapter_index * 100 + page_in_chapter * 10
            tag = f"pageword{body_number}"
            y = _paragraph(page, y, spec.body_size, seed, tag=tag)
            y = _paragraph(page, y, spec.body_size, seed + 1)
            if spec.quote_size:
                y = _paragraph(page, y, spec.quote_size, seed + 2, x=LEFT + 36, lines=4,
                               tag=f"quoteword{body_number}")
            y = _paragraph(page, y, spec.body_size, seed + 3)
            y = _paragraph(page, y, spec.body_size, seed + 4)
            y = _paragraph(page, y, spec.body_size, seed + 5)

            if spec.footnote_size:
                leading = spec.footnote_size * 1.2
                foot_y = 730 - (spec.footnote_lines - 1) * leading
                page.insert_text((LEFT, foot_y - 3), str(body_number), fontname="tiro",
                                 fontsize=spec.footnote_size * 0.6)
                for line in range(spec.footnote_lines):
                    text = (f"noteword{body_number} FIXTURE footnote citing a synthetic work."
                            if line == 0 else _sentence(7000 + body_number * 10 + line))
                    page.insert_text((LEFT + 8, foot_y + line * leading), text,
                                     fontname="tiro", fontsize=spec.footnote_size)
            if spec.divider_number and body_number == 3:
                page.insert_text((PAGE_WIDTH / 2, 600), "2", fontname="tibo", fontsize=spec.body_size)

    doc.save(path)
    doc.close()
    expected["pages"] = pdf_page
    return expected


def make_blank_pdf(path, pages: int = 2) -> None:
    """A PDF with pages but no text layer — what a scan looks like to the system."""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        page.draw_rect(pymupdf.Rect(80, 80, 500, 700))
    doc.save(path)
    doc.close()


def make_encrypted_pdf(path) -> None:
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_text((LEFT, 200), "FIXTURE protected text", fontname="tiro", fontsize=12)
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="fixture", owner_pw="fixture")
    doc.close()


# ---------------------------------------------------------------------------
# A synthetic journal article in two columns (PLAN_V7 §5)
# ---------------------------------------------------------------------------

COL_LEFT, COL_RIGHT = 50, 310          # where each column's text starts
ARTICLE_TOP = 70


@dataclass
class ArticleSpec:
    pages: int = 4
    columns: int = 2                   # 1 = the same article set in a single column
    body_size: float = 10.0
    title: str = "FIXTURE Article On Synthetic Canals"
    authors: str | None = "Fixture Author and Second Fixture"
    doi: str | None = "10.5555/fixture.2020.001"
    journal: str = "FIXTURE Journal of Synthetic Studies"
    first_page_number: int = 101
    year_line: str | None = "Received 2019, accepted 2020"
    footnotes: bool = True             # a footnote at the foot of the LEFT column of each page
    footnote_lines: int = 1            # more lines = footnotes carry more of the text
    short_left_column: bool = False    # the left column ends, with its footnote, above the foot of the right
    references: bool = True            # a "References" heading and entries, closing the last page
    wide_figure_beside_text: bool = False   # a block across both columns with text beside it
    # What real journals do (ADR 0015):
    line_jitter: bool = False          # one line a page set a hair smaller, as justified text is
    journal_furniture: bool = False    # a running head on left-hand pages only; the page number inside a
                                       # footer line that changes side: "102 | Journal | Vol 12 | ... 2021"
    appended_form_pages: int = 0       # pages of a form at the end, close to body size, numbered 1, 2 ...
    panel_letters: bool = False        # figure panel letters "a", "b" close to body size
    margin_stamp: bool = False         # a repository's stamp turned on its side in the margin of page 1
    cited_year: str | None = None      # a year cited in the abstract, earlier than the article's own


def _short(seed: int) -> str:
    """A line short enough to stay inside one column."""
    a, b = WORDS[(seed * 5) % len(WORDS)], WORDS[(seed * 11 + 3) % len(WORDS)]
    return f"FIXTURE the {a} and the {b} met"


def _column_paragraph(page, x: float, y: float, size: float, seed: int, tag: str, lines: int = 4,
                      small_line: str | None = None) -> float:
    """`small_line` sets the third line a tenth of a point smaller and tags it: what a
    journal does to a line when it justifies it."""
    leading = size * 1.25
    for line in range(lines):
        text = _short(seed * 10 + line)
        if small_line and line == 2:
            page.insert_text((x, y + line * leading), f"{small_line} {text}", fontname="tiro", fontsize=size - 0.1)
            continue
        page.insert_text((x, y + line * leading), f"{tag} {text}" if line == 0 else text, fontname="tiro", fontsize=size)
    return y + lines * leading + size * 1.4


def make_article(path, spec: ArticleSpec | None = None) -> dict:
    """Write the PDF and return what a correct extraction must find: per page, the
    tags of its paragraphs in reading order, and its printed page number."""
    spec = spec or ArticleSpec()
    doc = pymupdf.open()
    expected = {"order": {}, "labels": {}, "footnote_pages": [], "reference_page": None}
    seed = 0
    for number in range(1, spec.pages + 1):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        label = str(spec.first_page_number + number - 1)
        if spec.journal_furniture:
            left_hand = number % 2 == 0
            if left_hand:
                page.insert_text((COL_LEFT, 32), "FIXTURE Running Head", fontname="tibo", fontsize=14)
            line = "FIXTURE Journal | Vol 12 | 26 August 2021"
            page.insert_text((COL_LEFT if left_hand else PAGE_WIDTH - 230, 815),
                             f"{label} | {line}" if left_hand else f"{line} | {label}", fontname="tiro", fontsize=8)
        else:
            page.insert_text((COL_LEFT, 34), spec.journal, fontname="tiit", fontsize=8)
            page.insert_text((PAGE_WIDTH - 70, 34), label, fontname="tiro", fontsize=8)
        expected["labels"][number] = label
        if spec.margin_stamp and number == 1:
            page.insert_text((24, 620), "fixture:1810.00000v2 [xx.YY] 24 May 2031", fontname="tiro", fontsize=20, rotate=90)
        order, y = [], ARTICLE_TOP
        if number == 1:
            page.insert_text((COL_LEFT, y + 10), spec.title, fontname="tibo", fontsize=18)
            y += 40
            if spec.authors:
                page.insert_text((COL_LEFT, y), spec.authors, fontname="tiro", fontsize=11)
                y += 18
            if spec.doi:
                page.insert_text((COL_LEFT, y), f"https://doi.org/{spec.doi}", fontname="tiro", fontsize=8)
                y += 14
            if spec.year_line:
                page.insert_text((COL_LEFT, y), spec.year_line, fontname="tiro", fontsize=8)
                y += 20
            # the abstract runs across both columns
            for line in range(3):
                page.insert_text((COL_LEFT, y + line * spec.body_size * 1.25),
                                 ("abstractword " if line == 0 else "") + _sentence(500 + line) + " " + _short(600 + line)
                                 + (f" (Example, {spec.cited_year})" if spec.cited_year and line == 2 else ""),
                                 fontname="tiro", fontsize=spec.body_size)
            order.append("abstractword")
            y += 3 * spec.body_size * 1.25 + 20
        top = y
        columns = [COL_LEFT, COL_RIGHT] if spec.columns == 2 else [COL_LEFT]
        for column, x in enumerate(columns):
            y = top
            side = "left" if column == 0 else "right"
            if column == 0 and number in (1, 3):
                page.insert_text((x, y), f"FIXTURE Section {number}", fontname="tibo", fontsize=spec.body_size)
                y += spec.body_size * 2.2
            closing = spec.references and number == spec.pages and column == len(columns) - 1
            short = spec.short_left_column and column == 0 and spec.columns == 2
            if spec.panel_letters:
                page.insert_text((x, y), "a" if column == 0 else "b", fontname="hebo", fontsize=spec.body_size - 0.2)
                y += spec.body_size * 2.2
            for paragraph in range(2 if closing or short else 5):
                seed += 1
                tag = f"{side}{number}x{paragraph}"
                jitter = spec.line_jitter and column == 0 and paragraph == 1
                y = _column_paragraph(page, x, y, spec.body_size, seed, tag,
                                      small_line=f"jitterword{number}" if jitter else None)
                order.append(tag)
            if closing:
                page.insert_text((x, y), "References", fontname="tibo", fontsize=spec.body_size)
                y += spec.body_size * 2.2
                for entry in range(6):
                    for line in range(2):
                        text = (f"refword{entry} Example, A. FIXTURE cited work {entry}" if line == 0
                                else "FIXTURE Synthetic Press, 1999, and so on")
                        page.insert_text((x, y + line * spec.body_size * 1.25), text, fontname="tiro", fontsize=spec.body_size)
                    y += 2 * spec.body_size * 1.25 + spec.body_size * 1.4
                    order.append(f"refword{entry}")
                expected["reference_page"] = number
            if spec.footnotes and column == 0 and not (number == spec.pages and len(columns) == 1):
                foot_y = y + 12 if short else 760 - (spec.footnote_lines - 1) * 9.6
                page.insert_text((x, foot_y - 3), str(number), fontname="tiro", fontsize=8 * 0.6)
                for line in range(spec.footnote_lines):
                    text = f"noteword{number} FIXTURE footnote, a synthetic work." if line == 0 else _short(9000 + number * 10 + line)
                    page.insert_text((x + 8, foot_y + line * 9.6), text, fontname="tiro", fontsize=8)
                expected["footnote_pages"].append(number)
        if number == 2 and spec.wide_figure_beside_text:
            # a caption-like block across the split, level with text on both sides
            page.insert_text((COL_LEFT + 150, top + 4), "wideword FIXTURE a wide block lying across both columns here",
                             fontname="tiro", fontsize=spec.body_size)
        expected["order"][number] = order
    expected["form_pages"] = []
    for form in range(1, spec.appended_form_pages + 1):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        for line in range(22):
            page.insert_text((COL_LEFT, ARTICLE_TOP + line * 14), f"formword{form} " + _sentence(3000 + form * 40 + line),
                             fontname="tiro", fontsize=spec.body_size - 0.2)
        page.insert_text((PAGE_WIDTH / 2, 815), str(form), fontname="tiro", fontsize=8)
        expected["form_pages"].append(spec.pages + form)
    doc.save(path)
    doc.close()
    expected["pages"] = spec.pages + spec.appended_form_pages
    return expected
