"""The web UI's "Write an article" view — `app.py` (PLAN_V6, Sprint W2).

The real `app.py` runs under Streamlit's test harness against the built-in
index and its committed footnote map. The embedding provider is an offline
fake and the generation model is replaced at `ask.call_model`. Every brief and
every scripted answer is synthetic; no test asserts on a word of the thesis.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

import ask
import runs
from article import assemble, pipeline
from config import ROOT, settings
from test_app import all_text, button

OUTLINE = ("FIXTURE first heading | FIXTURE-A what does the harbour ledger say?\n"
           "FIXTURE second heading | FIXTURE-B what does the grafting calendar say?\n"
           "FIXTURE third heading | FIXTURE-C what does the tramway timetable say?")


def payload(answer, cites, sufficiency="sufficient"):
    return {"evidence_sufficiency": sufficiency, "answer": answer, "limitations": [], "ai_interpretation": [],
            "unsupported_by_evidence": [], "citations_used": cites}


REFUSAL = {"evidence_sufficiency": "insufficient", "answer": None, "limitations": [], "ai_interpretation": [],
           "unsupported_by_evidence": ["FIXTURE: glaciers"], "citations_used": []}
SCRIPT = {
    "FIXTURE-A": payload("FIXTURE the ledger says one thing [E1]. FIXTURE and it says another [E2].", ["E1", "E2"]),
    "FIXTURE-B": payload("FIXTURE the calendar lists rootstock [E3].", ["E3"]),
    "FIXTURE-C": payload("FIXTURE the timetable changed [E4].", ["E4"]),
    "introduce": payload("FIXTURE a generated opening [E1].", ["E1"]),
    "connect": payload("FIXTURE a generated bridge [E1].", ["E1"]),
    "establish": payload("FIXTURE a generated closing [E1].", ["E1"]),
}


class Scripted:
    def __init__(self, script):
        self.script, self.calls = dict(script), []

    def __call__(self, question, items, instructions=None):
        self.calls.append(question)
        if instructions and instructions.startswith("EDITORIAL TASK"):
            self.edits = getattr(self, "edits", 0) + 1
            key = next(key for key in self.script if key in question)
            return self.script.get(f"EDIT:{key}", self.script[key]), "fixturehash"
        return next(value for key, value in self.script.items() if key in question), "fixturehash"


def offline_embedding(texts, *, is_query=False, progress=False):
    """Deterministic and offline, in the built-in index's own dimension."""
    width = np.load(settings.index_dir / "vectors.npy", mmap_mode="r").shape[1]
    rows = []
    for text in texts:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        vector = np.random.default_rng(seed).standard_normal(width).astype(np.float32)
        rows.append(vector / np.linalg.norm(vector))
    return np.stack(rows)


@pytest.fixture
def view(tmp_path, monkeypatch):
    """The app on its article view, with a scripted model and an empty output folder."""
    monkeypatch.setattr(runs, "settings", dataclasses.replace(runs.settings, runs_path=tmp_path / "runs.jsonl"))
    monkeypatch.setattr(pipeline, "DEFAULT_OUT_DIR", tmp_path / "articles")
    monkeypatch.setattr(ask, "embed_texts", offline_embedding)
    model = Scripted(SCRIPT)
    monkeypatch.setattr(ask, "call_model", model)

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    at.radio[0].set_value("Write an article")
    at.run()
    at.model, at.out = model, tmp_path / "articles"
    return at


def fill(at: AppTest, title="FIXTURE harbour title", outline=OUTLINE) -> AppTest:
    at.text_input(key="article_title").set_value(title)
    at.text_area(key="article_outline").set_value(outline)
    return at.run()


def draft(at: AppTest, **kwargs) -> AppTest:
    fill(at, **kwargs)
    button(at, "Draft the article").click()
    return at.run()


def record(at: AppTest) -> dict:
    (path,) = at.out.glob("*/record.json")
    return json.loads(path.read_text(encoding="utf-8"))


def article_file(at: AppTest) -> str:
    (path,) = at.out.glob("*/article.md")
    return path.read_text(encoding="utf-8")


def judge(at: AppTest, verdicts: list[str]) -> AppTest:
    radios = [r for r in at.radio if r.key and r.key.startswith("article_verdict_")]
    assert len(radios) == len(verdicts)
    for radio, verdict in zip(radios, verdicts):
        radio.set_value(verdict)
    at.run()
    button(at, "Record my verdicts").click()
    return at.run()


# ---------------------------------------------------------------------------


def test_the_view_opens_on_topics_from_the_index_without_calling_a_model(view):
    workspace = pipeline.open_workspace()
    options = view.selectbox(key="article_topic").options

    assert not view.exception
    assert view.title[0].value == "Write an article"
    assert options[0] == "My own topic" and len(options) == 1 + len(workspace.topics())
    assert not any(option.startswith(("Bibliography", "References")) for option in options)
    assert "It drafts; you check every note and decide." in all_text(view)
    assert "reference-list passages left out" in all_text(view)
    assert view.model.calls == [] and not view.out.exists()


def test_an_outline_can_be_filled_from_a_chapters_own_section_titles(view):
    view.selectbox(key="article_topic").set_value(view.selectbox(key="article_topic").options[8])
    view.run()
    button(view, "Fill the outline from this chapter's sections").click()
    view.run()
    lines = view.text_area(key="article_outline").value.splitlines()

    assert len(lines) == 3
    assert all(" | What does the thesis say about “" in line for line in lines)
    assert view.model.calls == []


@pytest.mark.parametrize(
    ("title", "outline", "message"),
    [
        ("", OUTLINE, "Give the article a title."),
        ("FIXTURE title", "\n".join(OUTLINE.splitlines()[:2]), "An outline has 3 to 6 sections; this one has 2."),
        ("FIXTURE title", OUTLINE + "\nFIXTURE heading with no question", "Every section needs a heading and a question"),
    ],
)
def test_nothing_is_drafted_from_an_outline_that_is_not_ready(view, title, outline, message):
    draft(view, title=title, outline=outline)

    assert message in all_text(view)
    assert view.model.calls == [] and not view.out.exists()


def test_a_topic_becomes_a_saved_reviewed_article_with_no_file_edited_by_hand(view):
    view.text_area(key="article_introduction_text").set_value("FIXTURE my own opening words.")
    draft(view)
    saved = record(view)

    assert not view.exception
    assert len(view.model.calls) == 3                                   # one call per section, none for the frame
    assert saved["status"] == "draft" and saved["support"]["not judged"] == saved["support"]["notes"] == 4
    assert saved["frame"]["introduction"] == {"origin": "researcher", "text": "FIXTURE my own opening words."}
    text = article_file(view)
    assert text.startswith(f"*{assemble.DRAFT_LINE}*") and "## FIXTURE second heading" in text and "## Sources" in text
    assert "FIXTURE my own opening words." in text and assemble.COMMENTARY_LABEL not in text
    assert "Draft: not every note has been judged" in all_text(view)
    assert len(view.text) == 4                                          # each note beside the passage it cites

    judge(view, ["supports", "supports", "partly", "supports"])
    saved = record(view)

    assert saved["status"] == "reviewed"
    assert saved["support"] == {"supports": 3, "partly": 1, "does not": 0, "not judged": 0, "notes": 4}
    assert all(note["judged_by"] == "researcher" and note["judged_at"] for note in saved["notes"])
    assert assemble.DRAFT_LINE not in article_file(view)
    assert article_file(view).rstrip().endswith(f"*{assemble.CLOSING_LINE_REVIEWED}*")
    assert "Reviewed: every note has your verdict." in all_text(view)
    assert len(view.model.calls) == 3                                   # reviewing calls no model


def test_a_note_judged_does_not_keeps_the_draft_until_its_sentences_are_removed(view):
    draft(view)
    judge(view, ["supports", "does not", "supports", "supports"])

    assert record(view)["status"] == "draft"
    assert "FIXTURE and it says another [2]." in article_file(view)
    assert "The article stays a draft until these sentences are removed." in all_text(view)

    button(view, "Remove the sentences that carry this note").click()
    view.run()
    saved = record(view)

    assert "FIXTURE and it says another" not in article_file(view)
    assert "FIXTURE the calendar lists rootstock [2]." in article_file(view)       # renumbered, no gap
    assert saved["status"] == "reviewed"
    assert saved["support"] == {"supports": 3, "partly": 0, "does not": 1, "not judged": 0, "notes": 4}
    removed = [note for note in saved["notes"] if note["sentences_removed"]]
    assert [(note["n"], note["verdict"]) for note in removed] == [(None, "does not")]


def test_generated_frame_text_is_marked_as_commentary_and_costs_one_call_each(view):
    for part in ("introduction", "transitions", "conclusion"):
        view.radio(key=f"article_{part}_origin").set_value("Generate as labelled commentary")
    draft(view)
    text = article_file(view)

    assert len(view.model.calls) == 3 + 1 + 2 + 1
    assert text.count(assemble.COMMENTARY_LABEL) == 4
    assert f"{assemble.COMMENTARY_LABEL} FIXTURE a generated opening [1]." in text
    assert record(view)["frame"]["conclusion"]["origin"] == "generated"
    assert record(view)["support"]["notes"] == 4                        # the frame added no note of its own


def test_a_blocked_section_is_shown_with_its_reason_and_a_refused_one_can_be_stated(view):
    view.model.script["FIXTURE-B"] = REFUSAL
    view.model.script["FIXTURE-C"] = payload("FIXTURE fluent text that cites nothing.", [])
    draft(view)
    text = all_text(view)

    assert "**FIXTURE second heading** was not written: the thesis does not hold enough evidence for this." in text
    assert "**FIXTURE third heading** is blocked and left out: validation failed: ungrounded_answer" in text
    assert "FIXTURE second heading" not in article_file(view) and "FIXTURE third heading" not in article_file(view)
    assert len(view.model.calls) == 3                                   # nothing was retried

    next(c for c in view.checkbox if c.label == "Say so in the article, under this heading").check()
    view.run()

    assert f"## FIXTURE second heading\n\n{assemble.NOT_COVERED_LINE}" in article_file(view)
    assert "FIXTURE third heading" not in article_file(view)
    assert record(view)["sections"][1]["gap_stated"] is True


def test_the_researcher_can_drop_a_drafted_section(view):
    draft(view)
    next(c for c in view.checkbox if c.label == "Keep section: FIXTURE second heading").uncheck()
    view.run()

    assert "FIXTURE second heading" not in article_file(view)
    assert record(view)["sections"][1]["kept_by_researcher"] is False
    assert record(view)["support"]["notes"] == 3


def test_a_saved_article_is_reopened_with_its_verdicts_and_no_model_call(view):
    draft(view)
    judge(view, ["supports", "not judged", "not judged", "not judged"])
    button(view, "Start another article").click()
    view.run()
    assert view.text_input(key="article_title") is not None            # back on the setup steps

    button(view, "Open this article").click()
    view.run()
    radios = [r.value for r in view.radio if r.key and r.key.startswith("article_verdict_")]

    assert not view.exception
    assert radios == ["supports", "not judged", "not judged", "not judged"]
    assert "## FIXTURE first heading" in all_text(view)
    assert len(view.model.calls) == 3 and len(list(view.out.glob("*"))) == 1


def test_the_other_views_do_not_reach_the_article_writer_and_it_records_no_query_run(view, tmp_path):
    draft(view)

    assert not (tmp_path / "runs.jsonl").exists()                       # an article is not a query run
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "draft_from_evidence" not in source                          # only the article package calls it
    chat = source[source.index("def render_chat"):source.index("def main()")]
    assert "pipeline." not in chat and "article" not in chat


# --- layout and accessibility (docs/decisions/0004-ui-accessibility.md) ---------------------


def page_style(at: AppTest) -> str:
    return next(m.value for m in at.markdown if "<style>" in m.value)


def test_the_page_style_never_hides_the_button_that_opens_the_sidebar(view):
    """On a phone the sidebar starts closed. Hiding Streamlit's whole toolbar hid
    the only way to open it, so views and theses could not be changed."""
    hidden = page_style(view).split("{visibility: hidden;}")[0]

    assert '"stToolbar"]' not in hidden and "stExpandSidebarButton" not in hidden and "stHeader" not in hidden
    assert "stToolbarActions" in hidden and "stMainMenu" in hidden          # the developer furniture still goes


def test_captions_and_quoted_sentences_take_the_themes_text_colour(view):
    style = page_style(view)
    rule = style[style.index('[data-testid="stCaptionContainer"]'):style.index(":focus-visible")]

    assert "blockquote" in rule and "color: inherit !important" in rule
    assert not __import__("re").search(r"color:\s*#", rule)                # no fixed colour: dark themes must hold too


def test_each_page_has_one_title_and_no_skipped_heading_level(view):
    draft(view)
    shown = "\n".join(m.value for m in view.markdown)

    assert len(view.title) == 1 and len(view.header) == 1                  # h1, then the thesis as h2
    assert all(s.value for s in view.subheader)                             # the steps are h3
    assert "### FIXTURE harbour title" in shown and "\n# FIXTURE harbour title" not in shown
    assert "#### FIXTURE first heading" in shown
    assert "\n# FIXTURE harbour title" in article_file(view)               # the saved file keeps its own levels


def test_a_cited_passage_is_shown_whole_and_reflowed(view):
    draft(view)
    workspace = pipeline.open_workspace()
    notes = record(view)["notes"]

    assert [t.value for t in view.text] == [" ".join(workspace.by_id[n["chunk_id"]]["text"].split()) for n in notes]
    assert not any("\n" in t.value for t in view.text)


# --- commentary (ADR 0005) -------------------------------------------------------------------


def test_commentary_is_off_until_switched_on_and_then_waits_for_a_verdict(view):
    view.model.script["FIXTURE-A"] = {**SCRIPT["FIXTURE-A"], "ai_interpretation": ["FIXTURE a reading of the ledger [E1]."]}
    draft(view)

    assert assemble.COMMENTARY_LABEL not in article_file(view)         # off by default
    next(c for c in view.checkbox if c.label == "Show the model's commentary in the article").check()
    view.run()
    assert f"{assemble.COMMENTARY_LABEL} FIXTURE a reading of the ledger [1]." in article_file(view)

    judge(view, ["supports"] * 4)                                       # every note judged; the commentary is not
    assert record(view)["status"] == "draft"
    assert "a commentary paragraph is waiting for your verdict" in all_text(view)

    view.radio(key="article_commentary_verdict_0").set_value("reject")
    view.run()
    button(view, "Record my verdicts").click()
    view.run()

    assert record(view)["status"] == "reviewed"
    assert assemble.COMMENTARY_LABEL not in article_file(view)
    assert record(view)["sections"][0]["commentary"]["verdict"] == "reject"
    assert len(view.model.calls) == 3


# --- the editorial pass (ADR 0005) -----------------------------------------------------------


def test_the_editorial_pass_is_off_by_default_and_shows_what_it_kept_and_what_it_rejected(view):
    view.model.script["EDIT:FIXTURE-B"] = payload("FIXTURE the calendar, moreover, lists rootstock [E3].", ["E3"])
    view.model.script["EDIT:FIXTURE-C"] = payload("FIXTURE Harland changed the timetable [E4].", ["E4"])
    assert view.checkbox(key="article_editorial").value is False
    view.checkbox(key="article_editorial").check()
    draft(view)
    text, saved = article_file(view), record(view)

    assert len(view.model.calls) == 6 and view.model.edits == 3         # one more call per section, once
    assert "FIXTURE the calendar, moreover, lists rootstock [3]." in text
    assert "FIXTURE the timetable changed [4]." in text and "Harland" not in text      # rejected: the original stands
    assert [s["editorial"]["accepted"] for s in saved["sections"]] == [True, True, False]
    assert saved["sections"][2]["editorial"]["rejected_because"] == ["new_terms: the rewrite adds “Harland”"]
    shown = all_text(view)
    assert "rewrite rejected; the original stands" in shown and "new_terms: the rewrite adds “Harland”" in shown


# --- save as you go, and resume (ADR 0005) -----------------------------------------------------


class Restart(BaseException):
    """The container going away in the middle of a call."""


def test_a_draft_cut_short_is_on_disk_and_resumes_without_resending_what_was_done(view, monkeypatch):
    # The container goes away during the third section: the pipeline is run here, outside the page.
    outline = [tuple(part.strip() for part in line.split("|")) for line in OUTLINE.splitlines()]
    workspace = pipeline.open_workspace()

    def dying(question, items, instructions=None):
        if "FIXTURE-C" in question:
            raise Restart()
        return view.model(question, items, instructions)

    monkeypatch.setattr(ask, "call_model", dying)
    with pytest.raises(Restart):
        pipeline.run(workspace, pipeline.new_draft("FIXTURE harbour title", outline))
    saved = record(view)
    assert saved["status"] == "drafting" and [bool(s.get("pending")) for s in saved["sections"]] == [False, False, True]

    monkeypatch.setattr(ask, "call_model", view.model)                  # the container is back; the page is opened afresh
    view.run()
    listed = view.selectbox(key="article_saved")
    assert listed.format_func(listed.value) == "FIXTURE harbour title — unfinished, 1 model call(s) left"
    button(view, "Open this article").click()
    view.run()
    assert "1 model call(s) remain" in all_text(view) and "## FIXTURE third heading" not in article_file(view)
    before = len(view.model.calls)
    button(view, "Resume drafting").click()
    view.run()

    assert len(view.model.calls) == before + 1 and "FIXTURE-C" in view.model.calls[-1]      # one call: the missing one
    assert record(view)["status"] == "draft" and "## FIXTURE third heading" in article_file(view)
    assert len(list(view.out.glob("*"))) == 1 and not view.exception
