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
# A DOI as printed: "10.", a registrant code, a slash, a suffix. A proposal, like the rest.
_DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+")
AUTHOR_LINE_MAX = 200          # a longer block under the title is an abstract, not a list of names


def _empty(reason: str) -> dict:
    return {"value": "", "source": reason}


def propose(pdf_path, kind: str = "thesis") -> dict:
    """Return {"title", "author", "year", "doi"} proposals, each with where it came
    from, plus the PDF's own metadata as an unverified hint.

    For an article (PLAN_V7 §5) the first page stands in for a title page: the title
    is its largest text, the authors the short block set under it, and a DOI is read
    by its printed shape. No network lookup is made, and no value is cited until the
    researcher confirms it."""
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
        "doi": _empty("no title page with text was found"),
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

    found = [match.group(0).rstrip(".,;)]") for block in title_page for match in _DOI.finditer(block.text)]
    proposal["doi"] = ({"value": found[0], "source": f"a DOI printed on PDF page {page_number}"} if found
                       else _empty("no DOI is printed on the first page"))

    # Author: a line that reads "By <name>", or the line after a lone "by".
    proposal["author"] = _empty('no line beginning "by" was found on the title page')
    if kind == "article" and largest > min(sizes):
        # An article prints its authors under the title, in smaller type.
        titled = max(index for index, block in enumerate(title_page) if block.lead["size"] == largest)
        under = next((block for block in title_page[titled + 1:] if not _DOI.search(block.text)), None)
        if under is not None and len(under.text) <= AUTHOR_LINE_MAX:
            proposal["author"] = {"value": under.text,
                                  "source": f"the block under the title on PDF page {page_number}; check the form of the name"}
        else:
            proposal["author"] = _empty("no short block is set under the title")
    for index, block in enumerate(title_page if kind != "article" else []):
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
    if kind == "article" and years:
        # An article's first page carries its text, and with it the years of the works it
        # cites. None of those can be later than the article itself (ADR 0015).
        proposal["year"] = {"value": max(years), "source": f"the latest year printed on PDF page {page_number}"}
    else:
        proposal["year"] = (
            {"value": years[-1], "source": f"the last year printed on PDF page {page_number}"}
            if years
            else _empty("no four-digit year was found on the title page")
        )
    return proposal
