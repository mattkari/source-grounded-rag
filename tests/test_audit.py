"""The provenance audit — `audit.py` (PLAN_V4 §8).

A clean synthetic thesis must pass every check, and each planted defect must be
reported by the check that exists to catch it.
"""

from __future__ import annotations

import copy

import pytest

import audit
import upload
from documents import HEADING, RUNNING_HEADER
from pdf_factory import ThesisSpec, make_blank_pdf, make_thesis


@pytest.fixture
def analysed(tmp_path):
    """Measure, extract and chunk a synthetic thesis; return what the audit needs."""

    def run(**spec):
        path = tmp_path / "thesis.pdf"
        make_thesis(path, ThesisSpec(**spec))
        analysis = upload.analyse_pdf(path, "thesis-fixture")

        class Analysed:
            pdf = path
            layout = analysis["layout"]
            rows = copy.deepcopy(analysis["rows"])
            chunks = copy.deepcopy(analysis["records"])
            clean = analysis["audit"]

            def audit(self):
                return audit.audit(self.pdf, self.rows, self.chunks, self.layout)

        return Analysed()

    return run


def spanning(chunks, minimum_pages=2):
    """A chunk that covers more than one page."""
    return next(c for c in chunks if c["pdf_page_end"] - c["pdf_page_start"] + 1 >= minimum_pages)


# --- a clean thesis ----------------------------------------------------------------


def test_a_clean_thesis_passes_every_check(analysed):
    a = analysed()
    result = a.clean
    total = len(a.chunks)

    assert total >= 4
    assert result["chunks"]["page_labels_match_the_pdf"] == {"n": total, "N": total, "failing": []}
    assert result["chunks"]["words_on_claimed_pages"] == {"n": total, "N": total, "failing": []}
    assert result["chunks"]["within_one_chapter"] == {"n": total, "N": total, "failing": []}
    assert result["labels_printed_on_their_page"] == {"n": 20, "N": 20, "failing": []}
    assert result["label_sequence"] == {"steps_checked": 17, "breaks": []}
    assert result["hard_stops"] == []


def test_the_audit_counts_pages_and_lists_the_ones_without_a_number(analysed):
    result = analysed(unnumbered=(3, 4)).clean

    assert result["pages"] == {
        "total": 21,
        "with_text": 21,
        "with_body_text": 21,
        "with_printed_number": 18,
        "without_printed_number": [1, 6, 7],
        "text_but_no_body": [],
    }
    # Pages 2 -> 5 skip two unnumbered pages; label and PDF page still advance together.
    assert result["label_sequence"]["breaks"] == []


def test_reference_apparatus_is_counted_apart_from_source_passages(analysed):
    chunks = analysed().clean["chunks"]

    assert chunks["apparatus"] >= 1
    assert chunks["source"] + chunks["apparatus"] == chunks["total"]


def test_chapters_are_reported_with_what_carried_them(analysed):
    by_header = analysed().clean["chapters"]
    by_heading = analysed(header="none").clean["chapters"]

    assert by_header["source"] == RUNNING_HEADER
    assert by_heading["source"] == HEADING
    assert {"FIXTURE Chapter Alpha", "FIXTURE Chapter Beta", "FIXTURE Chapter Gamma"} <= set(by_header["names"])
    assert by_header["count"] == len(by_header["names"])


# --- planted defects ------------------------------------------------------------------


def test_a_chunk_with_the_wrong_page_label_is_reported(analysed):
    a = analysed()
    victim = a.chunks[1]
    victim["page_start"] = "99"

    result = a.audit()

    assert result["chunks"]["page_labels_match_the_pdf"]["failing"] == [victim["chunk_id"]]
    assert result["chunks"]["page_labels_match_the_pdf"]["n"] == len(a.chunks) - 1
    assert result["hard_stops"] == []          # a wrong label is for the researcher to weigh


def test_a_stored_label_that_is_not_printed_on_its_page_is_reported(analysed):
    a = analysed()
    row = next(r for r in a.rows if r["printed_page"] == "4")
    row["printed_page"] = "40"

    result = a.audit()

    assert result["labels_printed_on_their_page"]["failing"] == [row["pdf_page"]]
    assert result["labels_printed_on_their_page"]["n"] == 19
    assert result["label_sequence"]["breaks"] == [
        {"from_pdf_page": row["pdf_page"] - 1, "to_pdf_page": row["pdf_page"]},
        {"from_pdf_page": row["pdf_page"], "to_pdf_page": row["pdf_page"] + 1},
    ]


def test_a_word_that_is_not_on_the_claimed_pages_is_a_hard_stop(analysed):
    a = analysed()
    victim = a.chunks[2]
    victim["text"] += " FIXTUREALIENWORD"

    result = a.audit()

    assert result["chunks"]["words_on_claimed_pages"]["failing"] == [victim["chunk_id"]]
    assert result["hard_stops"] == [
        f"1 of {len(a.chunks)} passages contain words that are not on the pages they claim. "
        "A citation of such a passage would be false."
    ]


def test_a_passage_assigned_to_the_wrong_pages_is_a_hard_stop(analysed):
    a = analysed()
    victim = spanning(a.chunks, 1)
    shift = 8 if victim["pdf_page_end"] + 8 <= 21 else -8
    victim["pdf_page_start"] += shift
    victim["pdf_page_end"] += shift

    result = a.audit()

    assert victim["chunk_id"] in result["chunks"]["words_on_claimed_pages"]["failing"]
    assert result["hard_stops"] != []


def test_a_chunk_that_crosses_a_running_header_boundary_is_reported(analysed):
    a = analysed()
    alpha = [c for c in a.chunks if c["chapter"] == "FIXTURE Chapter Alpha"][-1]
    alpha["pdf_page_end"] += 1               # now reaches into Chapter Beta's first page

    result = a.audit()

    assert result["chunks"]["within_one_chapter"]["failing"] == [alpha["chunk_id"]]


def test_a_chunk_that_runs_into_the_next_chapter_heading_is_reported(analysed):
    a = analysed(header="none")
    alpha = [c for c in a.chunks if c["chapter"] == "FIXTURE Chapter Alpha"][-1]
    alpha["text"] += "\nFIXTURE Chapter Beta\nFIXTURE the ferry stood beside the canal."
    alpha["pdf_page_end"] += 1

    result = a.audit()

    assert result["chunks"]["within_one_chapter"]["failing"] == [alpha["chunk_id"]]


def test_with_no_chapter_structure_the_chapter_check_says_so_instead_of_passing(analysed):
    result = analysed(header="constant", chapter_heading_size=None).clean

    assert result["chunks"]["within_one_chapter"]["n"] is None
    assert result["chunks"]["within_one_chapter"]["note"] == "no chapter structure to check against"


def test_a_pdf_with_no_text_is_a_hard_stop(tmp_path, analysed):
    a = analysed()
    scan = tmp_path / "scan.pdf"
    make_blank_pdf(scan)

    result = audit.audit(scan, [{"pdf_page": 1, "printed_page": None, "running_header": None, "text": ""}],
                         [], a.layout)

    assert "The PDF has no text layer." in result["hard_stops"]


# --- the report -------------------------------------------------------------------------


def test_the_report_gives_counts_and_ids_and_never_passage_text(analysed):
    a = analysed()
    a.chunks[2]["text"] += " FIXTUREALIENWORD"
    report = audit.format_report(a.audit())
    total = len(a.chunks)

    assert f"every word on the claimed pages    {total - 1}/{total}" in report
    assert a.chunks[2]["chunk_id"] in report
    assert "CANNOT BE APPROVED" in report
    for leaked in ("FIXTUREALIENWORD", "lighthouse", "pageword", "FIXTURE Chapter Alpha"):
        assert leaked not in report


def test_a_clean_report_leaves_the_decision_to_the_researcher(analysed):
    report = audit.format_report(analysed().clean)

    assert "Nothing here blocks approval. Whether it is good enough is your decision." in report
    assert "CANNOT BE APPROVED" not in report
    assert "with a printed page number         20/21" in report
    assert "without one (PDF pages)            1" in report
