"""Propose a thesis's author, year and title from its title page — PLAN_V4 §10.

A proposal, never a fact. Everything returned here is shown to the researcher
in a form and nothing is cited until they confirm it (hard rule 6).

The reading uses layout only — the largest text, a "by" line, a four-digit
year. No model is called, so the step is deterministic and testable. A field
the rules cannot read is left empty for the researcher to type.

PDF metadata is returned separately, as a hint. It is known to be unreliable:
the built-in thesis's own metadata names a second author inherited from the
template it was written in.
"""

from __future__ import annotations

import re

import pymupdf

import layout

TITLE_PAGE_SEARCH = 3          # look for the title page among the first few pages
_BY_LINE = re.compile(r"^by[:\s]+(?P<name>\S.*)$", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_QUOTES = "\"'“”‘’«» "


def _empty(reason: str) -> dict:
    return {"value": "", "source": reason}


def propose(pdf_path) -> dict:
    """Return {"title", "author", "year"} proposals, each with where it came from,
    plus the PDF's own metadata as an unverified hint."""
    doc = pymupdf.open(pdf_path)
    metadata = {
        key: value.strip()
        for key, value in (doc.metadata or {}).items()
        if key in {"title", "author"} and isinstance(value, str) and value.strip()
    }

    pages = layout.read_blocks(pdf_path)
    title_page = next((blocks for blocks in pages[:TITLE_PAGE_SEARCH] if blocks), None)
    proposal = {
        "title": _empty("no title page with text was found"),
        "author": _empty("no title page with text was found"),
        "year": _empty("no title page with text was found"),
        "pdf_metadata": metadata,
        "title_page": title_page[0].pdf_page if title_page else None,
    }
    if title_page is None:
        return proposal
    page_number = title_page[0].pdf_page

    # Title: the largest text on the page, if anything is set larger than the rest.
    sizes = [block.lead["size"] for block in title_page]
    largest = max(sizes)
    if largest > min(sizes):
        title = " ".join(block.text for block in title_page if block.lead["size"] == largest)
        proposal["title"] = {
            "value": title.strip(_QUOTES),
            "source": f"the largest text on PDF page {page_number}",
        }
    else:
        proposal["title"] = _empty("no text on the title page is set larger than the rest")

    # Author: a line that reads "By <name>", or the line after a lone "by".
    proposal["author"] = _empty('no line beginning "by" was found on the title page')
    for index, block in enumerate(title_page):
        match = _BY_LINE.match(block.text)
        if match:
            proposal["author"] = {
                "value": match.group("name").strip(),
                "source": f'the line beginning "by" on PDF page {page_number}',
            }
            break
        if block.text.lower() in {"by", "by:"} and index + 1 < len(title_page):
            proposal["author"] = {
                "value": title_page[index + 1].text,
                "source": f'the line after "by" on PDF page {page_number}',
            }
            break

    # Year: the last four-digit year printed on the page.
    years = [year for block in title_page for year in _YEAR.findall(block.text)]
    proposal["year"] = (
        {"value": years[-1], "source": f"the last year printed on PDF page {page_number}"}
        if years
        else _empty("no four-digit year was found on the title page")
    )
    return proposal
