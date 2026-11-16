"""The article writer — `article/` and its command line, `write_article.py` (PLAN_V6).

Offline. The generation model is replaced at `ask.call_model` and nowhere else;
retrieval, validation, citation resolution and assembly are the real code.
Every passage and brief here is synthetic and says so.
"""

from __future__ import annotations

import dataclasses
import io
import json
import re
from pathlib import Path

import pytest

import ask
from article import assemble, footnotes, pipeline, sources, topics, voice
from article.assemble import GENERATED, RESEARCHER, FrameElement, SectionDraft
from documents import LayoutProfile, default_document
from pdf_factory import ThesisSpec, make_thesis
import write_article

ROOT = Path(ask.__file__).resolve().parent


def payload(answer, *, cites, sufficiency="sufficient", limitations=(), interpretation=()):
    return {
        "evidence_sufficiency": sufficiency,
        "answer": answer,
        "limitations": list(limitations),
        "ai_interpretation": list(interpretation),
        "unsupported_by_evidence": [],
        "citations_used": list(cites),
    }


REFUSAL = {"evidence_sufficiency": "insufficient", "answer": None, "limitations": [],
           "ai_interpretation": [], "unsupported_by_evidence": ["FIXTURE: glaciers"], "citations_used": []}


def outcome(result, items):
    """What the pipeline would hand over: the real validation on a scripted payload."""
    return ask.QueryOutcome("FIXTURE brief", result, items, ask.validate(result, items), "fixturehash")


@pytest.fixture
def document():
    return default_document(ask.settings)


@pytest.fixture
def three(items):
    """Three sections. The second cites the passage the first cited, under another handle."""
    reordered = [ask.EvidenceItem("E1", items[1].chunk, 0.5), ask.EvidenceItem("E2", items[0].chunk, 0.4)]
    return [
        SectionDraft("FIXTURE one", "b1", outcome(payload("FIXTURE oil was logged [E1]. FIXTURE canals [E6].",
                                                          cites=["E1", "E6"]), items)),
        SectionDraft("FIXTURE two", "b2", outcome(payload("FIXTURE grafting [E1], and oil again [E2].",
                                                          cites=["E1", "E2"],
                                                          interpretation=["FIXTURE a reading of it [E1]."]), reordered)),
        SectionDraft("FIXTURE three", "b3", outcome(payload("FIXTURE the timetable changed [E3].", cites=["E3"],
                                                            sufficiency="partial",
                                                            limitations=["The thesis does not give a date for the change [E3]."]), items)),
    ]


# --- assembly ------------------------------------------------------------------------


def test_one_passage_keeps_one_note_number_across_the_whole_article(three, document):
    article = assemble.assemble(title="FIXTURE title", document=document, sections=three)
    text = article.markdown

    assert "FIXTURE oil was logged [1]. FIXTURE canals [2]." in text
    assert "FIXTURE grafting [3], and oil again [1]." in text
    assert "FIXTURE the timetable changed [4]." in text
    assert [note["n"] for note in article.notes] == [1, 2, 3, 4]
    assert article.notes[0]["chunk_id"] == "fixture-document::00000::fixture"
    assert not re.search(r"\[E\d+\]", text)
    assert not re.search(r"[⁰¹²³⁴-⁹]", text)            # Medium has no footnotes: plain markers only


def test_sources_are_resolved_from_stored_provenance_never_from_the_model(three, items, document):
    text = assemble.assemble(title="FIXTURE title", document=document, sections=three).markdown
    listed = text.split("## Sources\n\n")[1].split("\n\n*")[0]
    sources = listed.split("\n\n")                    # one paragraph each, or they run together when rendered

    expected = [ask.footnote(n, item).split(". ", 1)[1] for n, item in ((1, items[0]), (2, items[5]), (3, items[1]), (4, items[2]))]
    assert sources == [f"[{n}] {line}" for n, line in enumerate(expected, start=1)]
    assert sources[0].endswith("p. 3.") and sources[2].endswith("pp. 7–8.")


def test_the_article_opens_as_a_draft_names_its_source_and_closes_with_the_ai_line(three, document):
    lines = assemble.assemble(title="FIXTURE title", document=document, sections=three).markdown.splitlines()
    reviewed = assemble.assemble(title="FIXTURE title", document=document, sections=three, reviewed=True).markdown

    assert lines[0] == f"*{assemble.DRAFT_LINE}*"
    assert lines[2] == "# FIXTURE title"
    assert lines[4] == f"*Drawn from {document.author} ({document.year}), {document.title}.*"
    assert [l for l in lines if l][-1] == f"*{assemble.CLOSING_LINE}*"
    assert "checked by the researcher" not in lines[-2]              # a draft never claims a check it has not had
    assert assemble.DRAFT_LINE not in reviewed and reviewed.startswith("# FIXTURE title")
    assert reviewed.rstrip().endswith(f"*{assemble.CLOSING_LINE_REVIEWED}*")


def test_the_models_own_reading_is_marked_as_commentary_in_words(three, document):
    assert assemble.COMMENTARY_LABEL not in assemble.assemble(title="FIXTURE title", document=document, sections=three).markdown
    text = assemble.assemble(title="FIXTURE title", document=document, sections=three, commentary=True).markdown

    assert f"{assemble.COMMENTARY_LABEL} FIXTURE a reading of it [3]." in text
    assert text.count(assemble.COMMENTARY_LABEL) == 1
    assert "- The thesis does not give a date for the change [4]." in text   # a stated limit is kept, at the close


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (payload("FIXTURE cites a passage that was never supplied [E9].", cites=["E9"]), "validation failed: citation_hallucination"),
        (payload("FIXTURE fluent text with no handle at all.", cites=[]), "validation failed: ungrounded_answer"),
        (payload("FIXTURE oil, see p. 44 [E1].", cites=["E1"]), "validation failed: invented_page_reference"),
        (REFUSAL, "the thesis does not hold enough evidence for this"),
        (payload("FIXTURE a table [E1].\n\n| a | b |\n|---|---|\n| 1 | 2 |", cites=["E1"]), "the draft contains a table"),
    ],
)
def test_a_section_that_may_not_be_printed_is_left_out_and_the_reason_recorded(three, items, document, result, reason):
    three[1] = SectionDraft("FIXTURE blocked", "b2", outcome(result, items))
    article = assemble.assemble(title="FIXTURE title", document=document, sections=three)

    assert "FIXTURE blocked" not in article.markdown
    assert len(article.blocked) == 1
    assert article.blocked[0]["what"] == "section: FIXTURE blocked"
    assert article.blocked[0]["reason"].startswith(reason)
    assert "## FIXTURE one" in article.markdown and "## FIXTURE three" in article.markdown
    assert not any(line.lstrip().startswith("|") for line in article.markdown.splitlines())


def test_a_section_whose_pipeline_failed_is_blocked_not_hidden(three, document):
    three[0] = SectionDraft("FIXTURE down", "b1", None, "RuntimeError: FIXTURE outage")
    article = assemble.assemble(title="FIXTURE title", document=document, sections=three)

    assert article.blocked == [{"what": "section: FIXTURE down", "reason": "the pipeline failed: RuntimeError: FIXTURE outage"}]
    assert "FIXTURE down" not in article.markdown


def test_generated_frame_text_is_labelled_and_the_researchers_is_not(three, items, document):
    generated = FrameElement(GENERATED, brief="FIXTURE", outcome=outcome(payload("FIXTURE an opening [E1].", cites=["E1"]), items))
    written = FrameElement(RESEARCHER, text="FIXTURE my own closing words.")
    text = assemble.assemble(title="FIXTURE title", document=document, sections=three,
                             introduction=generated, conclusion=written).markdown

    assert f"{assemble.COMMENTARY_LABEL} FIXTURE an opening [1]." in text
    assert "\nFIXTURE my own closing words.\n" in text
    assert f"{assemble.COMMENTARY_LABEL} FIXTURE my own" not in text
    assert text.index("FIXTURE an opening") < text.index("## FIXTURE one") < text.index("FIXTURE my own") < text.index("## Sources")


def test_generated_frame_text_that_fails_validation_is_blocked(three, items, document):
    bad = FrameElement(GENERATED, brief="FIXTURE", outcome=outcome(payload("FIXTURE no handle here.", cites=[]), items))
    article = assemble.assemble(title="FIXTURE title", document=document, sections=three, conclusion=bad)

    assert "FIXTURE no handle here" not in article.markdown
    assert article.blocked[0]["what"] == "conclusion"


def test_a_transition_is_printed_only_between_two_kept_neighbours(three, items, document):
    def bridge(word):
        return FrameElement(GENERATED, brief="FIXTURE", outcome=outcome(payload(f"FIXTURE bridge {word} [E1].", cites=["E1"]), items))

    whole = assemble.assemble(title="FIXTURE title", document=document, sections=three,
                              transitions=[bridge("first"), bridge("second")]).markdown
    assert whole.index("## FIXTURE one") < whole.index("bridge first") < whole.index("## FIXTURE two")
    assert whole.index("## FIXTURE two") < whole.index("bridge second") < whole.index("## FIXTURE three")

    three[1] = SectionDraft("FIXTURE blocked", "b2", outcome(REFUSAL, items))
    gapped = assemble.assemble(title="FIXTURE title", document=document, sections=three,
                               transitions=[bridge("first"), bridge("second")]).markdown
    assert "FIXTURE bridge" not in gapped        # neither bridge joins the two sections that remain


def test_a_note_not_yet_judged_is_never_counted_as_supported(three, document):
    notes = assemble.assemble(title="FIXTURE title", document=document, sections=three).notes
    assert {note["verdict"] for note in notes} == {None}
    assert assemble.support_rate(notes) == {"supports": 0, "partly": 0, "does not": 0, "not judged": 4, "notes": 4, "pairs": 4}

    notes[0]["verdict"], notes[1]["verdict"], notes[2]["verdict"] = "supports", "does not", "FIXTURE typo"
    assert assemble.support_rate(notes) == {"supports": 1, "partly": 0, "does not": 1, "not judged": 2, "notes": 4, "pairs": 4}


# --- topics ----------------------------------------------------------------------------


def test_topics_come_from_printed_structure_and_leave_out_the_reference_list(chunks):
    chunks.append({**chunks[0], "chapter": None, "section": "FIXTURE orphan"})
    chunks.append({**chunks[2], "chapter": "FIXTURE second chapter", "section": "FIXTURE tramway timetable"})
    chunks.append({**chunks[2], "chapter": "FIXTURE second chapter", "section": "FIXTURE tramway timetable",
                   "page_start": "13", "page_end": "14"})
    listed = topics.list_topics(chunks)

    assert [t.chapter for t in listed] == ["FIXTURE chapter", "FIXTURE second chapter"]     # no Bibliography
    first, second = listed
    assert (first.passages, first.pages) == (5, "pp. 3–11")
    assert [s.title for s in first.sections] == ["FIXTURE lamp oil ledger", "FIXTURE grafting calendar",
                                                 "FIXTURE tramway timetable", "FIXTURE unnumbered plate",
                                                 "FIXTURE canal survey"]
    assert (second.passages, second.pages, second.sections[0].passages) == (2, "pp. 12–14", 2)
    report = topics.format_topics(listed)
    assert "FIXTURE unnumbered plate — 1 passage, pages not printed" in report
    assert " 2. FIXTURE second chapter — 2 passages, pp. 12–14  (thin: few passages)" in report
    assert "passage:" not in report                   # never the text of a passage


def test_default_briefs_use_only_the_documents_own_section_titles(chunks):
    chunks += [dict(chunks[5]), dict(chunks[1])]
    topic = topics.list_topics(chunks)[0]

    assert topics.default_briefs(topic, 3) == [
        "What does the thesis say about “FIXTURE lamp oil ledger”?",       # document order, richest three
        "What does the thesis say about “FIXTURE grafting calendar”?",
        "What does the thesis say about “FIXTURE canal survey”?",
    ]


# --- voice -----------------------------------------------------------------------------


def test_voice_measures_are_plain_counts():
    text = ("I walked to my harbour [1]. But the ferry had gone. The collection states that it left early [E2]. "
            "We waited and waited a very long while!")      # two first-person words, one mid-sentence "and"
    assert voice.measure(text) == {
        "sentences": 4,
        "words": 25,
        "sentence_length_median": 6.0,
        "sentence_length_middle_half": [5, 8],
        "first_person_per_100_sentences": 50.0,
        "connective_openings_per_100_sentences": 25.0,
        "report_phrases_per_1000_words": 40.0,
        "connectives_per_1000_words": 40.0,            # one opening "But" in 25 words; the inner "and" is not counted
        "em_dashes": 0,
    }
    assert voice.measure("")["sentences"] == 0


def test_the_voice_comparison_gives_no_score_and_no_verdict():
    table = voice.format_comparison({"your writing": voice.measure("I went. But I came back."),
                                     "draft": voice.measure("The collection states a thing.")})
    assert "your writing" in table and "draft" in table
    assert len(table.splitlines()) == 1 + len(voice.ROWS)
    assert not re.search(r"score|match|similar|pass|fail|%", table, re.IGNORECASE)


# --- footnotes ---------------------------------------------------------------------------


def footnoted_thesis(tmp_path, document, **spec):
    """A synthetic thesis whose footnotes are set large enough for the extractor to keep."""
    path = tmp_path / "footnoted.pdf"
    make_thesis(path, ThesisSpec(footnote_size=11.0, **spec))
    layout = LayoutProfile(**{**dataclasses.asdict(document.layout), "body_size": 12.0, "body_min_size": 10.5,
                              "header_band_y": 60.0, "footnote_band_y": 780.0})
    return dataclasses.replace(document, pdf_path=path, layout=layout)


def test_the_footnote_map_finds_footnote_shaped_blocks_and_the_passages_they_sit_in(tmp_path, document):
    source = footnoted_thesis(tmp_path, document)
    found = footnotes.build(source)

    assert found.count == 18 and found.pages == 18 and found.unclear == 0     # one on each body page
    assert all("FIXTURE footnote citing a synthetic work." in text for texts in found.by_page.values() for text in texts)
    page = min(found.by_page)
    note = found.by_page[page][0]
    carrying = {"chunk_id": "a", "pdf_page_start": page, "pdf_page_end": page,
                "text": f"FIXTURE body words. {note.replace(' ', chr(10))}"}        # line breaks must not matter
    clean = {"chunk_id": "b", "pdf_page_start": page, "pdf_page_end": page, "text": "FIXTURE body words only."}
    elsewhere = {**carrying, "chunk_id": "c", "pdf_page_start": page + 30, "pdf_page_end": page + 30}

    assert footnotes.footnotes_in(carrying, found) == [note]
    assert footnotes.touched([carrying, clean, elsewhere], found) == ["a"]


def test_a_document_whose_footnotes_were_already_dropped_has_nothing_to_filter(tmp_path, document):
    source = footnoted_thesis(tmp_path, document)
    strict = dataclasses.replace(source, layout=dataclasses.replace(source.layout, body_min_size=11.5))

    assert footnotes.build(strict).count == 0


def test_the_built_in_thesis_holds_its_footnotes_as_body_text():
    """The finding PLAN_V6 §7 rests on. Counts only; the index is read, never written."""
    document = default_document()
    if not document.pdf_path.exists():
        pytest.skip("the thesis PDF is not in this checkout")
    before = (document.index_dir / "chunks.json").read_bytes()
    chunks = json.loads(before)
    found = footnotes.build(document)

    assert (found.count, found.pages) == (213, 213)
    assert (len(footnotes.touched(chunks, found)), len(chunks)) == (188, 294)
    assert (document.index_dir / "chunks.json").read_bytes() == before


# --- the trial ---------------------------------------------------------------------------


class Scripted:
    """Stand-in for `ask.call_model`. Records every call and the passages it was given."""

    def __init__(self, script):
        self.script, self.calls, self.seen, self.instructions = script, [], [], []

    def __call__(self, question, items, instructions=None):
        self.instructions.append(instructions)
        self.seen += [item.chunk for item in items]
        self.calls.append((question, [item.chunk["chunk_id"] for item in items], [item.handle for item in items]))
        behaviour = next(value for key, value in self.script.items() if key in question)
        if isinstance(behaviour, BaseException):
            raise behaviour
        return behaviour, "fixturehash"


BRIEFS = ["FIXTURE: what did the lighthouse keeper log about lamp oil?",
          "FIXTURE: what does the orchard grafting calendar list?",
          "FIXTURE: when did the tramway timetable change?"]
SCRIPT = {
    "lighthouse": payload("FIXTURE the keeper logged lamp oil [E1].", cites=["E1"]),
    "orchard": payload("FIXTURE the calendar lists rootstock [E1].", cites=["E1"]),
    "tramway": payload("FIXTURE the timetable changed [E1].", cites=["E1"]),
    "introduce": payload("FIXTURE these passages open a harbour story [E1] [E3].", cites=["E1", "E3"]),
    "connect": payload("FIXTURE one leads to the other [E2].", cites=["E2"]),
    "establish": payload("FIXTURE together they establish a little [E2].", cites=["E2"]),
}


@pytest.fixture
def trial(tmp_path, monkeypatch, fixture_index):
    """The fixture index, no PDF, and a stored footnote map that says it has no footnotes."""
    monkeypatch.setattr(ask, "settings", dataclasses.replace(ask.settings, pdf_path=tmp_path / "no.pdf"))
    monkeypatch.setattr(sources, "SIDE_DIR", tmp_path / "footnote_maps")
    side = sources.side_path(default_document(ask.settings))
    side.parent.mkdir()
    side.write_text(json.dumps({"schema_version": sources.SCHEMA_VERSION, "corpus_text_sha256": "fixture-corpus-hash",
                                "footnotes_found": 0, "unclear_foot_blocks": 0, "spans": {}}), encoding="utf-8")

    class Trial:
        out_dir = tmp_path / "output"
        log = io.StringIO()
        model = None

        def run(self, script=SCRIPT, **kwargs):
            self.model = Scripted(script)
            monkeypatch.setattr(ask, "call_model", self.model)
            args = dict(title="FIXTURE harbour title", briefs=list(BRIEFS), frame=GENERATED, references=[])
            args.update(kwargs)
            outline = tmp_path / "outline.txt"
            outline.write_text("\n".join(f"{brief.rstrip('?')} | {brief}" for brief in args["briefs"]), encoding="utf-8")
            argv = ["--title", args["title"], "--outline", str(outline), "--out-dir", str(self.out_dir),
                    "--frame", "generate" if args["frame"] == GENERATED else "none"]
            for reference in args["references"]:
                argv += ["--reference", str(reference)]
            self.code = write_article.main(argv, self.log)
            folders = sorted(self.out_dir.glob("*")) if self.out_dir.exists() else []
            self.article = (folders[-1] / "article.md").read_text(encoding="utf-8") if folders else None
            self.record = json.loads((folders[-1] / "record.json").read_text(encoding="utf-8")) if folders else None
            return self

    return Trial()


def test_the_trial_writes_one_assembled_article_and_its_record(trial):
    t = trial.run()

    assert t.code == 0
    for heading in ("## FIXTURE: what did the lighthouse keeper log about lamp oil", "## Sources"):
        assert heading in t.article
    assert t.article.count(assemble.COMMENTARY_LABEL) == 4          # introduction, two transitions, conclusion
    assert t.record["status"] == "draft"
    assert t.record["model"] == ask.settings.llm_model              # recorded, never set (hard rule 1)
    assert t.record["title"] == {"origin": "researcher", "text": "FIXTURE harbour title"}
    assert [s["blocked"] for s in t.record["sections"]] == [None, None, None]
    assert t.record["frame"]["introduction"]["origin"] == "generated"
    assert t.record["support"] == {"supports": 0, "partly": 0, "does not": 0, "not judged": 3, "notes": 3, "pairs": 3}
    assert t.record["source_filter"]["reference_list_excluded"] == 1
    assert t.record["source_filter"]["passages_available"] == 5
    assert "Notes to check in the web app: 3." in t.log.getvalue()


def test_frame_text_is_drafted_only_from_passages_the_sections_cite(trial):
    t = trial.run()
    cited = {note["chunk_id"] for note in t.record["notes"]}
    sections, frame = t.model.calls[:3], t.model.calls[3:]

    assert len(sections) == 3 and len(frame) == 4                   # one call each; nothing repeated
    assert all(len(chunk_ids) > 3 for _, chunk_ids, _ in sections)  # sections retrieve
    assert not any(chunk.get("kind") == "apparatus" for chunk in t.model.seen)   # never the reference list
    for _, chunk_ids, handles in frame:
        assert set(chunk_ids) <= cited                              # the frame does not
        assert handles == [f"E{n + 1}" for n in range(len(chunk_ids))]
    assert set(frame[0][1]) == cited                                # the introduction sees all of them, once
    assert len(t.record["notes"]) == 3                              # the frame added no note of its own


def test_a_failed_section_is_recorded_blocked_and_never_retried(trial):
    t = trial.run({**SCRIPT, "orchard": RuntimeError("FIXTURE provider outage")})

    assert t.code == 1
    assert sum(1 for question, _, _ in t.model.calls if "orchard" in question) == 1
    assert t.record["sections"][1]["error"] == "RuntimeError: FIXTURE provider outage"
    assert t.record["sections"][1]["blocked"] == "the pipeline failed: RuntimeError: FIXTURE provider outage"
    assert "orchard" not in t.article
    assert t.record["frame"]["transitions"] == [None, None]         # no bridge to or from a missing section
    assert "BLOCKED" in t.log.getvalue()


def test_no_bridge_is_drafted_to_a_section_the_thesis_could_not_support(trial):
    t = trial.run({**SCRIPT, "orchard": REFUSAL,
                   "introduce": payload("FIXTURE these passages open a harbour story [E1].", cites=["E1"])})

    assert t.code == 1
    assert [q for q, _, _ in t.model.calls if "connect" in q] == []      # no credit spent on a bridge to nothing
    assert t.record["sections"][1]["blocked"] == "the thesis does not hold enough evidence for this"
    assert t.article.count(assemble.COMMENTARY_LABEL) == 2               # introduction and conclusion only


def test_frame_text_goes_through_the_same_validation_as_a_section(trial):
    t = trial.run({**SCRIPT, "establish": payload("FIXTURE a closing that cites nothing supplied [E9].", cites=["E9"])})

    assert "FIXTURE a closing" not in t.article
    assert t.record["blocked"][0]["what"] == "conclusion"
    assert t.record["blocked"][0]["reason"].startswith("validation failed: citation_hallucination")
    assert t.record["frame"]["conclusion"]["validation_failures"] != []


def test_frame_none_makes_no_frame_call(trial):
    t = trial.run(frame="none")

    assert len(t.model.calls) == 3
    assert assemble.COMMENTARY_LABEL not in t.article
    assert t.record["frame"] == {"introduction": None, "transitions": [None, None], "conclusion": None}


def test_the_trial_reports_voice_beside_the_researchers_own_writing(trial, tmp_path):
    mine = tmp_path / "mine.md"
    mine.write_text("FIXTURE I went to the harbour. But I came back.", encoding="utf-8")
    t = trial.run(references=[mine])

    assert list(t.record["voice"]) == ["your writing", "draft, whole", "draft, sourced", "draft, commentary"]
    assert t.record["voice"]["your writing"]["first_person_per_100_sentences"] == 100.0
    assert t.record["voice"]["draft, sourced"]["sentences"] == 3
    assert t.record["voice"]["draft, commentary"]["sentences"] == 4
    assert "nothing of yours to compare with" not in t.log.getvalue()
    again = trial.run(references=[])                                # same second: a new folder, nothing overwritten
    assert "nothing of yours to compare with" in again.log.getvalue()
    assert len(list(trial.out_dir.glob("*"))) == 2


def test_footnote_text_never_reaches_the_model(trial, tmp_path, monkeypatch, document):
    source = footnoted_thesis(tmp_path, document)
    found = footnotes.build(source)
    page = min(found.by_page)
    note = found.by_page[page][0]
    index = Path(ask.settings.index_dir) / "chunks.json"
    stored = json.loads(index.read_text(encoding="utf-8"))
    for n in (0, 5):
        stored[n].update(pdf_page_start=page, pdf_page_end=page, text=stored[n]["text"] + "\n" + note)
    index.write_text(json.dumps(stored), encoding="utf-8")
    before = index.read_bytes()
    sources.side_path(default_document(ask.settings)).unlink()            # no stored map: measure from the PDF
    monkeypatch.setattr(ask, "settings", dataclasses.replace(
        ask.settings, pdf_path=source.pdf_path, body_size=12.0, body_min_size=10.5,
        header_band_y=60.0, footnote_band_y=780.0))

    t = trial.run(frame="none")

    assert len(t.model.seen) >= 10
    assert not any("footnote citing a synthetic work" in chunk["text"] for chunk in t.model.seen)
    assert any("lighthouse keeper logged lamp oil" in chunk["text"] for chunk in t.model.seen)   # the body is kept
    assert t.record["source_filter"]["footnote_text_removed_from"] == 2
    assert t.record["source_filter"]["footnotes_found"] == 18
    assert stored[0]["chunk_id"] in t.record["sections"][0]["footnote_text_cut_from"]
    assert "footnote text cut from             2" in t.log.getvalue()
    assert index.read_bytes() == before                                    # the index is read, never written


def test_without_a_pdf_or_a_stored_map_nothing_is_drafted(trial):
    sources.side_path(default_document(ask.settings)).unlink()

    t = trial.run()

    assert t.code == 2 and t.model.calls == [] and not trial.out_dir.exists()
    assert "footnotes cannot be told from the author's own text" in t.log.getvalue()


def test_the_trial_refuses_a_chapter_that_is_not_listed_or_the_wrong_number_of_briefs(trial):
    assert trial.run(briefs=BRIEFS[:2]).code == 2
    assert trial.run(briefs=BRIEFS * 3).code == 2                    # three to six sections
    assert trial.run(title="  ").code == 2                           # the title is the researcher's
    assert trial.model.calls == [] and not trial.out_dir.exists()


def test_listing_topics_calls_no_model(trial, monkeypatch):
    monkeypatch.setattr(ask, "call_model", lambda *a: pytest.fail("the topic listing called the model"))
    monkeypatch.setattr(ask, "embed_texts", lambda *a, **k: pytest.fail("the topic listing embedded something"))
    stream = io.StringIO()

    assert write_article.main(["--topics"], stream) == 0
    assert " 1. FIXTURE chapter — 5 passages, pp. 3–11" in stream.getvalue()


def test_no_shell_exposes_drafting_from_chosen_passages():
    """`ask.draft_from_evidence` is for the article writer only (PLAN_V6 §6)."""
    for shell in ("app.py", "main.py", "evaluate.py"):
        assert "draft_from_evidence" not in (ROOT / shell).read_text(encoding="utf-8"), shell
    source = (ROOT / "ask.py").read_text(encoding="utf-8")
    assert "draft_from_evidence" not in source[source.index("def main()"):]


# =====================================================================================
# Sprint W1 — the source filter (PLAN_V6 §7)
# =====================================================================================

NOTE = "FIXTURE footnote: Example, A., A Synthetic Work on Harbours, 44."


def note_map(page=30, text=NOTE):
    return footnotes.FootnoteMap(by_page={page: [text]})


def passage(n, text, page=30, **extra):
    return {"chunk_id": f"p{n}", "pdf_page_start": page, "pdf_page_end": page, "text": text, **extra}


def test_a_footnote_is_cut_out_and_the_body_text_around_it_is_kept():
    broken = NOTE.replace(", A Synthetic", ",\nA  Synthetic")                # line breaks differ in the index
    chunk = passage(1, f"FIXTURE body before.\n{broken}\nFIXTURE body after.")

    spans = sources.footnote_spans(chunk, note_map())

    assert len(spans) == 1
    assert chunk["text"][spans[0][0]:spans[0][1]] == broken
    assert sources.cut(chunk["text"], spans) == "FIXTURE body before.\nFIXTURE body after."


def test_a_footnote_cut_in_two_by_a_passage_boundary_is_removed_from_both_sides():
    opening, remainder = NOTE[:30], NOTE[30:]
    first = passage(1, f"FIXTURE body one. {opening}")
    second = passage(2, f"{remainder} FIXTURE body two.")

    assert sources.cut(first["text"], sources.footnote_spans(first, note_map())) == "FIXTURE body one."
    assert sources.cut(second["text"], sources.footnote_spans(second, note_map())) == "FIXTURE body two."


def test_only_footnotes_of_the_pages_a_passage_covers_are_looked_for_and_short_echoes_are_left():
    elsewhere = passage(1, f"FIXTURE body. {NOTE}", page=31)
    echo = passage(2, "FIXTURE body that names A Synthetic Work on Harbours in passing.")
    tail_echo = passage(3, "FIXTURE body ends with the word FIXTURE foot")          # 11 characters: too short to be a split

    assert sources.footnote_spans(elsewhere, note_map(page=30)) == []
    assert sources.footnote_spans(echo, note_map()) == []
    assert sources.footnote_spans(tail_echo, note_map()) == []


def test_the_filtered_view_leaves_out_the_reference_list_and_passages_that_are_mostly_footnote(chunks):
    import numpy as np
    vectors = np.arange(len(chunks) * 2, dtype=np.float32).reshape(len(chunks), 2)
    original = json.dumps(chunks)
    text0, text2 = chunks[0]["text"], chunks[2]["text"]
    side = {"footnotes_found": 7, "unclear_foot_blocks": 2, "spans": {
        chunks[0]["chunk_id"]: [[0, 8]],                              # a little of it
        chunks[2]["chunk_id"]: [[0, len(text2) - 5]],                 # nearly all of it
    }}

    view = sources.filtered(vectors, chunks, side)

    assert [c["chunk_id"][18:23] for c in view.chunks] == ["00000", "00001", "00003", "00005"]
    assert view.vectors.tolist() == vectors[[0, 1, 3, 5]].tolist()   # each vector still belongs to its passage
    assert view.chunks[0]["text"] == text0[8:].strip()
    assert view.removed == {chunks[0]["chunk_id"]: 1}
    assert view.report.to_json() == {
        "passages_in_index": 6, "reference_list_excluded": 1, "footnote_text_removed_from": 1,
        "dropped_mostly_footnote": 1, "passages_available": 4, "footnotes_found": 7,
        "unclear_foot_blocks": 2, "dropped_chunk_ids": [chunks[2]["chunk_id"]],
    }
    assert json.dumps(chunks) == original and len(vectors) == 6       # what was passed in is untouched


def _strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value


def test_the_stored_footnote_map_holds_ids_and_numbers_and_no_text(tmp_path, monkeypatch, document):
    monkeypatch.setattr(sources, "SIDE_DIR", tmp_path / "maps")
    source = footnoted_thesis(tmp_path, document)
    found = footnotes.build(source)
    page = min(found.by_page)
    chunk = passage(1, f"FIXTURE body. {found.by_page[page][0]}", page=page)

    side = sources.load_or_measure(source, [chunk], "hash-one")
    stored = sources.side_path(source).read_text(encoding="utf-8")

    assert side["footnotes_found"] == 18 and list(side["spans"]) == ["p1"]
    assert "FIXTURE" not in stored and "footnote citing" not in stored
    allowed = {"schema_version", "document_id", "corpus_text_sha256", "footnotes_found", "pages_with_footnotes",
               "unclear_foot_blocks", "spans", "p1", "hash-one", source.document_id}
    assert set(_strings(json.loads(stored))) <= allowed


def test_a_stored_map_is_used_without_the_pdf_and_ignored_when_the_index_has_changed(tmp_path, monkeypatch, document):
    monkeypatch.setattr(sources, "SIDE_DIR", tmp_path / "maps")
    source = footnoted_thesis(tmp_path, document)
    page = min(footnotes.build(source).by_page)
    chunk = passage(1, f"FIXTURE body. {footnotes.build(source).by_page[page][0]}", page=page)
    measured = sources.load_or_measure(source, [chunk], "hash-one")
    gone = dataclasses.replace(source, pdf_path=tmp_path / "gone.pdf")

    assert sources.load_or_measure(gone, [chunk], "hash-one") == measured         # same index: the stored map serves
    with pytest.raises(sources.NoFootnoteMap):
        sources.load_or_measure(gone, [chunk], "hash-two")                          # another index: it does not
    assert sources.load_or_measure(source, [chunk], "hash-two")["corpus_text_sha256"] == "hash-two"


def test_the_committed_map_of_the_built_in_thesis_holds_no_text_and_matches_its_index():
    document = default_document()
    chunks = json.loads((document.index_dir / "chunks.json").read_text(encoding="utf-8"))
    manifest = json.loads((document.index_dir / "manifest.json").read_text(encoding="utf-8"))
    side = json.loads(sources.side_path(document).read_text(encoding="utf-8"))
    ids = {chunk["chunk_id"] for chunk in chunks}
    keys = {"schema_version", "document_id", "corpus_text_sha256", "footnotes_found", "pages_with_footnotes",
            "unclear_foot_blocks", "spans"}

    assert side["corpus_text_sha256"] == manifest["corpus_text_sha256"]
    assert side["footnotes_found"] == 213                              # every footnote ADR 0003 counted
    assert set(_strings(side)) <= keys | ids | {document.document_id, manifest["corpus_text_sha256"]}
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    for chunk_id, spans in side["spans"].items():
        assert all(0 <= start < end <= len(by_id[chunk_id]["text"]) for start, end in spans)


def test_no_footnote_of_the_built_in_thesis_is_left_in_what_an_article_drafts_from():
    """PLAN_V6 §7's test, on the real thesis. Counts only; nothing is written."""
    import difflib
    import numpy as np
    document = default_document()
    if not document.pdf_path.exists():
        pytest.skip("the thesis PDF is not in this checkout")
    frozen = [document.index_dir / "chunks.json", document.index_dir / "vectors.npy",
              document.canonical_dir / "pages.jsonl"]
    before = [path.read_bytes() for path in frozen]
    chunks = json.loads(before[0])
    manifest = json.loads((document.index_dir / "manifest.json").read_text(encoding="utf-8"))

    measured = sources.measure(document, chunks, manifest["corpus_text_sha256"])
    assert measured == json.loads(sources.side_path(document).read_text(encoding="utf-8"))   # the committed map is current
    view = sources.filtered(np.load(frozen[1]), chunks, measured)

    report = view.report
    assert (report.footnotes_found, report.reference_list_excluded) == (213, 28)
    assert report.passages_available == 294 - 28 - report.dropped_mostly_footnote == len(view.chunks)
    assert not any(chunk.get("kind") == "apparatus" for chunk in view.chunks)
    found, longest = footnotes.build(document), 0
    for page, texts in found.by_page.items():
        on_page = [footnotes._squash(c["text"]) for c in view.chunks if c["pdf_page_start"] <= page <= c["pdf_page_end"]]
        for text in texts:
            note = footnotes._squash(text)
            for haystack in on_page:
                assert note not in haystack                            # no footnote survives whole
                match = difflib.SequenceMatcher(None, note, haystack, autojunk=False).find_longest_match(
                    0, len(note), 0, len(haystack))
                longest = max(longest, match.size)
    assert longest < 100           # what still matches is a title or a verse the body quotes too
    assert [path.read_bytes() for path in frozen] == before


# =====================================================================================
# Sprint W1 — verdicts, the record, saving and loading (PLAN_V6 §9)
# =====================================================================================


@pytest.fixture
def workspace(trial):
    return pipeline.open_workspace()


@pytest.fixture
def draft(workspace, monkeypatch):
    """A drafted article: three sections, a generated introduction, the researcher's own conclusion."""
    monkeypatch.setattr(ask, "call_model", Scripted({
        **SCRIPT,
        "lighthouse": payload("FIXTURE the keeper logged lamp oil [E1]. FIXTURE it was every winter [E1]. "
                              "FIXTURE the calendar agrees [E2].", cites=["E1", "E2"]),
        "introduce": payload("FIXTURE an opening that restates the oil [E1]. FIXTURE a bare remark.", cites=["E1"]),
    }))
    sections = [pipeline.draft_section(workspace, f"FIXTURE heading {n + 1}", brief) for n, brief in enumerate(BRIEFS)]
    return pipeline.Draft(
        title="FIXTURE harbour title", sections=sections, topic="FIXTURE chapter",
        introduction=pipeline.draft_introduction("FIXTURE harbour title", sections),
        transitions=[None, None],
        conclusion=pipeline.written("FIXTURE my own closing words."),
    )


def ids(article):
    return [note["chunk_id"] for note in article.notes]


def test_an_article_is_a_draft_until_every_note_has_a_verdict(workspace, draft):
    article = pipeline.render(workspace, draft)
    assert pipeline.status(draft, article) == "draft" and article.markdown.startswith(f"*{assemble.DRAFT_LINE}*")

    for chunk_id in ids(article)[:-1]:
        pipeline.set_verdict(draft, chunk_id, "supports")
    assert pipeline.status(draft, pipeline.render(workspace, draft)) == "draft"       # one note still unjudged

    pipeline.set_verdict(draft, ids(article)[-1], "partly", "FIXTURE reason: only half of it")
    reviewed = pipeline.render(workspace, draft)
    assert pipeline.status(draft, reviewed) == "reviewed"
    assert assemble.DRAFT_LINE not in reviewed.markdown
    assert reviewed.markdown.rstrip().endswith(f"*{assemble.CLOSING_LINE_REVIEWED}*")


def test_a_verdict_must_be_one_of_the_three_and_is_recorded_as_the_researchers(workspace, draft):
    article = pipeline.render(workspace, draft)
    with pytest.raises(pipeline.ArticleError):
        pipeline.set_verdict(draft, ids(article)[0], "probably")
    pipeline.set_verdict(draft, ids(article)[0], "partly", " FIXTURE reason ")

    note = pipeline.notes_record(draft, article)[0]
    assert (note["verdict"], note["reason"], note["judged_by"]) == ("partly", "FIXTURE reason", "researcher")
    assert note["judged_at"].startswith("20") and note["n"] == 1
    assert pipeline.notes_record(draft, article)[1]["judged_by"] is None           # not judged: nobody's verdict


def test_a_does_not_verdict_keeps_the_article_in_draft_until_its_sentences_are_removed(workspace, draft):
    article = pipeline.render(workspace, draft)
    oil, calendar = ids(article)[0], ids(article)[1]
    assert article.carriers[1] == ["FIXTURE an opening that restates the oil [1].",
                                   "FIXTURE the keeper logged lamp oil [1].", "FIXTURE it was every winter [1]."]
    with pytest.raises(pipeline.ArticleError):
        pipeline.remove_sentences(draft, oil)                         # not before the verdict
    for chunk_id in ids(article):
        pipeline.set_verdict(draft, chunk_id, "supports")
    pipeline.set_verdict(draft, oil, "does not", "FIXTURE reason: the passage is about pears")
    assert pipeline.status(draft, pipeline.render(workspace, draft)) == "draft"

    pipeline.remove_sentences(draft, oil)
    after = pipeline.render(workspace, draft)

    assert pipeline.status(draft, after) == "reviewed"
    assert "lamp oil" not in after.markdown and "every winter" not in after.markdown and "restates the oil" not in after.markdown
    assert "FIXTURE the calendar agrees [1]." in after.markdown        # renumbered, with no gap
    assert ids(after)[0] == calendar and [note["n"] for note in after.notes] == [1, 2, 3]
    assert "p. 3." not in after.markdown.split("## Sources")[1]        # its source line went with it
    record = pipeline.notes_record(draft, after)
    assert record[-1] == {**record[-1], "chunk_id": oil, "n": None, "verdict": "does not", "sentences_removed": True}
    assert assemble.support_rate(record) == {"supports": 3, "partly": 0, "does not": 1, "not judged": 0, "notes": 4, "pairs": 4}


def test_generated_frame_sentences_without_a_note_are_raised_for_the_researcher(workspace, draft):
    article = pipeline.render(workspace, draft)

    assert article.unnoted == [{"what": "introduction", "sentences": 1}]
    assert pipeline.build_record(workspace, draft, article)["frame_sentences_without_a_note"] == article.unnoted


def test_the_record_holds_what_the_plan_says_and_no_passage_text(workspace, draft, tmp_path):
    folder = pipeline.save(workspace, draft, tmp_path / "out")
    text = (folder / "record.json").read_text(encoding="utf-8")
    record = json.loads(text)

    assert "FIXTURE passage:" not in text                              # passages by id, never by text
    assert record["schema_version"] == 4 and record["status"] == "draft"
    assert record["model"] == ask.settings.llm_model and record["sections"][0]["prompt_sha256_12"] == "fixturehash"
    section = record["sections"][0]
    assert {"heading", "brief", "kept_by_researcher", "gap_stated", "blocked", "evidence", "result",
            "validation_failures", "footnote_text_cut_from", "voice"} <= set(section)
    assert section["evidence"][0].keys() == {"handle", "chunk_id", "score"}
    assert record["frame"]["introduction"]["origin"] == "generated"
    assert record["frame"]["conclusion"] == {"origin": "researcher", "text": "FIXTURE my own closing words."}
    assert record["support"]["notes"] == 4                              # four notes, one of them on two sentences:
    assert record["support"]["pairs"] == record["support"]["not judged"] == 5      # five things to judge
    assert record["support_excludes"] == "text written by the researcher, which carries no notes"
    assert record["source_filter"]["passages_available"] == 5
    assert (folder / "article.md").read_text(encoding="utf-8") == pipeline.render(workspace, draft).markdown


def test_a_saved_draft_is_reopened_without_a_model_call_and_keeps_its_verdicts(workspace, draft, tmp_path, monkeypatch):
    first = pipeline.render(workspace, draft)
    pipeline.set_verdict(draft, ids(first)[0], "does not", "FIXTURE reason")
    pipeline.remove_sentences(draft, ids(first)[0])
    pipeline.set_verdict(draft, ids(first)[1], "supports")
    folder = pipeline.save(workspace, draft, tmp_path / "out")
    monkeypatch.setattr(ask, "call_model", lambda *a: pytest.fail("reopening a draft called the model"))
    monkeypatch.setattr(ask, "embed_texts", lambda *a, **k: pytest.fail("reopening a draft embedded something"))

    reopened = pipeline.load(folder, workspace)

    assert pipeline.render(workspace, reopened).markdown == pipeline.render(workspace, draft).markdown
    assert reopened.removed == draft.removed and reopened.verdicts == draft.verdicts
    assert reopened.article_id == draft.article_id
    assert json.loads((folder / "record.json").read_text(encoding="utf-8"))["status"] == "draft"
    for chunk_id in ids(first)[2:]:
        pipeline.set_verdict(reopened, chunk_id, "supports")
    assert pipeline.save(workspace, reopened, tmp_path / "out") == folder          # the same folder, not a copy
    assert json.loads((folder / "record.json").read_text(encoding="utf-8"))["status"] == "reviewed"
    assert [row["status"] for row in pipeline.saved_articles(tmp_path / "out")] == ["reviewed"]


def test_a_saved_draft_is_not_reopened_against_another_index_or_document(workspace, draft, tmp_path):
    folder = pipeline.save(workspace, draft, tmp_path / "out")

    changed = pipeline.Workspace(workspace.document, workspace.sources, {**workspace.manifest, "corpus_text_sha256": "other"})
    with pytest.raises(pipeline.ArticleError, match="index has changed"):
        pipeline.load(folder, changed)
    other = pipeline.Workspace(dataclasses.replace(workspace.document, document_id="another-thesis"),
                               workspace.sources, workspace.manifest)
    with pytest.raises(pipeline.ArticleError, match="not the thesis now open"):
        pipeline.load(folder, other)


def test_the_researcher_can_drop_a_section_or_state_that_the_thesis_does_not_cover_it(workspace, monkeypatch):
    monkeypatch.setattr(ask, "call_model", Scripted({
        **SCRIPT, "orchard": REFUSAL,
        "tramway": payload("FIXTURE fluent text that cites nothing.", cites=[])}))
    sections = [pipeline.draft_section(workspace, f"FIXTURE heading {n + 1}", brief) for n, brief in enumerate(BRIEFS)]
    draft = pipeline.Draft("FIXTURE title", sections)

    plain = pipeline.render(workspace, draft)
    assert "FIXTURE heading 2" not in plain.markdown and len(plain.blocked) == 2

    sections[1].state_gap = True          # refused: the researcher chooses to say so
    sections[2].state_gap = True          # failed validation: this choice does not apply
    sections[0].kept = False              # a good section the researcher does not want
    chosen = pipeline.render(workspace, draft)

    assert f"## FIXTURE heading 2\n\n{assemble.NOT_COVERED_LINE}" in chosen.markdown
    assert "FIXTURE heading 3" not in chosen.markdown and "FIXTURE heading 1" not in chosen.markdown
    assert [item["what"] for item in chosen.blocked] == ["section: FIXTURE heading 3"]
    record = pipeline.build_record(workspace, draft, chosen)
    assert [s["kept_by_researcher"] for s in record["sections"]] == [False, True, True]
    assert [s["gap_stated"] for s in record["sections"]] == [False, True, True]
    assert record["sections"][2]["blocked"].startswith("validation failed")


def test_a_note_on_an_unnumbered_page_is_listed_as_it_is_cited_today(workspace, monkeypatch):
    monkeypatch.setattr(ask, "call_model", lambda question, items, instructions=None: (
        payload(f"FIXTURE the plate shows a chart [{next(i.handle for i in items if i.chunk['page_start'] is None)}].",
                cites=[next(i.handle for i in items if i.chunk["page_start"] is None)]), "fixturehash"))
    section = pipeline.draft_section(workspace, "FIXTURE plate", "FIXTURE: what does the unnumbered plate show of the harbour chart?")
    text = pipeline.render(workspace, pipeline.Draft("FIXTURE title", [section])).markdown

    assert "None" not in text
    assert text.split("## Sources\n\n")[1].startswith("[1] ") and "[VERIFY]" in text


def test_the_outline_has_three_to_six_sections_and_a_title():
    good = [("FIXTURE h", "FIXTURE q?")] * 3
    pipeline.check_outline("FIXTURE title", good)
    pipeline.check_outline("FIXTURE title", good * 2)
    for title, outline in (("FIXTURE title", good[:2]), ("FIXTURE title", good * 2 + good[:1]),
                           ("  ", good), ("FIXTURE title", good[:2] + [("", "FIXTURE q?")])):
        with pytest.raises(pipeline.ArticleError):
            pipeline.check_outline(title, outline)


def test_the_evaluation_and_the_answer_path_do_not_know_the_article_writer():
    for module in ("evaluate.py", "ask.py", "main.py", "ingest.py", "evaluation/metrics.py"):
        source = (ROOT / module).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import) article\b", source, re.MULTILINE), module
