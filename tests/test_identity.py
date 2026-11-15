"""Identity proposal from the title page — `identity.py` (PLAN_V4 §10)."""

from __future__ import annotations

import pymupdf

import identity
from pdf_factory import ThesisSpec, make_blank_pdf, make_thesis


def propose(tmp_path, **spec) -> dict:
    path = tmp_path / "thesis.pdf"
    make_thesis(path, ThesisSpec(**spec))
    return identity.propose(path)


def test_title_author_and_year_are_proposed_with_where_each_came_from(tmp_path):
    proposal = propose(tmp_path)

    assert proposal["title"] == {
        "value": "FIXTURE Thesis On Synthetic Lighthouses",
        "source": "the largest text on PDF page 1",
    }
    assert proposal["author"] == {
        "value": "Fixture Author",
        "source": 'the line beginning "by" on PDF page 1',
    }
    assert proposal["year"] == {"value": "2001", "source": "the last year printed on PDF page 1"}
    assert proposal["title_page"] == 1


def test_a_missing_by_line_leaves_the_author_blank(tmp_path):
    proposal = propose(tmp_path, author_line="Fixture Author")

    assert proposal["author"] == {
        "value": "",
        "source": 'no line beginning "by" was found on the title page',
    }
    assert proposal["title"]["value"] == "FIXTURE Thesis On Synthetic Lighthouses"


def test_a_missing_year_is_left_blank_not_guessed(tmp_path):
    proposal = propose(tmp_path, year_line="March")
    assert proposal["year"] == {"value": "", "source": "no four-digit year was found on the title page"}


def test_quotation_marks_around_a_title_are_dropped(tmp_path):
    proposal = propose(tmp_path, title='"FIXTURE Quoted Title"')
    assert proposal["title"]["value"] == "FIXTURE Quoted Title"


def test_pdf_metadata_is_returned_as_a_hint_and_never_used_as_the_proposal(tmp_path):
    path = tmp_path / "thesis.pdf"
    make_thesis(path, ThesisSpec())
    doc = pymupdf.open(path)
    doc.set_metadata({"author": "FIXTURE Template Owner", "title": "FIXTURE Template Title"})
    tagged = tmp_path / "tagged.pdf"
    doc.save(tagged)

    proposal = identity.propose(tagged)

    assert proposal["pdf_metadata"] == {"author": "FIXTURE Template Owner", "title": "FIXTURE Template Title"}
    assert proposal["author"]["value"] == "Fixture Author"
    assert proposal["title"]["value"] == "FIXTURE Thesis On Synthetic Lighthouses"


def test_a_pdf_with_no_text_proposes_nothing(tmp_path):
    path = tmp_path / "scan.pdf"
    make_blank_pdf(path)
    proposal = identity.propose(path)

    assert [proposal[field]["value"] for field in ("title", "author", "year")] == ["", "", ""]
    assert proposal["title_page"] is None
