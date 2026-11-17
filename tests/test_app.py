"""The web UI's thesis library and document picker — `app.py` (PLAN_V4 §12).

Driven through Streamlit's own test harness: the real `app.py` runs, with a
temporary library, the offline embedding fake, and the generation model
replaced at `ask.call_model`. No browser and no network.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from streamlit.testing.v1 import AppTest

import ask
import runs
import upload
from config import ROOT, settings
from pdf_factory import ThesisSpec, make_thesis

BUILTIN_LABEL = f"{settings.document_short_title} (built-in)"
UPLOAD_SHORT_TITLE = "Fixture, A. (2001), FIXTURE Thesis On Synthetic Lighthouses"


def button(at: AppTest, label: str):
    matches = [b for b in at.button if b.label == label]
    assert matches, f"no button labelled {label!r}; found {[b.label for b in at.button]}"
    return matches[0]


def text_input(at: AppTest, prefix: str):
    return next(t for t in at.text_input if t.label.startswith(prefix))


def all_text(at: AppTest) -> str:
    parts = []
    for kind in ("title", "header", "subheader", "markdown", "caption", "info", "warning", "error", "success", "code"):
        parts += [str(element.value) for element in getattr(at, kind)]
    return "\n".join(parts)


@pytest.fixture
def app(tmp_path, monkeypatch, library):
    """The app, pointed at an empty library and an empty run history."""
    monkeypatch.setattr(runs, "settings", dataclasses.replace(runs.settings, runs_path=tmp_path / "runs.jsonl"))
    pdf = tmp_path / "upload.pdf"
    make_thesis(pdf, ThesisSpec())

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.thesis_pdf = pdf.read_bytes()
    return at.run()


def open_library(at: AppTest) -> AppTest:
    at.radio[0].set_value("Thesis library")
    return at.run()


def add_thesis(at: AppTest) -> AppTest:
    open_library(at)
    at.file_uploader[0].upload("fixture-thesis.pdf", at.thesis_pdf, "application/pdf")
    at.run()
    button(at, "Add to the library").click()
    return at.run()


def confirm_and_approve(at: AppTest) -> AppTest:
    text_input(at, "Author").set_value("Fixture, A.")
    button(at, "Confirm identity").click()
    at.run()
    button(at, "Approve").click()
    return at.run()


def index_thesis(at: AppTest) -> AppTest:
    next(c for c in at.checkbox if c.label == "I accept this cost").check()
    at.run()
    button(at, "Embed and index").click()
    return at.run()


# ---------------------------------------------------------------------------


def test_the_view_and_thesis_are_chosen_on_the_page_not_in_the_sidebar(app):
    """On a phone the sidebar opens as a panel over the page and stays open after a
    choice, so controls under it (such as "I accept this cost") could not be tapped.
    Every control needed to move between views lives on the page itself."""
    assert not app.exception
    assert len(app.sidebar.radio) == 0
    assert len(app.sidebar.selectbox) == 0
    assert app.radio[0].options == ["Ask", "Library", "Write"]
    assert app.selectbox[0].label == "Thesis"


def test_the_builtin_thesis_is_the_default_and_carries_no_unevaluated_notice(app):
    assert not app.exception
    assert app.selectbox[0].options == [BUILTIN_LABEL]
    assert app.header[0].value.startswith(settings.document_short_title)
    assert "not evaluated" not in all_text(app)


def test_an_empty_library_says_so(app):
    open_library(app)

    assert app.title[0].value == "Thesis library"
    assert "No thesis has been uploaded yet. The built-in thesis is always available." in all_text(app)
    assert "Nothing is sent for embedding, and nothing is spent, until you approve." in all_text(app)


def test_an_uploaded_thesis_is_analysed_and_shown_with_its_audit_for_review(app, library):
    add_thesis(app)
    text = all_text(app)
    (record,) = upload.list_records()

    assert not app.exception
    assert record["state"] == upload.AWAITING_REVIEW
    assert "analysed — waiting for your review" in text
    assert "Audit of the extraction against the PDF" in text
    assert "every word on the claimed pages" in text
    assert "Nothing here blocks approval. Whether it is good enough is your decision." in text
    assert "There is no pass mark: you judge the report." in text
    assert library.embedded == []


def test_the_identity_is_prefilled_from_the_title_page_and_approval_waits_for_it(app):
    add_thesis(app)

    assert text_input(app, "Author").value == "Fixture Author"
    assert text_input(app, "Year").value == "2001"
    assert text_input(app, "Title").value == "FIXTURE Thesis On Synthetic Lighthouses"
    assert 'Author — proposed from the line beginning "by" on PDF page 1.' in all_text(app)
    assert button(app, "Approve").disabled is True

    text_input(app, "Author").set_value("Fixture, A.")
    button(app, "Confirm identity").click()
    app.run()

    assert "Confirmed: Fixture, A. (2001), FIXTURE Thesis On Synthetic Lighthouses" in all_text(app)
    assert button(app, "Approve").disabled is False
    assert upload.list_records()[0]["identity"]["confirmed"] is True


def test_embedding_waits_for_the_cost_to_be_accepted(app, library):
    add_thesis(app)
    confirm_and_approve(app)
    text = all_text(app)

    assert "approved — not yet indexed" in text
    assert "Embedding cost." in text and "tokens" in text
    assert "no price is configured" in text
    assert button(app, "Embed and index").disabled is True
    assert library.embedded == []

    index_thesis(app)

    assert upload.list_records()[0]["state"] == upload.READY
    assert len(library.embedded) == upload.list_records()[0]["audit_summary"]["chunks_total"]
    assert "ingested and audited — not evaluated" in all_text(app)


def test_a_ready_thesis_joins_the_picker_and_is_labelled_not_evaluated_when_active(app):
    add_thesis(app)
    confirm_and_approve(app)
    index_thesis(app)

    assert app.selectbox[0].options == [BUILTIN_LABEL, UPLOAD_SHORT_TITLE]
    assert app.selectbox[0].value == settings.document_id   # still the built-in until chosen

    button(app, "Ask questions of this thesis").click()
    app.run()

    assert not app.exception
    assert app.title[0].value == "Source-Grounded Research Assistant"
    assert app.header[0].value.startswith(UPLOAD_SHORT_TITLE)
    assert "Ingested and audited — **not evaluated**." in all_text(app)


def test_a_question_to_an_uploaded_thesis_is_cited_and_recorded_under_that_thesis(app, monkeypatch):
    add_thesis(app)
    confirm_and_approve(app)
    index_thesis(app)
    button(app, "Ask questions of this thesis").click()
    app.run()

    def scripted(question, items):
        return {
            "evidence_sufficiency": "sufficient",
            "answer": "FIXTURE answer from the uploaded thesis [E1].",
            "limitations": [], "ai_interpretation": [], "unsupported_by_evidence": [],
            "citations_used": ["E1"],
        }, ask._get_prompt()[1]

    monkeypatch.setattr(ask, "call_model", scripted)
    app.chat_input[0].set_value("FIXTURE: where did the lighthouse stand?")
    app.run()

    document_id = upload.list_records()[0]["document_id"]
    (record,) = [json.loads(line) for line in runs.settings.runs_path.read_text(encoding="utf-8").splitlines()]
    text = all_text(app)

    assert not app.exception
    assert "FIXTURE answer from the uploaded thesis ¹." in text.replace("\u00a0", " ")
    assert "1. Fixture, A. (2001), " in text
    assert f"{settings.document_author} ({settings.document_year})" not in text
    assert record["document_id"] == document_id
    assert all(e["chunk_id"].startswith(document_id) for e in record["evidence"])

    # The built-in thesis has its own, separate conversation.
    app.selectbox[0].set_value(settings.document_id)
    app.run()
    assert "FIXTURE answer from the uploaded thesis" not in all_text(app)
    assert "No questions yet." in "\n".join(c.value for c in app.sidebar.caption)


def test_a_refused_upload_is_explained_in_plain_words(app):
    open_library(app)
    app.file_uploader[0].upload("notes.pdf", b"FIXTURE this is not a pdf", "application/pdf")
    app.run()
    button(app, "Add to the library").click()
    app.run()

    assert not app.exception
    assert [e.value for e in app.error] == ["This file is not a PDF."]
    assert upload.list_records() == []


def test_a_rejected_thesis_shows_its_reason_and_offers_no_way_to_index_it(app, library):
    add_thesis(app)
    text_input(app, "Reason for rejecting").set_value("FIXTURE: too many unnumbered pages")
    button(app, "Reject").click()
    app.run()

    assert upload.list_records()[0]["state"] == upload.REJECTED
    assert "Rejected. Reason recorded: FIXTURE: too many unnumbered pages" in all_text(app)
    assert "Embed and index" not in [b.label for b in app.button]
    assert library.embedded == []


def test_removing_a_thesis_needs_a_tick_and_then_deletes_it(app, library):
    add_thesis(app)
    assert button(app, "Remove").disabled is True

    next(c for c in app.checkbox if c.label == "Yes, delete all three").check()
    app.run()
    button(app, "Remove").click()
    app.run()

    assert upload.list_records() == []
    assert not any(p.is_dir() for p in library.path.iterdir())
    assert "No thesis has been uploaded yet." in all_text(app)


def test_ticking_the_cost_box_does_not_re_extract_the_thesis(app, monkeypatch):
    """The estimate re-reads the whole PDF. Done on every redraw, a tick on a slow
    machine looks like a box that does not work."""
    add_thesis(app)
    confirm_and_approve(app)
    calls = []
    real = upload.estimate_cost
    monkeypatch.setattr(upload, "estimate_cost", lambda key: calls.append(key) or real(key))
    app.run()
    counted = len(calls)

    box = next(c for c in app.checkbox if c.label == "I accept this cost")
    box.check()
    app.run()
    app.run()

    assert next(c for c in app.checkbox if c.label == "I accept this cost").value is True
    assert button(app, "Embed and index").disabled is False
    assert len(calls) == counted <= 1                  # redraws reuse the estimate already shown


def test_the_ask_view_never_shows_a_raw_handle_and_says_the_answer_is_not_grounded(app, monkeypatch):
    """A combined handle from the model (ADR 0006): rejected by validation, and the
    bracket itself is not put in front of the reader."""
    from test_article_app import offline_embedding

    monkeypatch.setattr(ask, "embed_texts", offline_embedding)
    monkeypatch.setattr(ask, "call_model", lambda question, items: ({
        "evidence_sufficiency": "sufficient",
        "answer": "FIXTURE one thing [E1]. FIXTURE virtue arises from balance [E1, E2].",
        "limitations": [], "ai_interpretation": ["FIXTURE a reading [E1; E2]."], "unsupported_by_evidence": [],
        "citations_used": ["E1", "E2"]}, "fixturehash"))
    app.chat_input[0].set_value("FIXTURE: what does the harbour ledger say?")
    app.run()
    # What a reader is shown. The evaluators' technical section is apart: it quotes the
    # rejected bracket inside the validation failure, which is what it is for.
    technical = ("malformed_handle", "Retrieval diagnostics", "<style>")
    answer_text = "\n".join(str(e.value) for e in [*app.markdown, *app.info]
                            if not any(mark in str(e.value) for mark in technical))
    assert any("malformed_handle" in str(m.value) for m in app.markdown)       # the failure is on record, in plain sight
    (record,) = [json.loads(line) for line in runs.settings.runs_path.read_text(encoding="utf-8").splitlines()]

    assert not app.exception
    assert "[E1, E2]" not in answer_text and "[E1; E2]" not in answer_text
    assert f"FIXTURE virtue arises from balance {ask.UNRESOLVED_NOTE}." in answer_text
    assert "FIXTURE one thing\u00a0¹." in answer_text.replace(" ¹", "\u00a0¹")   # the good note still resolves
    assert "did not pass the automatic grounding checks" in all_text(app)
    assert any(f.startswith("malformed_handle:") for f in record["validation_failures"])


def test_an_article_is_added_as_an_article_and_its_publication_details_are_confirmed(app, library, tmp_path):
    from pdf_factory import make_article

    pdf = tmp_path / "article.pdf"
    make_article(pdf)
    open_library(app)
    next(radio for radio in app.radio if radio.label == "What is this document?").set_value("article")
    app.run()
    app.file_uploader[0].upload("fixture-article.pdf", pdf.read_bytes(), "application/pdf")
    app.run()
    button(app, "Add to the library").click()
    app.run()
    (record,) = upload.list_records()

    assert not app.exception
    assert record["kind"] == "article" and record["document_id"].startswith("article-")
    assert "COLUMNS — two, read down the left and then the right" in all_text(app)
    assert text_input(app, "DOI").value == "10.5555/fixture.2020.001"
    assert "DOI — proposed from a DOI printed on PDF page 1." in all_text(app)
    assert button(app, "Approve").disabled is True                        # nothing is cited until confirmed

    text_input(app, "Author").set_value("Fixture, A.")
    text_input(app, "Journal").set_value("FIXTURE Journal of Synthetic Studies")
    button(app, "Confirm identity").click()
    app.run()

    assert ("Confirmed: Fixture, A. (2020), FIXTURE Article On Synthetic Canals, FIXTURE Journal of Synthetic Studies. "
            "doi:10.5555/fixture.2020.001") in all_text(app)
    assert button(app, "Approve").disabled is False and library.embedded == []
