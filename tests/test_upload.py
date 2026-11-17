"""The stages of an upload — `upload.py` (PLAN_V4 §5, §6, §10, §11).

Everything runs against a temporary library folder with the offline embedding
fake. The generation model is replaced only where a question is asked, at
`ask.call_model`, as in the E1 suite.
"""

from __future__ import annotations

import json

import pytest

import ask
import audit as audit_module
import upload
from config import settings
from documents import default_document
from pdf_factory import ThesisSpec, make_blank_pdf, make_encrypted_pdf, make_thesis
from upload import UploadRefused

IDENTITY = {"author": "Fixture, A.", "year": "2001", "title": "FIXTURE Thesis On Synthetic Lighthouses"}


@pytest.fixture
def thesis_bytes(tmp_path):
    def build(**spec) -> bytes:
        path = tmp_path / "upload.pdf"
        make_thesis(path, ThesisSpec(**spec))
        return path.read_bytes()

    return build


@pytest.fixture
def received(library, thesis_bytes):
    return upload.receive(thesis_bytes(), "fixture-thesis.pdf")


@pytest.fixture
def analysed(received):
    return upload.analyse(received["document_id"])


@pytest.fixture
def approved(analysed):
    upload.confirm_identity(analysed["document_id"], **IDENTITY)
    return upload.approve(analysed["document_id"])


@pytest.fixture
def ready(approved):
    return upload.build_index(approved["document_id"], cost_accepted=True)


def folder(library, record):
    return library.path / record["document_id"]


def refusals(library) -> list[dict]:
    log = library.path / "upload_log.jsonl"
    if not log.exists():
        return []
    return [e for e in map(json.loads, log.read_text(encoding="utf-8").splitlines()) if e["event"] == "refused"]


# ---------------------------------------------------------------------------
# Stage 1–2: receive and pre-flight
# ---------------------------------------------------------------------------


def test_a_thesis_is_stored_byte_for_byte_under_an_id_derived_from_its_hash(library, thesis_bytes):
    data = thesis_bytes()
    record = upload.receive(data, "fixture-thesis.pdf")

    assert record["document_id"] == "thesis-" + record["sha256"][:12]
    assert (folder(library, record) / "source.pdf").read_bytes() == data
    assert record["state"] == upload.RECEIVED
    assert record["pages_total"] == 21
    assert record["identity"]["confirmed"] is False
    assert upload.load(record["document_id"]) == record


def test_a_path_in_the_uploaded_filename_is_not_trusted(library, thesis_bytes):
    record = upload.receive(thesis_bytes(), "../../etc/fixture-thesis.pdf")
    assert record["source_filename"] == "fixture-thesis.pdf"


@pytest.mark.parametrize(
    "make, reason",
    [
        (lambda path: path.write_bytes(b"FIXTURE not a pdf at all"), "This file is not a PDF."),
        (make_encrypted_pdf, "This PDF is password-protected. Remove the protection and upload it again."),
        (make_blank_pdf, "This PDF has no text layer — it is a scan. Scanned documents need OCR, "
                         "which is outside what this system does."),
    ],
    ids=["not-a-pdf", "encrypted", "scan"],
)
def test_a_file_that_cannot_be_ingested_is_refused_and_leaves_nothing_behind(library, tmp_path, make, reason):
    path = tmp_path / "bad.pdf"
    make(path)

    with pytest.raises(UploadRefused) as refused:
        upload.receive(path.read_bytes(), "bad.pdf")

    assert str(refused.value) == reason
    assert upload.list_records() == []
    assert [p.name for p in library.path.iterdir()] == ["upload_log.jsonl"]
    assert [(e["filename"], e["reason"]) for e in refusals(library)] == [("bad.pdf", reason)]


def test_the_same_pdf_is_never_ingested_twice(library, received):
    same_bytes = (folder(library, received) / "source.pdf").read_bytes()

    with pytest.raises(UploadRefused) as refused:
        upload.receive(same_bytes, "the-same-file-renamed.pdf")

    assert str(refused.value) == (
        "This PDF is already in the library (received — not yet analysed). "
        "Remove it first to ingest it again."
    )
    assert len(upload.list_records()) == 1


def test_the_builtin_thesis_cannot_be_uploaded(library, monkeypatch, tmp_path, thesis_bytes):
    builtin_pdf = tmp_path / "builtin.pdf"
    builtin_pdf.write_bytes(thesis_bytes(title="FIXTURE The Built In Thesis"))
    import dataclasses

    monkeypatch.setattr(upload, "settings", dataclasses.replace(upload.settings, pdf_path=builtin_pdf))

    with pytest.raises(UploadRefused) as refused:
        upload.receive(builtin_pdf.read_bytes(), "copy.pdf")

    assert str(refused.value) == "This is the built-in thesis. It is already available and is kept frozen."
    assert upload.list_records() == []


# ---------------------------------------------------------------------------
# Stages 3–6: measure, dry run, audit, identity proposal
# ---------------------------------------------------------------------------


def test_analysis_measures_extracts_audits_and_then_waits_for_the_researcher(library, analysed):
    home = folder(library, analysed)

    assert analysed["state"] == upload.AWAITING_REVIEW
    assert analysed["layout"]["chapter_source"] == "running_header"
    assert analysed["layout"]["apparatus_chapter_prefixes"] == ["Bibliography"]
    assert analysed["layout_evidence"]["body_size"]["rule"]
    assert analysed["audit_summary"]["hard_stops"] == []
    assert len(analysed["audited_corpus_sha256"]) == 64
    assert [(h["stage"], h["outcome"]) for h in analysed["history"]] == [
        ("receive", "stored"), ("measure", "done"), ("dry run", "done"),
        ("audit", "done"), ("identity", "proposed"),
    ]
    assert (home / "canonical" / "pages.jsonl").exists()
    assert upload.read_audit(analysed["document_id"])["chunks"]["total"] == analysed["audit_summary"]["chunks_total"]


def test_nothing_is_embedded_or_indexed_before_approval(library, analysed):
    upload.confirm_identity(analysed["document_id"], **IDENTITY)

    assert library.embedded == []
    assert not (folder(library, analysed) / "index").exists()


def test_the_identity_is_proposed_but_not_adopted(analysed):
    assert analysed["identity_proposal"]["author"]["value"] == "Fixture Author"
    assert analysed["identity_proposal"]["year"]["value"] == "2001"
    assert analysed["identity"] == {"author": "", "year": "", "title": "", "short_title": "", "container": "",
                                    "volume_issue": "", "pages": "", "doi": "", "confirmed": False}


def test_the_canonical_extraction_is_written_once(library, analysed):
    """Hard rule 7: analysing again must not rewrite it."""
    record = upload.load(analysed["document_id"])
    record["state"] = upload.RECEIVED
    upload._save(record)
    before = (folder(library, analysed) / "canonical" / "pages.jsonl").read_bytes()

    with pytest.raises(UploadRefused):
        upload.analyse(analysed["document_id"])

    assert (folder(library, analysed) / "canonical" / "pages.jsonl").read_bytes() == before
    assert upload.load(analysed["document_id"])["state"] == upload.BLOCKED


def test_an_audit_hard_stop_blocks_the_thesis(library, received, monkeypatch):
    real_audit = audit_module.audit

    def failing_audit(*args, **kwargs):
        result = real_audit(*args, **kwargs)
        result["hard_stops"] = ["FIXTURE: 1 of 9 passages contain words that are not on the pages they claim."]
        return result

    monkeypatch.setattr(audit_module, "audit", failing_audit)
    record = upload.analyse(received["document_id"])

    assert record["state"] == upload.BLOCKED
    assert record["history"][-2]["outcome"] == "stopped"
    for step in (
        lambda: upload.confirm_identity(record["document_id"], **IDENTITY),
        lambda: upload.approve(record["document_id"]),
        lambda: upload.build_index(record["document_id"], cost_accepted=True),
    ):
        with pytest.raises(UploadRefused, match="cannot be used"):
            step()
    assert library.embedded == []


# ---------------------------------------------------------------------------
# Stages 6–7: identity and the decision
# ---------------------------------------------------------------------------


def test_a_thesis_cannot_be_approved_until_its_identity_is_confirmed(analysed):
    with pytest.raises(UploadRefused) as refused:
        upload.approve(analysed["document_id"])

    assert str(refused.value) == "Confirm the author, year and title before approving."
    assert upload.load(analysed["document_id"])["state"] == upload.AWAITING_REVIEW


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"author": "  "}, "Author and title are both needed before the thesis can be cited."),
        ({"title": ""}, "Author and title are both needed before the thesis can be cited."),
        ({"year": "01"}, "The year must be four digits, as printed on the title page."),
        ({"year": "c. 2001"}, "The year must be four digits, as printed on the title page."),
    ],
)
def test_an_incomplete_identity_is_not_accepted(analysed, overrides, reason):
    with pytest.raises(UploadRefused) as refused:
        upload.confirm_identity(analysed["document_id"], **{**IDENTITY, **overrides})

    assert str(refused.value) == reason
    assert upload.load(analysed["document_id"])["identity"]["confirmed"] is False


def test_the_confirmed_identity_is_recorded_with_when_and_by_whom(analysed):
    record = upload.confirm_identity(analysed["document_id"], author=" Fixture, A. ", year="2001",
                                     title=" FIXTURE Thesis On Synthetic Lighthouses ")
    who = record["identity"]

    assert (who["author"], who["year"], who["title"]) == (
        "Fixture, A.", "2001", "FIXTURE Thesis On Synthetic Lighthouses",
    )
    assert who["short_title"] == "Fixture, A. (2001), FIXTURE Thesis On Synthetic Lighthouses"
    assert who["confirmed"] is True and who["confirmed_at"]
    assert who["confirmed_via"] == "researcher, in the web UI"
    assert record["history"][-1]["outcome"] == "confirmed"


def test_a_rejected_thesis_leaves_no_index_and_cannot_be_indexed(library, analysed):
    record = upload.reject(analysed["document_id"], "FIXTURE: too many pages without a number")

    assert record["state"] == upload.REJECTED
    assert record["review"]["decision"] == "rejected"
    assert record["review"]["reason"] == "FIXTURE: too many pages without a number"
    with pytest.raises(UploadRefused, match="rejected"):
        upload.build_index(record["document_id"], cost_accepted=True)
    assert not (folder(library, record) / "index").exists()
    assert library.embedded == []
    assert upload.ready_documents() == []


# ---------------------------------------------------------------------------
# Stages 8–10: cost, index, ready
# ---------------------------------------------------------------------------


def test_the_cost_estimate_counts_tokens_and_never_assumes_a_price(library, approved):
    estimate = upload.estimate_cost(approved["document_id"])

    assert estimate["passages"] == approved["audit_summary"]["chunks_total"]
    assert estimate["tokens"] > estimate["passages"] * 40
    assert estimate["price_per_million_tokens"] is None
    assert estimate["estimated_cost"] is None
    assert library.embedded == []           # estimating spends nothing


def test_a_configured_price_turns_the_token_count_into_a_cost(library, approved, monkeypatch):
    import dataclasses

    monkeypatch.setattr(upload, "settings", dataclasses.replace(upload.settings, embedding_price_per_mtok=2.0))
    estimate = upload.estimate_cost(approved["document_id"])

    assert estimate["estimated_cost"] == round(estimate["tokens"] / 1_000_000 * 2.0, 4)


def test_embedding_needs_the_cost_to_be_accepted(library, approved):
    with pytest.raises(UploadRefused) as refused:
        upload.build_index(approved["document_id"], cost_accepted=False)

    assert str(refused.value) == "Embedding spends API credit. Accept the cost estimate first."
    assert library.embedded == []
    assert upload.load(approved["document_id"])["state"] == upload.APPROVED


def test_an_approved_thesis_is_indexed_with_its_confirmed_identity(library, ready):
    index = folder(library, ready) / "index"
    manifest = json.loads((index / "manifest.json").read_text(encoding="utf-8"))
    chunks = json.loads((index / "chunks.json").read_text(encoding="utf-8"))

    assert ready["state"] == upload.READY
    assert (index / "vectors.npy").exists()
    assert manifest["document_id"] == ready["document_id"]
    assert (manifest["document_author"], manifest["document_year"]) == ("Fixture, A.", "2001")
    assert manifest["corpus_text_sha256"] == ready["audited_corpus_sha256"]
    assert manifest["chunk_count"] == len(chunks) == len(library.embedded)
    assert all(c["chunk_id"].startswith(ready["document_id"] + "::") for c in chunks)
    # The short title heads each passage for embedding only, never the stored text.
    assert all(text.startswith("Fixture, A. (2001), FIXTURE Thesis") for text in library.embedded)
    assert not any("Fixture, A. (2001)" in c["text"] for c in chunks)


def test_a_provider_error_is_recorded_and_the_thesis_stays_approved(library, approved, monkeypatch):
    import ingest

    def outage(texts, **kwargs):
        raise ConnectionError("FIXTURE embedding outage")

    working = ingest.embed_texts
    monkeypatch.setattr(ingest, "embed_texts", outage)
    with pytest.raises(UploadRefused) as refused:
        upload.build_index(approved["document_id"], cost_accepted=True)

    record = upload.load(approved["document_id"])
    assert "Embedding failed (ConnectionError). Nothing was indexed." in str(refused.value)
    assert record["state"] == upload.APPROVED
    assert (record["history"][-1]["stage"], record["history"][-1]["outcome"]) == ("index", "failed")
    assert record["history"][-1]["detail"] == "ConnectionError: FIXTURE embedding outage"
    assert not (folder(library, record) / "index").exists()

    # Starting the stage again is the researcher's own, deliberate second attempt.
    monkeypatch.setattr(ingest, "embed_texts", working)
    assert upload.build_index(approved["document_id"], cost_accepted=True)["state"] == upload.READY


def test_what_is_indexed_must_be_what_was_audited(library, approved, thesis_bytes):
    """A PDF swapped after approval is never indexed under the approved audit."""
    (folder(library, approved) / "source.pdf").write_bytes(thesis_bytes(chapters=[("FIXTURE Other Thesis", 6)]))

    with pytest.raises(UploadRefused) as refused:
        upload.build_index(approved["document_id"], cost_accepted=True)

    assert str(refused.value).startswith("The extraction no longer matches the one that was audited")
    assert library.embedded == []
    assert not (folder(library, approved) / "index").exists()


# ---------------------------------------------------------------------------
# Asking a question of an uploaded thesis (PLAN_V4 §11)
# ---------------------------------------------------------------------------


def test_an_uploaded_thesis_answers_with_its_own_identity_in_the_citation(library, ready, monkeypatch):
    document = upload.find_document(ready["document_id"])
    vectors, chunks, manifest = ask.load_index(document)

    def scripted(question, items):
        payload = {
            "evidence_sufficiency": "sufficient",
            "answer": "FIXTURE answer drawn from the uploaded thesis [E1].",
            "limitations": [], "ai_interpretation": [], "unsupported_by_evidence": [],
            "citations_used": ["E1"],
        }
        scripted.evidence_block = ask.render_evidence_block(items)
        return payload, ask._get_prompt()[1]

    monkeypatch.setattr(ask, "call_model", scripted)
    outcome = ask.run_query("FIXTURE: where did the lighthouse stand?", vectors, chunks, 3, document)
    rendered = outcome.rendered()

    assert outcome.failures == []
    assert "1. Fixture, A. (2001), " in rendered
    assert f"{settings.document_author} ({settings.document_year})" not in rendered
    assert "[E1] Fixture, A. (2001), FIXTURE Thesis On Synthetic Lighthouses" in scripted.evidence_block
    assert settings.document_short_title not in scripted.evidence_block
    assert manifest["document_id"] == ready["document_id"]
    top = outcome.items[0].chunk
    assert f"p. {top['page_start']}" in rendered or f"pp. {top['page_start']}–{top['page_end']}" in rendered


def test_a_recorded_answer_is_re_rendered_under_the_thesis_it_came_from(library, ready):
    """History is rebuilt from disk; the citation must still name the right author."""
    import runs

    document = upload.find_document(ready["document_id"])
    _, chunks, _ = ask.load_index(document)
    record = {
        "question": "FIXTURE: where did the lighthouse stand?",
        "result": {"evidence_sufficiency": "sufficient", "answer": "FIXTURE recorded answer [E1].",
                   "limitations": [], "ai_interpretation": [], "unsupported_by_evidence": [],
                   "citations_used": ["E1"]},
        "evidence": [{"handle": "E1", "chunk_id": chunks[0]["chunk_id"], "score": 0.5}],
        "validation_failures": [],
        "prompt_sha256_12": "fixture",
    }

    outcome, unresolved = runs.as_outcome(record, chunks, document)

    assert unresolved == []
    assert "1. Fixture, A. (2001), " in outcome.rendered()
    assert settings.document_author not in outcome.rendered()


def test_the_builtin_thesis_is_still_the_default_and_keeps_its_own_identity(library, ready):
    assert upload.find_document(None) == default_document(settings)
    assert upload.find_document(settings.document_id).builtin is True
    assert ask.footnote(1, ask.EvidenceItem("E1", {
        "chapter": None, "section": None, "page_start": "3", "page_end": "3", "pdf_page_start": 26,
    }, 0.5)) == f"1. {settings.document_author} ({settings.document_year}), p. 3."


def test_a_thesis_that_is_not_ready_cannot_be_queried(approved):
    with pytest.raises(UploadRefused) as refused:
        upload.find_document(approved["document_id"])

    assert str(refused.value) == (
        f"{approved['document_id']} cannot be queried yet: it is 'approved — not yet indexed'."
    )


def test_only_ready_theses_are_offered_for_questions(library, ready, thesis_bytes):
    other = upload.receive(thesis_bytes(title="FIXTURE A Second Thesis"), "second.pdf")
    upload.analyse(other["document_id"])

    assert [d.document_id for d in upload.ready_documents()] == [ready["document_id"]]
    assert [r["document_id"] for r in upload.list_records()] == [ready["document_id"], other["document_id"]]


# ---------------------------------------------------------------------------
# Removal
# ---------------------------------------------------------------------------


def test_removing_a_thesis_deletes_its_pdf_extraction_and_index(library, ready):
    home = folder(library, ready)
    assert {p.name for p in home.iterdir()} == {"source.pdf", "record.json", "canonical", "audit.json", "index"}

    upload.remove(ready["document_id"])

    assert not home.exists()
    assert upload.list_records() == [] and upload.ready_documents() == []
    with pytest.raises(UploadRefused):
        upload.find_document(ready["document_id"])


def test_the_builtin_thesis_cannot_be_removed(library):
    with pytest.raises(UploadRefused) as refused:
        upload.remove(settings.document_id)

    assert str(refused.value) == "The built-in thesis is frozen and cannot be removed."
    assert settings.index_dir.joinpath("chunks.json").exists()


@pytest.mark.parametrize(
    "bad_id",
    ["../outside", "{upload}/../../outside", "not-a-thesis", "thesis-unknown0000"],
    ids=["parent-folder", "through-a-real-upload", "not-an-upload", "unknown-upload"],
)
def test_remove_only_ever_touches_an_upload_inside_the_library(library, received, tmp_path, bad_id):
    """`received` puts a real upload in the library, so the traversal paths do resolve."""
    bad_id = bad_id.format(upload=received["document_id"])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("FIXTURE", encoding="utf-8")
    assert (library.path / received["document_id"] / ".." / ".." / "outside" / "keep.txt").exists()
    # A folder inside the library that is not an upload must be left alone too.
    stray = library.path / "not-a-thesis"
    stray.mkdir()
    (stray / "keep.txt").write_text("FIXTURE", encoding="utf-8")

    with pytest.raises(UploadRefused):
        upload.remove(bad_id)

    assert (outside / "keep.txt").exists()
    assert (stray / "keep.txt").exists()
    assert (library.path / received["document_id"] / "source.pdf").exists()
