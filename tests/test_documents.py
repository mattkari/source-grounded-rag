"""The document record — `documents.py` (PLAN_V4 §5, §11)."""

from __future__ import annotations

import dataclasses

import ask
import evaluate
from config import settings
from documents import Document, LayoutProfile, default_document, default_layout


def test_the_builtin_document_is_built_from_the_configured_identity_and_profile():
    document = default_document()

    assert document.builtin is True
    assert (document.document_id, document.author, document.year) == (
        settings.document_id, settings.document_author, settings.document_year,
    )
    assert document.short_title == settings.document_short_title
    assert (document.pdf_path, document.canonical_dir, document.index_dir) == (
        settings.pdf_path, settings.canonical_dir, settings.index_dir,
    )
    assert document.layout == LayoutProfile(
        body_size=settings.body_size,
        body_min_size=settings.body_min_size,
        header_band_y=settings.header_band_y,
        footnote_band_y=settings.footnote_band_y,
        page_number_band="footer",
        heading_min_size=settings.heading_min_size,
        heading_fonts=settings.heading_fonts,
        chapter_heading_min_size=settings.chapter_heading_min_size,
        section_heading_min_size=settings.section_heading_min_size,
        chapter_source=settings.chapter_source,
        apparatus_chapter_prefixes=settings.apparatus_chapter_prefixes,
    )


def test_a_caller_with_its_own_settings_gets_a_document_built_from_them(tmp_path):
    custom = dataclasses.replace(settings, index_dir=tmp_path, document_author="Fixture, A.")
    document = default_document(custom)

    assert document.index_dir == tmp_path
    assert document.author == "Fixture, A."
    assert default_layout(custom) == default_layout(settings)


def test_a_layout_profile_survives_a_round_trip_through_json():
    profile = dataclasses.replace(
        default_layout(), header_band_y=None, chapter_source=None, heading_fonts=("Times-Bold", "Fixture-Bold"),
    )
    stored = profile.to_json()

    assert stored["heading_fonts"] == ["Times-Bold", "Fixture-Bold"]
    assert stored["header_band_y"] is None
    assert LayoutProfile.from_json(stored) == profile
    assert LayoutProfile.from_json({**stored, "a_field_from_a_newer_version": 1}) == profile


def test_an_evidence_item_with_no_document_belongs_to_the_builtin_thesis():
    item = ask.EvidenceItem("E1", {"chapter": None, "section": None, "page_start": "3", "page_end": "3"}, 0.5)

    assert item.document is None
    assert ask.footnote(1, item) == f"1. {settings.document_author} ({settings.document_year}), p. 3."


def test_an_evidence_item_is_cited_under_the_document_it_carries():
    other = dataclasses.replace(default_document(), author="Fixture, A.", year="2001",
                                short_title="FIXTURE short title", builtin=False)
    item = ask.EvidenceItem("E1", {"chapter": None, "section": None, "page_start": "3", "page_end": "3",
                                   "text": "FIXTURE passage."}, 0.5, document=other)

    assert ask.footnote(1, item) == "1. Fixture, A. (2001), p. 3."
    assert ask.render_evidence_block([item]) == '[E1] FIXTURE short title\n"FIXTURE passage."'


def test_the_evaluation_runs_against_the_builtin_thesis_only():
    """PLAN_V4 §11: evaluate.py takes no document, so it can never score an upload by accident."""
    assert "document" not in evaluate.run.__kwdefaults__
    assert isinstance(default_document(), Document)
