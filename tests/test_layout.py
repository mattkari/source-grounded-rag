"""Automatic layout measurement — `layout.py` (PLAN_V4 §7, Sprint U0).

Synthetic PDFs with known layouts go in; the measured profile, and what the
real extractor then reads with it, must come out right. The last tests run the
measurement on the built-in thesis itself (PLAN_V4 §9).
"""

from __future__ import annotations

import dataclasses
import json

import pytest

import ingest
import layout
from documents import HEADING, RUNNING_HEADER, default_document
from pdf_factory import ThesisSpec, make_blank_pdf, make_thesis


@pytest.fixture
def measured(tmp_path):
    """Build a synthetic thesis, measure it, and extract it with what was measured."""

    def run(**spec):
        path = tmp_path / "thesis.pdf"
        expected = make_thesis(path, ThesisSpec(**spec))
        measurement = layout.measure(path)
        pages = ingest.extract_document(path, measurement.layout)

        class Result:
            pass

        result = Result()
        result.path, result.expected, result.measurement = path, expected, measurement
        result.layout, result.pages = measurement.layout, pages
        result.labels = {p.pdf_page: p.printed_page for p in pages}
        result.headers = {p.pdf_page: p.running_header for p in pages}
        result.segments = ingest.build_segments(pages, measurement.layout)
        result.chapters = sorted({s.chapter for s in result.segments if s.chapter})
        result.body = "\n".join(p.body for p in pages)
        return result

    return run


# --- the ordinary case ---------------------------------------------------------------


def test_a_thesis_with_running_headers_and_footer_numbers_is_measured(measured):
    m = measured()

    assert m.layout.body_size == 12.0
    assert m.layout.body_min_size == 12.0
    assert m.layout.page_number_band == "footer"
    assert m.layout.heading_min_size == 13.0
    assert m.layout.heading_fonts == ("Times-Bold",)
    assert m.layout.chapter_source == RUNNING_HEADER
    assert m.measurement.flags == []
    assert (m.measurement.pages_total, m.measurement.pages_with_text) == (21, 21)


def test_the_measured_bands_separate_furniture_from_text(measured):
    m = measured()
    blocks = layout.read_blocks(m.path)
    body_page = blocks[5]
    header, label = body_page[0], body_page[-1]
    text = [b for b in body_page if b is not header and b is not label]

    assert header.y0 < m.layout.header_band_y < min(b.y0 for b in text)
    assert max(b.y0 for b in text) < m.layout.footnote_band_y < label.y0


def test_every_printed_page_number_is_read_and_the_title_page_has_none(measured):
    m = measured()
    assert m.labels == m.expected["labels"]
    assert m.labels[1] is None and m.labels[2] == "i" and m.labels[4] == "1"


def test_the_running_header_becomes_the_chapter(measured):
    m = measured()
    assert m.headers == m.expected["headers"]
    assert m.chapters == sorted(m.expected["chapter_titles"] + ["FIXTURE Abstract"])


def test_every_value_comes_with_its_evidence(measured):
    evidence = measured().measurement.evidence

    for key in ("body_size", "body_min_size", "header_band_y", "footnote_band_y", "page_number_band",
                "heading_min_size", "heading_fonts", "heading_tiers", "chapter_source"):
        assert evidence[key]["rule"]
    assert evidence["page_number_band"]["pages_with_a_label"] == 20
    assert evidence["page_number_band"]["consistent_steps"] == evidence["page_number_band"]["steps_checked"]
    assert evidence["chapter_source"]["distinct_headers"] == 5
    assert evidence["body_size"]["body_font"] == "Times-Roman"


# --- where the chapter comes from ---------------------------------------------------------


def test_without_a_running_header_chapters_come_from_the_large_headings(measured):
    m = measured(header="none")

    assert m.layout.header_band_y is None
    assert m.layout.chapter_source == HEADING
    assert m.layout.chapter_heading_min_size == 18.0
    assert set(m.expected["chapter_titles"]) <= set(m.chapters)
    assert m.labels == m.expected["labels"]


def test_a_header_that_never_changes_does_not_carry_the_chapter(measured):
    m = measured(header="constant")

    assert m.layout.header_band_y is not None      # still furniture, still kept out of the text
    assert m.layout.chapter_source == HEADING
    assert "FIXTURE Thesis On Synthetic Lighthouses" not in m.body.split("\n", 3)[-1]


def test_no_chapter_structure_is_reported_not_invented(measured):
    m = measured(header="constant", chapter_heading_size=None)

    assert m.layout.chapter_source is None
    assert m.chapters == []
    assert any(flag.startswith("No chapter structure was found.") for flag in m.measurement.flags)


# --- where the page number is ---------------------------------------------------------------


def test_a_page_number_sharing_the_header_line_is_read_and_kept_out_of_the_chapter(measured):
    m = measured(page_numbers="header")

    assert m.layout.page_number_band == "header"
    assert m.layout.footnote_band_y is None
    assert m.labels == m.expected["labels"]
    assert m.headers == m.expected["headers"]       # "FIXTURE Chapter Alpha", never "... Alpha 1"
    assert m.layout.chapter_source == RUNNING_HEADER


def test_a_thesis_with_no_page_numbers_is_flagged_and_gets_no_labels(measured):
    m = measured(page_numbers="none")

    assert m.layout.page_number_band is None
    assert set(m.labels.values()) == {None}
    assert m.measurement.flags == [
        "No printed page number was found. Every citation of this thesis will read "
        "'PDF p. N [VERIFY]' instead of a page number."
    ]


def test_numbers_that_do_not_advance_with_the_pages_are_not_page_numbers(measured):
    m = measured(page_numbers="scrambled")

    assert m.layout.page_number_band is None
    assert set(m.labels.values()) == {None}
    assert m.measurement.evidence["page_number_band"]["rejected"] == "labels do not advance with the pages"
    assert m.layout.footnote_band_y is not None     # the stray numbers are still kept out of the text


def test_a_page_whose_number_did_not_print_is_left_without_one(measured):
    m = measured(unnumbered=(3, 4))

    assert m.layout.page_number_band == "footer"
    assert m.labels == m.expected["labels"]
    assert [pdf for pdf, label in m.labels.items() if label is None] == [1, 6, 7]


def test_a_lone_number_inside_the_text_is_not_mistaken_for_the_page_number(measured):
    m = measured(divider_number=True, unnumbered=(3,))
    plain = measured()

    assert m.layout.footnote_band_y == plain.layout.footnote_band_y
    assert m.labels[6] is None


# --- headers that are awkward ------------------------------------------------------------------


def test_a_running_header_that_wraps_onto_a_second_line_is_taken_whole(measured):
    m = measured(header_lines=2)

    assert m.layout.chapter_source == RUNNING_HEADER
    assert m.headers == m.expected["headers"]
    assert m.headers[5] == "FIXTURE Chapter Alpha FIXTURE continued header"
    assert "continued header" not in m.body


def test_a_heading_that_repeats_on_the_next_page_is_not_swallowed_as_a_header(measured):
    m = measured(other_face_headings=True)
    plain = measured()

    assert abs(m.layout.header_band_y - plain.layout.header_band_y) < 1.0
    assert m.headers == m.expected["headers"]
    assert "FIXTURE subheading in another face" in m.body


# --- type sizes ----------------------------------------------------------------------------------


def test_a_thesis_set_in_eleven_point_has_its_bold_headings_found(measured):
    """The literal 12.0 that used to sit in the extractor would have missed these."""
    m = measured(body_size=11.0)

    assert m.layout.body_size == 11.0
    assert m.layout.heading_min_size == 12.0
    assert m.layout.heading_fonts == ("Times-Bold",)
    assert any(s.section and s.section.endswith("FIXTURE section heading") for s in m.segments)


def test_footnotes_set_smaller_at_the_foot_of_the_column_are_dropped(measured):
    m = measured(footnote_size=9.0)

    assert m.layout.body_min_size == 12.0
    assert "noteword" not in m.body
    assert "pageword3" in m.body


def test_block_quotations_are_kept_while_smaller_footnotes_are_dropped(measured):
    m = measured(quote_size=11.0, footnote_size=9.0)

    assert m.layout.body_min_size == 11.0
    assert "quoteword3" in m.body
    assert "noteword" not in m.body
    sizes = m.measurement.evidence["body_min_size"]["sizes_below_body"]
    assert sizes["11.0"]["read_as"] == "body text"
    assert sizes["9.0"]["read_as"].startswith("apparatus")
    assert m.measurement.flags == []


def test_footnotes_that_share_a_size_with_quotations_are_kept_and_flagged(measured):
    m = measured(quote_size=11.0, footnote_size=11.0)

    assert m.layout.body_min_size == 11.0
    assert "noteword3" in m.body                       # cannot be separated by size
    assert m.measurement.flags == [
        "Footnotes appear to share a type size (11pt) with block quotations: 18 blocks on 18 pages "
        "open with a footnote numeral at the foot of the column. They cannot be separated by size, "
        "so footnote text is kept and can be cited as if it were body text."
    ]


def test_bold_text_in_another_face_is_not_adopted_as_headings_but_is_reported(measured):
    m = measured(other_face_headings=True)

    assert m.layout.heading_fonts == ("Times-Bold",)
    assert m.measurement.evidence["heading_fonts"]["bold_faces_not_adopted"] == {"Helvetica-Bold": 18}
    assert not any(s.section == "FIXTURE subheading in another face" for s in m.segments)
    assert m.measurement.flags == [
        "Bold text in another face opens blocks at body size: Helvetica-Bold (18 pages). It was "
        "not treated as headings, so any sub-headings set in it are read as ordinary text."
    ]


# --- nothing to measure -----------------------------------------------------------------------------


def test_a_pdf_with_no_text_layer_yields_no_profile(tmp_path):
    path = tmp_path / "scan.pdf"
    make_blank_pdf(path)
    measurement = layout.measure(path)

    assert measurement.layout is None
    assert measurement.flags == ["The PDF has no text layer, so there is nothing to measure."]
    assert (measurement.pages_total, measurement.pages_with_text) == (2, 0)


# --- small parts ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "font, family",
    [
        ("TimesNewRomanPSMT", "TimesNewRoman"),
        ("TimesNewRomanPS-BoldMT", "TimesNewRoman"),
        ("Times-Roman", "Times"),
        ("Times-Bold", "Times"),
        ("ArialMT", "Arial"),
        ("Arial-BoldMT", "Arial"),
        ("ABCDEF+Garamond-Bold", "Garamond"),
        ("Calibri-Bold", "Calibri"),
    ],
)
def test_font_family_drops_weight_and_vendor_suffixes(font, family):
    assert layout.font_family(font) == family


@pytest.mark.parametrize("text, expected", [("12", True), ("xiv", True), (" 7 ", True), ("12a", False),
                                             ("Chapter 2", False), ("12345", False), ("", False)])
def test_is_page_label(text, expected):
    assert layout.is_page_label(text) is expected


def test_apparatus_prefixes_are_the_titles_as_printed():
    chapters = ["FIXTURE Chapter Alpha", "Bibliography", "References and notes", "Biography"]
    assert layout.apparatus_prefixes(chapters) == ("Bibliography", "References and notes")


# --- the built-in thesis (PLAN_V4 §9) -------------------------------------------------------------------

BUILTIN = default_document()
needs_builtin_pdf = pytest.mark.skipif(not BUILTIN.pdf_path.exists(), reason="the thesis PDF is not present")


@needs_builtin_pdf
def test_the_hand_measured_profile_still_reproduces_the_committed_extraction():
    """Refactoring ingest.py to take a profile must not move a single character."""
    pages = ingest.extract_document(BUILTIN.pdf_path, BUILTIN.layout)
    committed = [
        json.loads(line)
        for line in (BUILTIN.canonical_dir / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert ingest.canonical_rows(pages) == committed


@needs_builtin_pdf
def test_automatic_measurement_agrees_with_the_hand_profile_on_the_builtin_thesis():
    measured_layout = layout.measure(BUILTIN.pdf_path).layout
    hand = BUILTIN.layout

    # Values that are facts about the document must be the same.
    for name in ("body_size", "body_min_size", "page_number_band", "heading_min_size",
                 "heading_fonts", "chapter_source"):
        assert getattr(measured_layout, name) == getattr(hand, name), name

    # Band thresholds only need to fall in the same gap: between the lowest
    # header line (y=46) and the first body text (y=71), and between the lowest
    # text (y=757) and the page number (y=794).
    assert 46 < measured_layout.header_band_y < 71
    assert 757 < measured_layout.footnote_band_y < 794


@needs_builtin_pdf
def test_the_measured_profile_extracts_the_builtin_thesis_as_the_hand_profile_does():
    """Identical on every page but one, and there only in white space: the hand
    profile fuses the bibliography's title with the heading under it."""
    measured_layout = layout.measure(BUILTIN.pdf_path).layout
    measured_rows = ingest.canonical_rows(ingest.extract_document(BUILTIN.pdf_path, measured_layout))
    committed = [
        json.loads(line)
        for line in (BUILTIN.canonical_dir / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    differing = [(a, b) for a, b in zip(measured_rows, committed) if a != b]
    assert len(measured_rows) == len(committed) == 288
    assert [a["pdf_page"] for a, _ in differing] == [262]
    for measured_row, committed_row in differing:
        assert {**measured_row, "text": ""} == {**committed_row, "text": ""}
        assert measured_row["text"].split() == committed_row["text"].split()


def test_measuring_never_changes_the_profile_object_it_returns(measured):
    m = measured()
    with pytest.raises(dataclasses.FrozenInstanceError):
        m.layout.body_size = 10.0
