"""One question, several sources — `ask.retrieve_collection` and `run_query(collection=...)`
(PLAN_V7 §6, Sprint M2).

Offline. The model is replaced at `ask.call_model`, the embeddings by the offline
fake. Retrieval, the cap, validation, rendering and the run record are the real
code. Every passage is synthetic and says so.
"""

from __future__ import annotations

import dataclasses
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pytest

import ask
import embeddings
import runs
from conftest import fake_embed_texts
from documents import KIND_ARTICLE, Document, default_document, default_layout

ROOT = Path(ask.__file__).resolve().parent
QUESTION = "FIXTURE: what do the sources say about the lighthouse lamp oil?"


def payload(answer, cites, sufficiency="sufficient"):
    return {"evidence_sufficiency": sufficiency, "answer": answer, "limitations": [], "ai_interpretation": [],
            "unsupported_by_evidence": [], "citations_used": cites}


def make_source(document_id: str, author: str, year: str, texts: list[str], *, kind=KIND_ARTICLE,
                model: str | None = None, apparatus: bool = False) -> ask.Source:
    document = Document(document_id, author, year, f"FIXTURE title of {document_id}", f"{author} ({year}), FIXTURE",
                        default_layout(ask.settings), Path("no.pdf"), Path("."), Path("."), kind=kind)
    chunks = [{
        "chunk_id": f"{document_id}::{n:05d}::fixture", "document_id": document_id,
        "kind": "apparatus" if apparatus else "source", "chapter": None, "section": f"FIXTURE section {n}",
        "page_start": str(100 + n), "page_end": str(100 + n), "pdf_page_start": n + 1, "pdf_page_end": n + 1,
        "pages_unresolved": [], "token_count": len(text.split()), "text": text,
    } for n, text in enumerate(texts)]
    manifest = {"document_id": document_id, "embedding_model": model or embeddings.active_model_name(),
                "corpus_text_sha256": f"hash-of-{document_id}"}
    return ask.Source(document, fake_embed_texts(texts), chunks, manifest)


@pytest.fixture
def offline_embedding(monkeypatch):
    calls = []

    def embed(texts, **kwargs):
        calls.append(list(texts))
        return fake_embed_texts(texts, **kwargs)

    monkeypatch.setattr(ask, "embed_texts", embed)
    return calls


@pytest.fixture
def two(offline_embedding):
    """A thesis-like source and a short article, both touching the question."""
    thesis = make_source("thesis-fixture", "Fixture, T.", "2001", [
        "FIXTURE passage: the lighthouse keeper logged lamp oil deliveries every winter.",
        "FIXTURE passage: the lighthouse lamp oil was stored in the cellar.",
        "FIXTURE passage: the lighthouse lamp oil ledger was kept by the keeper.",
        "FIXTURE passage: the lighthouse lamp oil came by ferry.",
        "FIXTURE passage: the orchard grafting calendar lists rootstock.",
    ], kind="thesis")
    article = make_source("article-fixture", "Fixture, A.", "2020", [
        "FIXTURE passage: an article notes that lamp oil at the lighthouse was rationed.",
        "FIXTURE passage: the tramway timetable changed when the viaduct opened.",
    ])
    return [thesis, article]


# --- retrieval over several sources --------------------------------------------------


def test_passages_come_from_every_source_each_under_its_own_identity(two, offline_embedding):
    items = ask.retrieve_collection(QUESTION, two, k=5, per_source=3)

    assert [item.handle for item in items] == ["E1", "E2", "E3", "E4", "E5"]
    assert [item.score for item in items] == sorted((item.score for item in items), reverse=True)
    assert {item.document.document_id for item in items} == {"thesis-fixture", "article-fixture"}
    for item in items:
        assert item.chunk["chunk_id"].startswith(item.document.document_id + "::")   # identity travels with the passage
    assert offline_embedding == [[QUESTION]]                                       # the question is embedded once


def test_a_long_source_cannot_take_more_than_the_cap(two):
    capped = ask.retrieve_collection(QUESTION, two, k=5, per_source=3)
    by_source = [item.document.document_id for item in capped]

    assert by_source.count("thesis-fixture") == 3 and by_source.count("article-fixture") == 2
    uncapped = ask.retrieve_collection(QUESTION, two, k=5, per_source=5)
    assert [item.document.document_id for item in uncapped].count("thesis-fixture") == 4   # what the cap prevents
    assert len(ask.retrieve_collection(QUESTION, two, k=5, per_source=1)) == 2            # one each, and no padding


def test_sources_that_cannot_be_ranked_together_are_refused(two):
    other = make_source("article-other", "Fixture, O.", "2010", ["FIXTURE passage: lamp oil."], model="another-embedding")
    with pytest.raises(ask.CollectionRefused, match="different embedding models"):
        ask.retrieve_collection(QUESTION, [*two, other], 5, 3)
    with pytest.raises(ask.CollectionRefused, match="chosen twice"):
        ask.retrieve_collection(QUESTION, [two[0], two[0]], 5, 3)
    with pytest.raises(ask.CollectionRefused, match="No source was chosen"):
        ask.retrieve_collection(QUESTION, [], 5, 3)


# --- the one pipeline ----------------------------------------------------------------


class Model:
    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, question, items, **kwargs):
        self.calls.append({"question": question, "items": items, "kwargs": kwargs,
                           "block": ask.render_evidence_block(items)})
        return self.result, "fixturehash"


def test_a_collection_question_is_the_same_call_and_validation_with_the_collection_instruction(two, monkeypatch):
    model = Model(payload("FIXTURE Fixture, T. logs deliveries [E1]. FIXTURE Fixture, A. notes rationing [E4].", ["E1", "E4"]))
    monkeypatch.setattr(ask, "call_model", model)
    rules, digest = ask.collection_prompt()

    outcome = ask.run_query(QUESTION, None, None, collection=two)
    sent = model.calls[0]

    assert len(model.calls) == 1 and sent["kwargs"] == {"instructions": rules}
    assert rules == (ROOT / "prompts" / ask.COLLECTION_PROMPT).read_text(encoding="utf-8")
    assert "Fixture, T. (2001), FIXTURE" in sent["block"] and "Fixture, A. (2020), FIXTURE" in sent["block"]
    assert not ask.PAGE_CLAIM_RE.search(sent["block"])                              # still no page reaches the model
    assert (outcome.collection_prompt_hash, outcome.failures, outcome.grounded) == (digest, [], True)
    assert len(outcome.items) == ask.settings.top_k


def test_each_note_of_a_collection_answer_names_its_own_source(two, monkeypatch):
    monkeypatch.setattr(ask, "call_model", lambda q, items, **k: (payload("", []), "fixturehash"))
    items = ask.run_query(QUESTION, None, None, collection=two).items
    thesis = next(item for item in items if item.document.document_id == "thesis-fixture")
    article = next(item for item in items if item.document.document_id == "article-fixture")
    result = payload(f"FIXTURE one thing [{thesis.handle}]. FIXTURE another [{article.handle}].",
                     [thesis.handle, article.handle])

    text = ask.render(QUESTION, result, items, verbose=False)

    assert ask.validate(result, items) == []
    assert f"1. Fixture, T. (2001), § {thesis.chunk['section']}, p. {thesis.chunk['page_start']}." in text
    assert f"2. Fixture, A. (2020), § {article.chunk['section']}, p. {article.chunk['page_start']}." in text
    assert f"Fixture, A. (2020) — {article.chunk['section']}" in text.split("RETRIEVAL DIAGNOSTICS")[1]


def test_a_handle_the_collection_did_not_return_fails_validation_as_always(two, monkeypatch):
    monkeypatch.setattr(ask, "call_model", Model(payload("FIXTURE a claim [E9].", ["E9"])))
    outcome = ask.run_query(QUESTION, None, None, collection=two)

    assert not outcome.grounded and any("E9" in failure for failure in outcome.failures)


def test_other_instructions_follow_the_collection_instruction(two, monkeypatch):
    model = Model(payload("FIXTURE [E1].", ["E1"]))
    monkeypatch.setattr(ask, "call_model", model)

    ask.run_query(QUESTION, None, None, collection=two, instructions="FIXTURE rules of form")

    assert model.calls[0]["kwargs"]["instructions"] == ask.collection_prompt()[0] + "\n\nFIXTURE rules of form"


def test_the_no_retrieval_baseline_is_never_a_collection(two, monkeypatch):
    monkeypatch.setattr(ask, "call_model", lambda *a, **k: pytest.fail("a refused request reached the model"))
    with pytest.raises(ask.CollectionRefused, match="one document only"):
        ask.run_query(QUESTION, None, None, collection=two, retrieve_evidence=False)


# --- the single-document path is what it was -----------------------------------------


def test_a_question_of_one_document_is_sent_and_recorded_exactly_as_before(fixture_index, monkeypatch, tmp_path):
    model = Model(payload("FIXTURE the keeper logged lamp oil [E1].", ["E1"]))
    monkeypatch.setattr(ask, "call_model", model)
    monkeypatch.setattr(runs, "settings", dataclasses.replace(runs.settings, runs_path=tmp_path / "runs.jsonl"))
    vectors, chunks, manifest = ask.load_index()

    outcome = ask.run_query(QUESTION, vectors, chunks)
    record = runs.append(question=QUESTION, result=outcome.result, items=outcome.items, failures=outcome.failures,
                         prompt_hash=outcome.prompt_hash, manifest=manifest)

    assert model.calls[0]["kwargs"] == {}                                           # no instruction of any kind
    assert outcome.collection_prompt_hash is None
    assert [item.document for item in outcome.items] == [None] * ask.settings.top_k
    assert sorted(record) == ["corpus_text_sha256", "document_id", "embedding_model", "evidence", "model",
                              "prompt_sha256_12", "provider", "question", "result", "schema_version", "timestamp",
                              "validation_failures"]
    assert all(sorted(entry) == ["chunk_id", "handle", "score"] for entry in record["evidence"])
    assert record["document_id"] == "fixture-document"
    assert "RETRIEVAL DIAGNOSTICS" in outcome.rendered() and "Fixture" not in outcome.rendered().split("DIAGNOSTICS")[1]


def test_the_evaluation_and_the_interactive_loop_know_nothing_of_collections():
    for shell in ("evaluate.py", "main.py"):
        source = (ROOT / shell).read_text(encoding="utf-8")
        for name in ("collection=", "load_sources", "retrieve_collection", "Source("):
            assert name not in source, f"{shell} uses {name}"


# --- the run record ------------------------------------------------------------------


def test_a_collection_run_records_its_sources_and_is_reread_under_each_ones_identity(two, monkeypatch, tmp_path):
    monkeypatch.setattr(ask, "call_model", Model(payload("FIXTURE [E1]. FIXTURE [E4].", ["E1", "E4"])))
    monkeypatch.setattr(runs, "settings", dataclasses.replace(runs.settings, runs_path=tmp_path / "runs.jsonl"))
    outcome = ask.run_query(QUESTION, None, None, collection=two)

    record = runs.append(
        question=QUESTION, result=outcome.result, items=outcome.items, failures=outcome.failures,
        prompt_hash=outcome.prompt_hash, manifest=two[0].manifest,
        collection={"document_ids": [s.document.document_id for s in two], "prompt": ask.COLLECTION_PROMPT,
                    "prompt_sha256_12": outcome.collection_prompt_hash,
                    "per_source_passages": ask.settings.per_source_passages})
    stored = json.loads((tmp_path / "runs.jsonl").read_text(encoding="utf-8"))

    assert stored == record and "FIXTURE passage:" not in json.dumps(stored["evidence"])
    assert stored["collection"]["document_ids"] == ["thesis-fixture", "article-fixture"]
    assert stored["collection"]["prompt_sha256_12"] == ask.collection_prompt()[1]
    assert [entry["document_id"] for entry in stored["evidence"]] == [item.document.document_id for item in outcome.items]

    again, unresolved = runs.as_outcome(stored, [], sources=two)
    assert unresolved == [] and [i.document.document_id for i in again.items] == [i.document.document_id for i in outcome.items]
    assert again.rendered() == outcome.rendered()                                   # the same notes, from stored provenance
    _, missing = runs.as_outcome(stored, [], sources=two[:1])                       # one source since removed
    assert missing and all(chunk_id.startswith("article-fixture::") for chunk_id in missing)


# --- wording, and the command line ---------------------------------------------------


def test_an_articles_reference_list_is_named_as_the_articles_and_the_thesiss_as_the_thesiss():
    listed = make_source("article-fixture", "Fixture, A.", "2020", ["FIXTURE reference entry."], apparatus=True)
    note = ask.footnote(1, ask.EvidenceItem("E1", listed.chunks[0], 0.5, listed.document))
    assert note.endswith("[reference list — what the article cites, not what it argues]")

    builtin = default_document(ask.settings)
    chunk = {**listed.chunks[0], "document_id": builtin.document_id}
    assert ask.footnote(1, ask.EvidenceItem("E1", chunk, 0.5)).endswith(
        "[reference list — what the thesis cites, not what it argues]")


def test_the_command_line_asks_several_sources_when_several_are_named(two, monkeypatch):
    import upload

    by_id = {source.document.document_id: source for source in two}
    monkeypatch.setattr(upload, "find_document", lambda document_id: by_id[document_id].document)
    monkeypatch.setattr(ask, "load_index", lambda document=None: (
        by_id[document.document_id].vectors, by_id[document.document_id].chunks, by_id[document.document_id].manifest))
    model = Model(payload("FIXTURE [E1].", ["E1"]))
    monkeypatch.setattr(ask, "call_model", model)

    out = io.StringIO()
    with redirect_stdout(out):
        code = ask.main(["--document", "thesis-fixture", "--document", "article-fixture", "--json", QUESTION])
    printed = json.loads(out.getvalue())

    assert code == 0 and printed["document_ids"] == ["thesis-fixture", "article-fixture"]
    assert printed["collection_prompt_sha256_12"] == ask.collection_prompt()[1]
    assert {entry["chunk_id"].split("::")[0] for entry in printed["evidence"]} == {"thesis-fixture", "article-fixture"}

    model.calls.clear()
    with redirect_stdout(io.StringIO()):
        ask.main(["--document", "thesis-fixture", "--json", QUESTION])                # one source: the old path
    assert model.calls[0]["kwargs"] == {}
