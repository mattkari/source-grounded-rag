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
