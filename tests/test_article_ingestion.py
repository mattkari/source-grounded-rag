"""Ingesting a journal article — PLAN_V7 §5 (Sprint M1).

Offline. Every PDF here is synthetic, built by `pdf_factory.make_article`, and every
word in it says FIXTURE. The measurement, the extractor, the audit and the upload
stages are the real code; nothing is embedded except by the offline fake.
"""

from __future__ import annotations

import dataclasses
import json
import re

import pytest

import ask
import audit as audit_module
import identity
import ingest
import layout
import upload
from article import footnotes
from documents import KIND_ARTICLE, KIND_THESIS, Document, LayoutProfile, default_document, default_layout
from pdf_factory import ArticleSpec, ThesisSpec, make_article, make_thesis
from upload import UploadRefused

TAG = re.compile(r"\b(?:left|right)\d+x\d+|abstractword|refword\d|noteword\d|wideword")
IDENTITY = {"author": "Fixture, A. and Fixture, S.", "year": "2020", "title": "FIXTURE Article On Synthetic Canals"}
PUBLISHED = {"container": "FIXTURE Journal of Synthetic Studies", "volume_issue": "12(3)", "pages": "101–104",
             "doi": "https://doi.org/10.5555/fixture.2020.001"}


@pytest.fixture
def article(tmp_path):
    def build(**spec):
        path = tmp_path / "article.pdf"
        return path, make_article(path, ArticleSpec(**spec))

    return build


def tags(page: ingest.Page) -> list[str]:
    return TAG.findall(page.body)


# --- measuring columns ---------------------------------------------------------------


def test_two_columns_are_measured_from_where_the_text_sits_and_one_column_stays_one(article, tmp_path):
    path, _ = article()
    measured = layout.measure(path)

    assert measured.layout.columns == 2 and 287 < measured.layout.column_split_x < 310
    assert measured.evidence["columns"]["pages_set_side_by_side"] == 4
    assert measured.layout.page_number_band == "header" and measured.layout.chapter_source is None

    single, _ = article(columns=1)
    assert (layout.measure(single).layout.columns, layout.measure(single).layout.column_split_x) == (1, None)
    thesis = tmp_path / "thesis.pdf"
    make_thesis(thesis, ThesisSpec())
    assert layout.measure(thesis).layout.columns == 1                          # a thesis is not disturbed


def test_the_builtin_thesis_profile_says_one_column_and_an_old_profile_still_loads():
    builtin = default_layout(ask.settings)
    assert (builtin.columns, builtin.column_split_x, builtin.apparatus_section_prefixes) == (1, None, ())

    stored = builtin.to_json()
    for added in ("columns", "column_split_x", "apparatus_section_prefixes"):
        stored.pop(added)                                                      # as saved before articles
    assert LayoutProfile.from_json(stored) == builtin


# --- reading order -------------------------------------------------------------------


def test_a_two_column_page_is_read_down_the_left_column_and_then_the_right(article):
    path, expected = article()
    profile = layout.measure(path).layout

    pages = ingest.extract_document(path, profile)

    assert [tags(page) for page in pages] == [expected["order"][n] for n in range(1, 5)]
    assert tags(pages[0])[0] == "abstractword"                                 # what lies across both columns comes first
    assert [page.printed_page for page in pages] == ["101", "102", "103", "104"]
    assert {page.running_header for page in pages} == {"FIXTURE Journal of Synthetic Studies"}
    assert not any("noteword" in page.body for page in pages)                  # footnotes are not body text

    as_one = ingest.extract_document(path, dataclasses.replace(profile, columns=1, column_split_x=None))
    assert tags(as_one[1]) != expected["order"][2]                             # read across, the columns interleave
    assert tags(as_one[1])[:2] == ["left2x0", "right2x0"]


def test_a_single_column_document_is_read_exactly_as_before(tmp_path):
    path = tmp_path / "thesis.pdf"
    make_thesis(path, ThesisSpec())
    profile = layout.measure(path).layout
    forced = dataclasses.replace(profile, columns=2, column_split_x=None)       # no split: nothing to reorder

    assert profile.columns == 1
    assert ingest.extract_document(path, forced) == ingest.extract_document(path, profile)


def test_reading_order_is_worked_out_from_position_alone():
    block = lambda x0, y0, x1, y1: {"bbox": (x0, y0, x1, y1)}
    title, left_a, left_b = block(50, 70, 540, 90), block(50, 100, 280, 200), block(50, 210, 280, 300)
    right_a, wide, left_c, right_c = block(310, 100, 540, 300), block(50, 320, 540, 340), block(50, 350, 280, 400), block(310, 350, 540, 400)

    ordered = ingest.reading_order([right_c, wide, right_a, left_b, title, left_c, left_a], 295.0)

    assert ordered == [title, left_a, left_b, right_a, wide, left_c, right_c]


# --- footnotes at the foot of a column -----------------------------------------------


def test_a_footnote_at_the_foot_of_a_short_left_column_is_still_a_footnote(article):
    # No small type but the footnotes: a DOI line under the title is small and not at the foot.
    path, expected = article(short_left_column=True, footnote_lines=4, doi=None, year_line=None)
    measured = layout.measure(path)

    read = measured.evidence["body_min_size"]["sizes_below_body"]["8.0"]
    assert read["read_as"] == "footnote apparatus (sits at the foot of the column)"
    assert read["of_which_at_the_foot_of_the_column"] == read["blocks_on_pages_with_body_text"]
    assert measured.layout.body_min_size == 10.0
    assert not any("noteword" in page.body for page in ingest.extract_document(path, measured.layout))

    # Where footnotes share the body floor and so survive extraction, the article writer's
    # footnote map must find them at the foot of their own column too.
    kept = dataclasses.replace(measured.layout, body_min_size=8.0)
    document = Document("article-fixture", "Fixture, A.", "2020", "FIXTURE", "FIXTURE", kept, path, path.parent, path.parent)
    found = footnotes.build(document)
    assert sorted(found.by_page) == expected["footnote_pages"] and found.count == len(expected["footnote_pages"])


# --- the upload stages, for an article -----------------------------------------------


@pytest.fixture
def analysed(library, article):
    path, expected = article()
    record = upload.receive(path.read_bytes(), "fixture-article.pdf", KIND_ARTICLE)
    return upload.analyse(record["document_id"]), expected


def test_an_article_gets_its_own_kind_of_id_and_the_same_file_is_not_taken_twice(library, article):
    path, _ = article()
    record = upload.receive(path.read_bytes(), "fixture-article.pdf", KIND_ARTICLE)

    assert record["kind"] == KIND_ARTICLE and record["document_id"] == "article-" + record["sha256"][:12]
    with pytest.raises(UploadRefused, match="already in the library"):
        upload.receive(path.read_bytes(), "the-same-file.pdf", KIND_THESIS)     # under either kind
    with pytest.raises(UploadRefused, match="one of: thesis, article"):
        upload.receive(path.read_bytes(), "fixture.pdf", "book")


def test_an_articles_reference_list_is_tagged_apparatus_by_its_own_heading(library, analysed):
    record, _ = analysed
    profile = LayoutProfile.from_json(record["layout"])
    document = upload.as_document(record)
    _, _, chunks = upload.extract_and_chunk(document)

    assert record["state"] == upload.AWAITING_REVIEW
    assert (profile.columns, profile.apparatus_section_prefixes) == (2, ("References",))
    listed = [chunk for chunk in chunks if "refword" in chunk["text"]]
    assert listed and all(chunk["kind"] == "apparatus" and chunk["section"] == "References" for chunk in listed)
    assert all(chunk["kind"] == "source" for chunk in chunks if "refword" not in chunk["text"])
    assert all(chunk["chapter"] is None for chunk in chunks)                   # no chapter is invented


def test_a_references_heading_inside_a_thesis_chapter_changes_nothing(tmp_path):
    path = tmp_path / "thesis.pdf"
    make_thesis(path, ThesisSpec())
    analysis = upload.analyse_pdf(path, "thesis-fixture")

    assert analysis["layout"].apparatus_section_prefixes == ()
    assert analysis["measurement"].evidence["apparatus_section_prefixes"]["applies"] is False


def test_an_articles_identity_is_proposed_from_its_first_page_and_never_adopted(analysed):
    record, _ = analysed
    proposal = record["identity_proposal"]

    assert proposal["title"]["value"] == "FIXTURE Article On Synthetic Canals"
    assert proposal["author"]["value"] == "Fixture Author and Second Fixture"
    assert "under the title" in proposal["author"]["source"] and "check the form" in proposal["author"]["source"]
    assert proposal["year"]["value"] == "2020"
    assert proposal["doi"] == {"value": "10.5555/fixture.2020.001", "source": "a DOI printed on PDF page 1"}
    assert record["identity"]["confirmed"] is False and record["identity"]["doi"] == ""
    with pytest.raises(UploadRefused, match="Confirm the author, year and title"):
        upload.approve(record["document_id"])


def test_an_article_without_a_printed_doi_or_authors_gets_empty_proposals_with_the_reason(article):
    path, _ = article(doi=None, authors=None, year_line=None)
    proposal = identity.propose(path, KIND_ARTICLE)

    assert proposal["doi"] == {"value": "", "source": "no DOI is printed on the first page"}
    assert proposal["author"]["value"] == "" or "FIXTURE" in proposal["author"]["value"]
    assert identity.propose(path)["author"]["source"] == 'no line beginning "by" was found on the title page'


def test_the_confirmed_identity_of_an_article_makes_its_source_line(analysed):
    record, _ = analysed
    key = record["document_id"]
    with pytest.raises(UploadRefused, match="shape of a DOI"):
        upload.confirm_identity(key, **IDENTITY, doi="see the publisher's page")
    with pytest.raises(UploadRefused, match="as printed on the first page"):
        upload.confirm_identity(key, **{**IDENTITY, "year": "20"})

    confirmed = upload.confirm_identity(key, **IDENTITY, **PUBLISHED)
    document = upload._provisional_document(confirmed, LayoutProfile.from_json(confirmed["layout"]))

    assert confirmed["identity"]["doi"] == "10.5555/fixture.2020.001"           # the resolver prefix is not part of it
    assert document.kind == KIND_ARTICLE
    assert document.reference() == ("Fixture, A. and Fixture, S. (2020), FIXTURE Article On Synthetic Canals, "
                                    "FIXTURE Journal of Synthetic Studies 12(3), 101–104. doi:10.5555/fixture.2020.001")
    bare = upload.confirm_identity(key, **IDENTITY)
    assert upload._provisional_document(bare, None).reference() == (
        "Fixture, A. and Fixture, S. (2020), FIXTURE Article On Synthetic Canals")


def test_a_thesis_record_from_before_articles_still_loads_as_a_thesis(library, tmp_path):
    path = tmp_path / "thesis.pdf"
    make_thesis(path, ThesisSpec())
    record = upload.analyse(upload.receive(path.read_bytes(), "fixture-thesis.pdf")["document_id"])
    stored = library.path / record["document_id"] / "record.json"
    old = json.loads(stored.read_text(encoding="utf-8"))
    old.pop("kind")
    for added in ("container", "volume_issue", "pages", "doi"):
        old["identity"].pop(added)
    stored.write_text(json.dumps(old), encoding="utf-8")

    document = upload.as_document(upload.load(record["document_id"]))

    assert (document.kind, document.container, document.doi) == (KIND_THESIS, "", "")
    assert default_document(ask.settings).kind == KIND_THESIS


# --- the audit -----------------------------------------------------------------------


def test_the_audit_passes_a_clean_article_and_names_pages_whose_order_is_unclear(library, analysed, article):
    record, _ = analysed
    result = upload.read_audit(record["document_id"])

    assert result["hard_stops"] == [] and result["columns"] == {"count": 2, "pages_where_reading_order_is_unclear": []}
    assert result["chunks"]["words_on_claimed_pages"]["failing"] == []
    assert result["labels_printed_on_their_page"]["failing"] == []
    assert "COLUMNS — two, read down the left and then the right" in audit_module.format_report(result)

    path, _ = article(wide_figure_beside_text=True)
    analysis = upload.analyse_pdf(path, "article-fixture")
    report = audit_module.format_report(analysis["audit"])
    assert analysis["audit"]["columns"]["pages_where_reading_order_is_unclear"] == [2]
    assert analysis["audit"]["hard_stops"] == []                               # raised for the researcher; it does not decide
    assert "pages where the order is unclear   2" in report and "before citing them" in report


def test_an_audit_made_before_articles_is_still_reported(analysed):
    record, _ = analysed
    result = upload.read_audit(record["document_id"])
    result.pop("columns")

    assert "COLUMNS" not in audit_module.format_report(result)


# --- an ingested article answers with its own identity -------------------------------


def test_an_indexed_article_is_cited_by_its_own_author_section_and_printed_page(library, analysed, monkeypatch):
    record, _ = analysed
    key = record["document_id"]
    upload.confirm_identity(key, **IDENTITY, **PUBLISHED)
    upload.approve(key)
    upload.build_index(key, cost_accepted=True)
    document = upload.find_document(key)
    vectors, chunks, _ = ask.load_index(document)
    monkeypatch.setattr(ask, "embed_texts", library.embed if hasattr(library, "embed") else ask.embed_texts)
    target = next(chunk for chunk in chunks if "left3x0" in chunk["text"])

    note = ask.footnote(1, ask.EvidenceItem("E1", target, 0.5, document))

    assert document.kind == KIND_ARTICLE and target["chunk_id"].startswith(key + "::")
    assert note.startswith("1. Fixture, A. and Fixture, S. (2020), § ")
    assert re.search(r"pp?\. 10[1-4]", note) and "None" not in note
    assert [d.document_id for d in upload.ready_documents()] == [key]


# =====================================================================================
# What two real articles showed (ADR 0015, "calibrated on real articles")
#
# These fixtures reproduce, with synthetic text, five things real journal PDFs did that
# the first synthetic article did not: lines of body text a hair smaller than the rest,
# furniture that differs between left- and right-hand pages, a page number inside a
# footer line, a form appended with its own numbering, and a stamp turned on its side.
# =====================================================================================


def test_a_line_of_body_text_set_a_hair_smaller_is_not_dropped(article):
    path, expected = article(line_jitter=True)
    measured = layout.measure(path)
    pages = ingest.extract_document(path, measured.layout)

    read = measured.evidence["body_min_size"]["sizes_below_body"]["9.9"]
    assert read["read_as"] == "body text" and read["share_of_characters"] < layout.MINOR_SIZE_SHARE
    assert read["share_inside_blocks_of_body_text"] >= layout.NEAR_BODY_IN_BLOCK
    assert measured.layout.body_min_size == 9.9
    assert [f"jitterword{n}" in pages[n - 1].body for n in range(1, 5)] == [True] * 4      # no line is lost
    assert [tags(page) for page in pages] == [expected["order"][n] for n in range(1, 5)]


def test_text_close_to_the_body_size_but_set_apart_from_it_is_not_body_text(article):
    path, expected = article(line_jitter=True, panel_letters=True, appended_form_pages=2)
    measured = layout.measure(path)
    pages = ingest.extract_document(path, measured.layout)

    read = measured.evidence["body_min_size"]["sizes_below_body"]["9.8"]
    assert read["share_of_characters"] >= layout.MINOR_SIZE_SHARE          # too much text to dismiss by its amount
    assert read["read_as"] == "apparatus (close to the body size, but set apart from the body text)"
    assert measured.layout.body_min_size == 9.9
    assert not any(line.strip() in {"a", "b"} for page in pages for line in page.body.split("\n"))
    assert not any("formword" in page.body for page in pages)
    assert all(f"jitterword{n}" in pages[n - 1].body for n in range(1, 5))


def test_furniture_that_differs_between_left_and_right_pages_is_still_furniture(article):
    path, expected = article(journal_furniture=True, pages=8)
    measured = layout.measure(path)
    profile = measured.layout
    pages = ingest.extract_document(path, profile)

    assert profile.header_band_y is not None and profile.footnote_band_y is not None
    assert not any("FIXTURE Running Head" in title for page in pages for _, _, title in page.headings)
    assert not any("FIXTURE Running Head" in page.body or "Vol 12" in page.body for page in pages)
    assert [page.running_header for page in pages] == [None, "FIXTURE Running Head"] * 4      # printed on left-hand pages only
    analysis = upload.analyse_pdf(path, "article-fixture")
    assert all("FIXTURE Running Head" not in (chunk["chapter"] or "") for chunk in analysis["records"])

    # Seven pages: the running head is on three of them, fewer than half of all pages but
    # every left-hand one. It is furniture all the same.
    odd, _ = article(journal_furniture=True, pages=7)
    seven = layout.measure(odd)
    assert seven.evidence["header_band_y"]["pages_with_header_furniture"] == 3
    assert seven.layout.header_band_y is not None
    assert not any("FIXTURE Running Head" in page.body for page in ingest.extract_document(odd, seven.layout))


def test_a_page_number_inside_a_footer_line_is_read_and_checked_against_the_page(article):
    path, expected = article(journal_furniture=True, pages=8)
    measured = layout.measure(path)
    profile = measured.layout
    pages = ingest.extract_document(path, profile)
    found = measured.evidence["page_number_band"]

    assert (profile.page_number_band, profile.page_number_inline, profile.page_label_offset) == ("footer", True, 100)
    assert found["pages_agreeing"] == 8 and found["printed_minus_pdf_page"] == 100
    assert {page.pdf_page: page.printed_page for page in pages} == expected["labels"]     # "2021" is never the page
    assert not any("No printed page number" in flag for flag in measured.flags)
    result = upload.analyse_pdf(path, "article-fixture")["audit"]
    assert result["labels_printed_on_their_page"] == {"n": 8, "N": 8, "failing": []}
    assert result["chunks"]["page_labels_match_the_pdf"]["failing"] == []


def test_a_form_appended_with_its_own_numbering_gets_no_page_of_the_article(article):
    path, expected = article(journal_furniture=True, pages=6, appended_form_pages=2)
    profile = layout.measure(path).layout
    pages = ingest.extract_document(path, profile)

    assert profile.page_label_offset == 100                               # six of eight pages agree; that is enough
    assert [page.printed_page for page in pages[:6]] == ["101", "102", "103", "104", "105", "106"]
    assert [page.printed_page for page in pages[6:]] == [None, None]      # its "1" and "2" are not pages 1 and 2 of this


def test_a_number_in_a_furniture_line_is_taken_only_where_it_matches_the_page():
    profile = dataclasses.replace(default_layout(ask.settings), page_number_inline=True, page_label_offset=582)

    assert ingest.inline_label("584 | FIXTURE Journal | Vol 596 | 26 August 2021", 2, profile) == (
        "584", "FIXTURE Journal | Vol 596 | 26 August 2021")
    assert ingest.inline_label("FIXTURE Journal | Vol 596 | 26 August 2021 | 585", 3, profile) == (
        "585", "FIXTURE Journal | Vol 596 | 26 August 2021")
    assert ingest.inline_label("584 | FIXTURE Journal | Vol 596 | 26 August 2021", 9, profile)[0] is None
    assert ingest.inline_label("FIXTURE Journal 584 Vol 596", 2, profile)[0] is None       # not at an end of the line
    assert ingest.inline_label("584 | FIXTURE", 2, default_layout(ask.settings))[0] is None  # the built-in profile reads none
    assert layout.edge_numbers("584 | FIXTURE Journal | 26 August 2021") == ["584", "2021"]
    assert layout.furniture_key("584 | FIXTURE Journal | Vol 12") == layout.furniture_key("586 | FIXTURE Journal | Vol 12")
    assert layout.furniture_key("FIXTURE Chapter Alpha") == "FIXTURE Chapter Alpha"


def test_a_stamp_turned_on_its_side_is_neither_the_title_nor_a_heading(article):
    path, _ = article(margin_stamp=True)
    profile = layout.measure(path).layout
    pages = ingest.extract_document(path, profile)
    proposal = identity.propose(path, KIND_ARTICLE)

    assert proposal["title"]["value"] == "FIXTURE Article On Synthetic Canals"
    assert not any("fixture:1810" in title for page in pages for _, _, title in page.headings)
    assert not any("fixture:1810" in page.body for page in pages)
    assert proposal["year"]["value"] == "2020"                            # the stamp's 2031 is not read at all


def test_an_articles_year_is_the_latest_on_its_first_page_not_a_work_it_cites(article):
    path, _ = article(cited_year="1953")

    proposed = identity.propose(path, KIND_ARTICLE)["year"]
    assert proposed == {"value": "2020", "source": "the latest year printed on PDF page 1"}
    assert identity.propose(path)["year"]["source"] == "the last year printed on PDF page 1"   # a thesis: as before


def test_an_articles_top_level_heading_is_cited_as_a_section_not_a_chapter(tmp_path):
    chunk = {"chunk_id": "article-x::00000::f", "document_id": "article-x", "kind": "source", "chapter": "3 FIXTURE Method",
             "section": "3.1 FIXTURE Detail", "page_start": "585", "page_end": "586", "pdf_page_start": 3,
             "pdf_page_end": 4, "pages_unresolved": [], "text": "FIXTURE"}
    article_doc = Document("article-x", "Fixture, A.", "2021", "T", "T", None, tmp_path, tmp_path, tmp_path, kind=KIND_ARTICLE)
    thesis_doc = dataclasses.replace(article_doc, kind=KIND_THESIS)

    assert ask.footnote(1, ask.EvidenceItem("E1", chunk, 0.0, article_doc)) == (
        "1. Fixture, A. (2021), § 3 FIXTURE Method, § 3.1 FIXTURE Detail, pp. 585–586.")
    assert ask.footnote(1, ask.EvidenceItem("E1", chunk, 0.0, thesis_doc)) == (
        "1. Fixture, A. (2021), Ch. “3 FIXTURE Method”, § 3.1 FIXTURE Detail, pp. 585–586.")


def test_the_builtin_profile_reads_no_number_out_of_a_line_and_old_profiles_still_load():
    builtin = default_layout(ask.settings)
    assert (builtin.page_number_inline, builtin.page_label_offset) == (False, None)
    stored = builtin.to_json()
    stored.pop("page_number_inline"), stored.pop("page_label_offset")
    assert LayoutProfile.from_json(stored) == builtin
