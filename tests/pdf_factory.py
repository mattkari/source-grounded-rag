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
