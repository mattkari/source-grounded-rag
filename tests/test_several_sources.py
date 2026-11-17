"""The article writer over several sources — PLAN_V7 §7 (Sprint M3).

Offline. The drafting model is replaced at `ask.call_model`, the agent's at
`ask.call_explorer`, the embeddings by the offline fake. Opening the sources, the
collection retrieval, validation, assembly, the three raise-only checks, the record
and the export are the real code. Every passage is synthetic and says so.
"""

from __future__ import annotations

import dataclasses
import io
import json
import re
from pathlib import Path

import numpy as np
import pytest

import ask
import embeddings
import upload
import write_article
from article import checks, explorer, export as article_export, pipeline, sources, trace
from conftest import fake_embed_texts
from documents import KIND_ARTICLE, Document, default_document, default_layout
from test_article import payload, trial  # noqa: F401  (trial is a fixture)
from test_explorer import Agent, handle, reply, shown

ROOT = Path(ask.__file__).resolve().parent
# The first source is the built-in document as the fixture index stands in for it: its id
# comes from the settings, while the fixture's chunk ids begin "fixture-document".
FIRST = default_document(ask.settings).document_id
CHUNKS_OF_FIRST = "fixture-document"
SECOND_ID = "article-fixture0001"
SECOND_TEXTS = [
    ("FIXTURE rationing", "101", "FIXTURE passage: an article notes that lighthouse lamp oil was rationed in wartime."),
    ("FIXTURE tramway study", "102", "FIXTURE passage: an article finds the tramway timetable changed after the viaduct."),
    ("FIXTURE grafting study", "103", "FIXTURE passage: an article about orchard grafting and pear rootstock."),
]
OUTLINE = [("FIXTURE oil", "FIXTURE: what do the sources say about lighthouse lamp oil?"),
           ("FIXTURE tram", "FIXTURE: when did the tramway timetable change?"),
           ("FIXTURE graft", "FIXTURE: what is said about orchard grafting and rootstock?")]


def second_document(tmp_path, *, with_footnote_map=True) -> Document:
    """A second source on disk: its own index, and a stored footnote map saying it has none."""
    index_dir = tmp_path / "second-index"
    index_dir.mkdir(exist_ok=True)
    chunks = [{
        "chunk_id": f"{SECOND_ID}::{n:05d}::fixture", "document_id": SECOND_ID, "kind": "source", "chapter": None,
        "section": section, "page_start": page, "page_end": page, "pdf_page_start": n + 1, "pdf_page_end": n + 1,
        "pages_unresolved": [], "token_count": len(text.split()), "text": text,
    } for n, (section, page, text) in enumerate(SECOND_TEXTS)]
    chunks.append({**chunks[0], "chunk_id": f"{SECOND_ID}::00003::fixture", "kind": "apparatus", "section": "References",
                   "text": "FIXTURE reference entry: Example, B. A synthetic title about canals."})
    np.save(index_dir / "vectors.npy", fake_embed_texts([c["text"] for c in chunks]))
    (index_dir / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
    (index_dir / "manifest.json").write_text(json.dumps({
        "document_id": SECOND_ID, "embedding_model": embeddings.active_model_name(),
        "corpus_text_sha256": "second-corpus-hash", "chunk_count": len(chunks)}), encoding="utf-8")
    document = Document(SECOND_ID, "Second, B.", "2020", "FIXTURE Article On Synthetic Canals",
                        "Second, B. (2020), FIXTURE Article", default_layout(ask.settings), tmp_path / "no-second.pdf",
                        tmp_path, index_dir, kind=KIND_ARTICLE, container="FIXTURE Journal", volume_issue="12(3)",
                        pages="101–104", doi="10.5555/fixture.2020.001")
    if with_footnote_map:
        side = sources.side_path(document)
        side.parent.mkdir(exist_ok=True)
        side.write_text(json.dumps({"schema_version": sources.SCHEMA_VERSION, "corpus_text_sha256": "second-corpus-hash",
                                    "footnotes_found": 0, "unclear_foot_blocks": 0, "spans": {}}), encoding="utf-8")
    return document


@pytest.fixture
def second(trial, tmp_path):
    return second_document(tmp_path)


@pytest.fixture
def both(trial, second):
    return pipeline.open_workspace(others=[second])


@pytest.fixture
def one(trial):
    return pipeline.open_workspace()


class Model:
    """The drafting model: answers by the first key found in the question, and remembers each call."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def __call__(self, question, items, instructions=None):
        self.calls.append({"question": question, "items": list(items), "instructions": instructions})
        answer = next(value for key, value in self.script.items() if key in question)
        return (answer(items) if callable(answer) else answer), "fixturehash"


def of(items, document_id) -> str:
    """The handle of the first passage that came from this source."""
    return next(item.handle for item in items if ask._document(item.document).document_id == document_id)


def mixed(items):
    thesis, article = of(items, FIRST), of(items, SECOND_ID)
    return payload(f"FIXTURE Karimov logs lamp oil [{thesis}]. FIXTURE Second notes rationing [{article}].",
                   cites=[thesis, article])


SCRIPT = {"lamp oil": mixed,
          "tramway": lambda items: payload(f"FIXTURE Second dates the change [{of(items, SECOND_ID)}].", cites=[of(items, SECOND_ID)]),
          "grafting": lambda items: payload(f"FIXTURE Karimov lists rootstock [{of(items, FIRST)}].",
                                            cites=[of(items, FIRST)])}


# --- opening several sources ---------------------------------------------------------


def test_a_workspace_of_several_sources_keeps_each_ones_passages_and_identity(both, second):
    builtin = default_document(ask.settings)

    assert both.several and [d.document_id for d in both.documents] == [FIRST, SECOND_ID]
    assert len(both.by_id) == 5 + 3                                             # each one's reference list left out
    assert both.document_of(f"{SECOND_ID}::00001::fixture").author == "Second, B."
    assert both.document_of("fixture-document::00000::fixture").document_id == builtin.document_id
    assert [s.document.document_id for s in both.collection([SECOND_ID])] == [SECOND_ID]
    with pytest.raises(pipeline.ArticleError, match="None of the sources chosen"):
        both.collection(["not-a-source"])


def test_one_source_is_the_workspace_it_always_was(one):
    assert not one.several and one.others == [] and one.documents == [one.document]
    assert one.removed == one.sources.removed and len(one.by_id) == len(one.sources.chunks)


def test_a_source_is_not_added_twice_and_each_needs_its_own_footnote_map(trial, second, tmp_path):
    with pytest.raises(pipeline.ArticleError, match="chosen twice"):
        pipeline.open_workspace(others=[default_document(ask.settings)])
    sources.side_path(second).unlink()
    with pytest.raises(sources.NoFootnoteMap):
        pipeline.open_workspace(others=[second])                               # nothing is drafted from an unfiltered source


# --- drafting ------------------------------------------------------------------------


def test_a_section_of_several_sources_is_one_call_under_the_collection_and_several_sources_rules(both, monkeypatch):
    model = Model(SCRIPT)
    monkeypatch.setattr(ask, "call_model", model)

    section = pipeline.draft_section(both, *OUTLINE[0])
    sent = model.calls[0]

    assert len(model.calls) == 1 and pipeline.usable(section)
    rules = (ROOT / "prompts" / checks.SECTION_PROMPT_SOURCES).read_text(encoding="utf-8")
    assert sent["instructions"] == ask.collection_prompt()[0] + "\n\n" + rules
    assert {ask._document(i.document).document_id for i in sent["items"]} == {FIRST, SECOND_ID}
    assert not any(i.chunk.get("kind") == "apparatus" for i in sent["items"])
    assert section.outcome.collection_prompt_hash == ask.collection_prompt()[1]


def test_a_section_of_one_source_is_sent_exactly_as_before(one, monkeypatch):
    model = Model({"lamp oil": payload("FIXTURE the keeper logged lamp oil [E1].", cites=["E1"])})
    monkeypatch.setattr(ask, "call_model", model)

    section = pipeline.draft_section(one, *OUTLINE[0])

    assert model.calls[0]["instructions"] == (ROOT / "prompts" / checks.SECTION_PROMPT).read_text(encoding="utf-8")
    assert section.outcome.collection_prompt_hash is None and section.sources is None
    assert pipeline.section_prompt(one) == checks.SECTION_PROMPT != pipeline.section_prompt.__defaults__


def test_a_section_can_be_narrowed_to_some_of_the_sources(both, monkeypatch):
    model = Model({"tramway": lambda items: payload("FIXTURE Second dates it [E1].", cites=["E1"])})
    monkeypatch.setattr(ask, "call_model", model)

    section = pipeline.draft_section(both, *OUTLINE[1], only=[SECOND_ID])

    assert {i.chunk["document_id"] for i in model.calls[0]["items"]} == {SECOND_ID}
    assert section.sources == [SECOND_ID]
    wrong = pipeline.draft_section(both, *OUTLINE[1], only=["not-a-source"])
    assert not pipeline.usable(wrong) and "None of the sources chosen" in wrong.error and len(model.calls) == 1


def test_approved_passages_from_two_sources_keep_their_own_identity_and_the_same_rules(both, monkeypatch):
    model = Model({"lamp oil": payload("FIXTURE Karimov logs oil [E1]. FIXTURE Second notes rationing [E2].", cites=["E1", "E2"])})
    monkeypatch.setattr(ask, "call_model", model)
    monkeypatch.setattr(ask, "embed_texts", lambda *a, **k: pytest.fail("an approved section retrieved something"))

    section = pipeline.draft_section(both, *OUTLINE[0],
                                     approved=["fixture-document::00000::fixture", f"{SECOND_ID}::00000::fixture"])

    sent = model.calls[0]
    assert [ask._document(i.document).document_id for i in sent["items"]] == [FIRST, SECOND_ID]
    assert sent["instructions"].startswith(ask.collection_prompt()[0]) and pipeline.usable(section)


# --- the coverage map ----------------------------------------------------------------


def test_the_coverage_map_shows_what_each_source_holds_from_one_embedding_and_no_model(both, monkeypatch):
    embedded = []
    monkeypatch.setattr(ask, "embed_texts", lambda texts, **k: (embedded.append(list(texts)), fake_embed_texts(texts, **k))[1])
    monkeypatch.setattr(ask, "call_model", lambda *a, **k: pytest.fail("the coverage map called the model"))
    monkeypatch.setattr(ask, "settings", dataclasses.replace(ask.settings, preview_min_score=0.99))

    found = pipeline.coverage(both, OUTLINE[1][1])
    text = pipeline.format_coverage([found])

    assert embedded == [[OUTLINE[1][1]]]
    assert [row["document_id"] for row in found["sources"]] == [FIRST, SECOND_ID]
    assert all(len(row["passages"]) == pipeline.PREVIEW_PASSAGES for row in found["sources"])
    assert found["sources"][1]["passages"][0]["pages"] == "p. 102"             # the article's tramway passage, by its page
    assert "COVERAGE MAP (embedding only; scores are diagnostics, not confidence)" in text
    assert "Second, B. (2020)" in text and "FIXTURE passage:" not in text
    assert text.count("LOOK: the best score") == 2                             # raised per source; it refuses nothing
    narrowed = pipeline.coverage(both, OUTLINE[1][1], [SECOND_ID])
    assert [row["document_id"] for row in narrowed["sources"]] == [SECOND_ID]


# --- the whole article ---------------------------------------------------------------


@pytest.fixture
def drafted(both, trial, monkeypatch):
    monkeypatch.setattr(ask, "call_model", Model(SCRIPT))
    draft = pipeline.new_draft("FIXTURE harbour title", OUTLINE, section_sources=[None, [SECOND_ID], None])
    pipeline.run(both, draft, trial.out_dir)
    return draft


def test_every_note_names_its_own_source_and_the_article_names_them_all(both, drafted):
    article = pipeline.render(both, drafted)
    text = article.markdown
    by_source = {ask._document(entry["document"]).document_id for entry in article.sources}

    opening = next(line for line in text.splitlines() if line.startswith("*Drawn from "))
    assert "Second, B. (2020), FIXTURE Article On Synthetic Canals" in opening and opening.count(";") == 1
    assert by_source == {FIRST, SECOND_ID}
    notes = text.split("## Sources\n\n")[1]
    assert re.search(r"\[2\] Second, B\. \(2020\), § FIXTURE rationing, p\. 101\.", notes)
    assert "None" not in notes


def test_the_export_lists_notes_under_each_source_and_says_whose_work_it_is(both, drafted, monkeypatch):
    article = pipeline.render(both, drafted)
    exported = article_export.markdown(article, both.documents, None)
    listed = exported.split("## Sources\n\n")[1]
    thesis = both.document.reference()

    assert listed.index(f"**{thesis}**") < listed.index("**Second, B. (2020), FIXTURE Article On Synthetic Canals, "
                                                         "FIXTURE Journal 12(3), 101–104. doi:10.5555/fixture.2020.001**")
    assert "[2] FIXTURE rationing, p. 101." in listed.split("**Second, B.")[1]      # a note keeps its number
    assert "from several sources: " in exported and "Second, B. (2020), FIXTURE Article On Synthetic Canals" in exported
    html = article_export.as_html(article, both.documents, None)
    assert "<p><strong>Second, B. (2020), FIXTURE Article On Synthetic Canals" in html

    owner = both.document.author.split(",")[0]
    assert "my own work (" in article_export.disclosure(both.documents, owner)
    assert "on the work of other authors (Second, B. (2020)" in article_export.disclosure(both.documents, owner)
    assert "summarises the work of other authors" in article_export.disclosure(both.documents, "Nobody Else")
    assert article_export.disclosure([both.document], None) == article_export.disclosure(both.document, None)


def test_the_record_names_every_source_and_the_article_reopens_only_against_them(both, one, drafted, trial, second):
    folder = trial.out_dir / drafted.article_id
    record = json.loads((folder / "record.json").read_text(encoding="utf-8"))

    assert record["document_ids"] == [FIRST, SECOND_ID] and record["document_id"] == FIRST
    assert record["corpora"] == {FIRST: "fixture-corpus-hash", SECOND_ID: "second-corpus-hash"}
    assert record["sources"][1] == {"document_id": SECOND_ID, "kind": "article", "reference": second.reference()}
    assert set(record["prompts"]) >= {checks.SECTION_PROMPT_SOURCES, ask.COLLECTION_PROMPT}
    assert checks.SECTION_PROMPT not in record["prompts"]
    assert [s["sources_searched"] for s in record["sections"]] == [None, [SECOND_ID], None]
    assert set(record["source_filters"]) == {FIRST, SECOND_ID}

    reopened = pipeline.load(folder, both)
    assert pipeline.render(both, reopened).markdown == pipeline.render(both, drafted).markdown
    assert reopened.sections[1].sources == [SECOND_ID]
    with pytest.raises(pipeline.ArticleError, match="not from what is now open"):
        pipeline.load(folder, one)
    swapped = pipeline.Workspace(both.others[0].document, both.others[0].sources, both.others[0].manifest,
                                 [pipeline.Workspace(both.document, both.sources, both.manifest)])
    with pytest.raises(pipeline.ArticleError, match="not from what is now open"):
        pipeline.load(folder, swapped)


def test_a_limit_stated_of_the_sources_is_printed_like_one_stated_of_the_thesis(both, trial, monkeypatch):
    def limited(items):
        handle = of(items, SECOND_ID)
        return payload(f"FIXTURE Second dates the change [{handle}].", cites=[handle], sufficiency="partial",
                       limitations=[f"The sources do not give the year of the change [{handle}]."])

    monkeypatch.setattr(ask, "call_model", Model({**SCRIPT, "tramway": limited}))
    draft = pipeline.new_draft("FIXTURE harbour title", OUTLINE)
    pipeline.run(both, draft, trial.out_dir)

    article = pipeline.render(both, draft)
    assert any("The sources do not give the year of the change" in line for line in article.limits_printed.values())


# --- what is raised, and decides nothing ---------------------------------------------


def test_a_sentence_with_notes_from_two_sources_is_raised_for_the_researcher(both, trial, monkeypatch):
    def joined(items):
        thesis, article = of(items, FIRST), of(items, SECOND_ID)
        return payload(f"FIXTURE lamp oil was logged and rationed [{thesis}] [{article}].", cites=[thesis, article])

    monkeypatch.setattr(ask, "call_model", Model({**SCRIPT, "lamp oil": joined}))
    draft = pipeline.new_draft("FIXTURE harbour title", OUTLINE)
    pipeline.run(both, draft, trial.out_dir)
    article = pipeline.render(both, draft)
    first = [pair for pair in article.pairs if pair["section"] == 0]

    flags = pipeline.pair_flags(both, first[0], article)
    assert len(first) == 2 and any("carries notes from two sources" in flag for flag in flags)
    assert "Second, B. (2020)" in flags[-1] or any("Second, B. (2020)" in flag for flag in flags)
    assert pipeline.usable(draft.sections[0])                                  # raised; the section is not blocked
    rows = [row for row in pipeline.pairs_record(draft, article, both) if row["sid"].split(".")[0] == "0"]
    assert all(any("two sources" in flag for flag in row["raised"]) for row in rows)


def test_a_sentence_naming_one_author_with_a_note_to_another_source_is_raised():
    thesis = Document("thesis-x", "Karimov, I.", "2017", "T", "T", None, Path("."), Path("."), Path("."))
    article = Document("article-y", "Second, B. and Third, C.", "2020", "A", "A", None, Path("."), Path("."), Path("."))

    assert checks.source_flags("FIXTURE Second argues that oil was rationed.", [thesis], [thesis, article]) == [
        "the sentence names Second, but its note is to another source; check which source says this"]
    assert checks.source_flags("FIXTURE Second argues that oil was rationed.", [article], [thesis, article]) == []
    assert checks.source_flags("FIXTURE Karimov and Second differ.", [thesis, article], [thesis, article]) == [
        "this sentence carries notes from two sources (Karimov, I. (2017) and Second, B. and Third, C. (2020)); "
        "check that it does not join them into one claim"]
    assert checks.source_flags("FIXTURE the secondary school opened.", [thesis], [thesis, article]) == []   # whole words only
    assert checks.surname("Second, B. and Third, C.") == "Second" and checks.surname("Karimov, I.") == "Karimov"


@pytest.mark.parametrize("sentence, raised", [
    ("FIXTURE scholars agree that the oil was rationed.", True),
    ("FIXTURE the literature shows a change in 1900.", True),
    ("FIXTURE it is widely accepted that the viaduct opened late.", True),
    ("FIXTURE most historians date it earlier.", True),
    ("FIXTURE there is a broad consensus on the date.", True),
    ("FIXTURE Karimov and Second both date the change to the viaduct.", False),
    ("FIXTURE Second agrees with the ledger.", False),
])
def test_wording_that_claims_agreement_is_raised_and_naming_who_says_it_is_not(sentence, raised):
    assert bool(checks.consensus_flags(sentence)) is raised


def test_the_three_checks_never_keep_an_article_from_being_reviewed(both, trial, monkeypatch):
    def consensus(items):
        handle = of(items, SECOND_ID)
        return payload(f"FIXTURE scholars agree, and Karimov says so too [{handle}].", cites=[handle])

    monkeypatch.setattr(ask, "call_model", Model({**SCRIPT, "tramway": consensus}))
    draft = pipeline.new_draft("FIXTURE harbour title", OUTLINE)
    pipeline.run(both, draft, trial.out_dir)
    article = pipeline.render(both, draft)
    flagged = next(pair for pair in article.pairs if pair["section"] == 1)

    raised = pipeline.pair_flags(both, flagged, article)
    assert any("claims agreement" in flag for flag in raised) and any("names Karimov" in flag for flag in raised)
    for pair in article.pairs:
        pipeline.set_pair_verdict(draft, pair, "supports", "")
    assert pipeline.status(draft, pipeline.render(both, draft)) == pipeline.REVIEWED     # the verdict is the researcher's
    assert pipeline.export_blockers(draft, pipeline.render(both, draft)) == []


def test_an_article_of_one_source_raises_none_of_them(one, trial, monkeypatch):
    monkeypatch.setattr(ask, "call_model", Model({
        "lamp oil": payload("FIXTURE scholars agree that Second logged oil [E1].", cites=["E1"]),
        "tramway": payload("FIXTURE the timetable changed [E1].", cites=["E1"]),
        "grafting": payload("FIXTURE the calendar lists rootstock [E1].", cites=["E1"])}))
    draft = pipeline.new_draft("FIXTURE harbour title", OUTLINE)
    pipeline.run(one, draft, trial.out_dir)
    article = pipeline.render(one, draft)

    assert all(not any("source" in flag or "agreement" in flag for flag in pipeline.pair_flags(one, pair, article))
               for pair in article.pairs)


# --- the exploring agent, over several sources ---------------------------------------


def test_the_agent_sees_every_source_and_may_search_one_by_its_id(both, one, monkeypatch):
    def narrow(messages):
        return reply((explorer.SEARCH, {"query": "FIXTURE tramway timetable viaduct", "source": SECOND_ID}))

    def propose(messages):
        return reply((explorer.PROPOSE, {"theme": "FIXTURE: two sources on a harbour town.", "gaps": [], "sections": [
            {"heading": "FIXTURE oil", "question": "FIXTURE: lamp oil?", "passages": [handle(messages, "rationed")]},
            {"heading": "FIXTURE tram", "question": "FIXTURE: tramway?", "passages": [handle(messages, "after the viaduct")]},
            {"heading": "FIXTURE graft", "question": "FIXTURE: grafting?", "passages": [handle(messages, "apple and pear")]}]}))

    agent = Agent(reply((explorer.LIST_SOURCES, {})),
                  reply((explorer.SEARCH, {"query": "FIXTURE lighthouse lamp oil rationed", "source": None})),
                  narrow,
                  reply((explorer.SEARCH, {"query": "FIXTURE orchard grafting rootstock", "source": FIRST}),
                        (explorer.SEARCH, {"query": "FIXTURE anything", "source": "not-a-source"})),
                  propose)
    monkeypatch.setattr(ask, "call_explorer", agent)

    run = explorer.explore(both, "FIXTURE: a harbour town in two sources")
    seen = shown(agent.seen[-1])
    search = agent.tools[1]["input_schema"]["properties"]

    assert run.stop == explorer.PROPOSED and run.document_ids == [FIRST, SECOND_ID]
    assert search["source"]["anyOf"][0]["enum"] == [FIRST, SECOND_ID]
    assert f"[id: {SECOND_ID}; 3 passages]" in seen and "Section: FIXTURE tramway study" in seen
    first, second_search = run.steps[1]["calls"][0], run.steps[2]["calls"][0]
    from_each = [run.passages[h]["chunk_id"].split("::")[0] for h in first["returned"]]
    assert from_each.count(CHUNKS_OF_FIRST) <= ask.settings.per_source_passages and SECOND_ID in from_each
    assert {run.passages[h]["chunk_id"].split("::")[0] for h in second_search["returned"]} == {SECOND_ID}
    assert run.steps[3]["calls"][1]["error"] == "there is no source with the id not-a-source"
    assert [s["passages"][0].split("::")[0] for s in run.proposal["sections"]] == [SECOND_ID, SECOND_ID, CHUNKS_OF_FIRST]
    assert run.as_record()["corpora"] == {FIRST: "fixture-corpus-hash", SECOND_ID: "second-corpus-hash"}
    assert not ask.PAGE_CLAIM_RE.search(seen)

    approved = pipeline.approve(both, run.as_record())
    assert approved["approval"]["changes"]["sections_approved"] == 3
    with pytest.raises(pipeline.ArticleError, match="not what is now open"):
        pipeline.approve(one, run.as_record())
    assert explorer.tools_for(one) is explorer.TOOLS                            # one source: the tools as they were


# --- the trace and the command line --------------------------------------------------


def test_the_trace_reports_each_sources_filter_and_which_source_a_passage_is_from(both, drafted):
    rows = trace.trace(both, drafted)
    filters = [row for row in rows if row["step"] == "sources"]
    tram = next(row for row in rows if row["step"] == "section" and row["where"] == "FIXTURE tram")

    assert [row["where"] for row in filters] == [both.document.reference(), both.others[0].document.reference()]
    assert any(re.search(r"E\d  p\. 10\d +score \d\.\d{3}  Second, B\. \(2020\)", detail) for detail in tram["details"])
    assert f"sources searched: {SECOND_ID}" in [detail.strip() for detail in tram["details"]]
    assert f"rules of form {checks.SECTION_PROMPT_SOURCES}" in "\n".join(tram["details"])
    assert "FIXTURE passage:" not in trace.format_trace(rows)


def test_the_command_line_drafts_from_several_documents_and_prints_the_coverage_map(both, second, trial, monkeypatch, tmp_path):
    builtin = default_document(ask.settings)
    monkeypatch.setattr(upload, "find_document", lambda i: {builtin.document_id: builtin, SECOND_ID: second}[i])
    outline = tmp_path / "outline.txt"
    outline.write_text("\n".join(f"{heading} | {brief}" for heading, brief in OUTLINE), encoding="utf-8")
    common = ["--document", builtin.document_id, "--document", SECOND_ID, "--title", "FIXTURE harbour title",
              "--outline", str(outline), "--out-dir", str(trial.out_dir)]

    monkeypatch.setattr(ask, "call_model", lambda *a, **k: pytest.fail("a dry run called the model"))
    out = io.StringIO()
    assert write_article.main([*common, "--coverage", "--dry-run"], stream=out) == 0
    assert "COVERAGE MAP" in out.getvalue() and "Second, B. (2020)" in out.getvalue()

    monkeypatch.setattr(ask, "call_model", Model(SCRIPT))
    out = io.StringIO()
    assert write_article.main(common, stream=out) == 0
    record = json.loads(next(trial.out_dir.glob("*/record.json")).read_text(encoding="utf-8"))
    assert record["document_ids"] == [builtin.document_id, SECOND_ID]
    assert second.reference() in out.getvalue()                                 # each source's filter is reported
