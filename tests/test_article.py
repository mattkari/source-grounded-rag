"""The article writer's W0 trial — `article/` and `scripts/article_trial.py` (PLAN_V6).

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
from article import assemble, footnotes, topics, voice
from article.assemble import GENERATED, RESEARCHER, FrameElement, SectionDraft
from documents import LayoutProfile, default_document
from pdf_factory import ThesisSpec, make_thesis
from scripts import article_trial

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
                                                            limitations=["FIXTURE the passages give no date [E3]."]), items)),
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
    sources = text.split("## Sources\n\n")[1].split("\n\n")[0].splitlines()

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
    text = assemble.assemble(title="FIXTURE title", document=document, sections=three).markdown

    assert f"{assemble.COMMENTARY_LABEL} FIXTURE a reading of it [3]." in text
    assert text.count(assemble.COMMENTARY_LABEL) == 1
    assert "FIXTURE the passages give no date [4]." in text      # a stated limit is kept in the section


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
    assert assemble.support_rate(notes) == {"supports": 0, "partly": 0, "does not": 0, "not judged": 4, "notes": 4}

    notes[0]["verdict"], notes[1]["verdict"], notes[2]["verdict"] = "supports", "does not", "FIXTURE typo"
    assert assemble.support_rate(notes) == {"supports": 1, "partly": 0, "does not": 1, "not judged": 2, "notes": 4}


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
    assert "FIXTURE unnumbered plate — 1 passages, pages not printed" in report
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
        self.script, self.calls = script, []

    def __call__(self, question, items):
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
    monkeypatch.setattr(ask, "settings", dataclasses.replace(ask.settings, pdf_path=tmp_path / "no.pdf"))

    class Trial:
        out_dir = tmp_path / "output"
        log = io.StringIO()
        model = None

        def run(self, script=SCRIPT, **kwargs):
            self.model = Scripted(script)
            monkeypatch.setattr(ask, "call_model", self.model)
            args = dict(chapter=1, title="FIXTURE harbour title", briefs=list(BRIEFS), headings=None,
                        frame=GENERATED, references=[], out_dir=self.out_dir, stream=self.log)
            args.update(kwargs)
            self.code = article_trial.run_trial(**args)
            folders = sorted(self.out_dir.glob("trial_*")) if self.out_dir.exists() else []
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
    assert t.record["kind"] == "w0_trial" and t.record["status"] == "draft"
    assert t.record["model"] == ask.settings.llm_model              # recorded, never set (hard rule 1)
    assert t.record["title"] == {"origin": "researcher", "text": "FIXTURE harbour title"}
    assert [s["blocked"] for s in t.record["sections"]] == [None, None, None]
    assert t.record["frame"]["introduction"]["origin"] == "generated"
    assert t.record["support"] == {"supports": 0, "partly": 0, "does not": 0, "not judged": 3, "notes": 3}
    assert t.record["footnotes"] is None                            # no PDF here: not measured, not zero
    assert "Notes to check: 3." in t.log.getvalue()


def test_frame_text_is_drafted_only_from_passages_the_sections_cite(trial):
    t = trial.run()
    cited = {note["chunk_id"] for note in t.record["notes"]}
    sections, frame = t.model.calls[:3], t.model.calls[3:]

    assert len(sections) == 3 and len(frame) == 4                   # one call each; nothing repeated
    assert all(len(chunk_ids) > 3 for _, chunk_ids, _ in sections)  # sections retrieve
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
    assert len(list(trial.out_dir.glob("trial_*"))) == 2


def test_the_trial_counts_cited_passages_that_contain_footnote_text(trial, tmp_path, monkeypatch, document):
    source = footnoted_thesis(tmp_path, document)
    note = footnotes.build(source).by_page[min(footnotes.build(source).by_page)][0]
    page = min(footnotes.build(source).by_page)
    index = Path(ask.settings.index_dir) / "chunks.json"
    stored = json.loads(index.read_text(encoding="utf-8"))
    for n in (0, 5):        # the lamp-oil passage is cited below; the canal passage is only retrieved
        stored[n].update(pdf_page_start=page, pdf_page_end=page, text=stored[n]["text"] + " " + note)
    index.write_text(json.dumps(stored), encoding="utf-8")
    monkeypatch.setattr(ask, "settings", dataclasses.replace(
        ask.settings, pdf_path=source.pdf_path, body_size=12.0, body_min_size=10.5,
        header_band_y=60.0, footnote_band_y=780.0))

    t = trial.run(frame="none")

    assert t.record["footnotes"]["footnotes_in_document"] == 18
    assert t.record["footnotes"]["cited_containing_footnote_text"] == 1
    assert t.record["footnotes"]["retrieved_containing_footnote_text"] == 2
    assert t.record["footnotes"]["passages_cited"] == 3
    assert "passages cited that contain footnote text : 1/3" in t.log.getvalue()


def test_the_trial_refuses_a_chapter_that_is_not_listed_or_the_wrong_number_of_briefs(trial):
    assert trial.run(chapter=7).code == 2
    assert trial.run(briefs=BRIEFS[:2]).code == 2
    assert trial.model.calls == [] and not trial.out_dir.exists()


def test_listing_topics_calls_no_model(trial, monkeypatch, capsys):
    monkeypatch.setattr(ask, "call_model", lambda *a: pytest.fail("the topic listing called the model"))
    monkeypatch.setattr(ask, "embed_texts", lambda *a, **k: pytest.fail("the topic listing embedded something"))

    assert article_trial.main(["--topics"]) == 0
    assert " 1. FIXTURE chapter — 5 passages, pp. 3–11" in capsys.readouterr().out


def test_no_shell_exposes_drafting_from_chosen_passages():
    """`ask.draft_from_evidence` is for the article writer only (PLAN_V6 §6)."""
    for shell in ("app.py", "main.py", "evaluate.py"):
        assert "draft_from_evidence" not in (ROOT / shell).read_text(encoding="utf-8"), shell
    source = (ROOT / "ask.py").read_text(encoding="utf-8")
    assert "draft_from_evidence" not in source[source.index("def main()"):]
