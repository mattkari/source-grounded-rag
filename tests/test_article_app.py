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
        if instructions and instructions.startswith("FRAME TASK"):
            self.frames = getattr(self, "frames", []) + [(question, list(items), instructions)]
            return self.script["FRAME"], "fixturehash"
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


def draft(at: AppTest, options=None, **kwargs) -> AppTest:
    """Walk the steps a researcher walks: outline, frame and options, the plan, draft.
    `options` sets the frame and option widgets on their own step."""
    fill(at, **kwargs)
    button(at, "Next: frame and options").click()
    at.run()
    if not any(b.label == "Next: check the plan" for b in at.button):
        return at                                                        # the outline was not accepted
    if options:
        options(at)
        at.run()
    button(at, "Next: check the plan").click()
    at.run()
    button(at, "Draft the article").click()
    return at.run()


def finish(at: AppTest) -> AppTest:
    button(at, "Next: the finished article").click()
    return at.run()


def record(at: AppTest) -> dict:
    (path,) = at.out.glob("*/record.json")
    return json.loads(path.read_text(encoding="utf-8"))


def article_file(at: AppTest) -> str:
    (path,) = at.out.glob("*/article.md")
    return path.read_text(encoding="utf-8")


def current_verdict(at: AppTest):
    """The one verdict control on the screen: a note's, or a commentary paragraph's."""
    (radio,) = [r for r in at.radio if r.key and r.key.startswith(("article_verdict_", "article_commentary_verdict_"))]
    return radio


def judge(at: AppTest, verdicts: list[str]) -> AppTest:
    """Judge the items in order from the one now on screen, one at a time."""
    for verdict in verdicts:
        current_verdict(at).set_value(verdict)
        at.run()
        next(b for b in at.button if b.label in ("Save and next", "Save my verdict")).click()
        at.run()
    return at


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
    draft(view, options=lambda at: at.text_area(key="article_introduction_text").set_value("FIXTURE my own opening words."))
    saved = record(view)

    assert not view.exception
    assert len(view.model.calls) == 3                                   # one call per section, none for the frame
    assert saved["status"] == "draft" and saved["support"]["not judged"] == saved["support"]["notes"] == 4
    assert saved["frame"]["introduction"] == {"origin": "researcher", "text": "FIXTURE my own opening words."}
    text = article_file(view)
    assert text.startswith(f"*{assemble.DRAFT_LINE}*") and "## FIXTURE second heading" in text and "## Sources" in text
    assert "FIXTURE my own opening words." in text and assemble.COMMENTARY_LABEL not in text
    assert "**1 of 4** · judged so far: 0 of 4" in all_text(view)
    assert len(view.text) == 1                                          # one note on screen, beside the passage it cites

    judge(view, ["supports", "supports", "partly", "supports"])
    saved = record(view)
    assert "**4 of 4** · judged so far: 4 of 4" in all_text(view)
    finish(view)

    assert saved["status"] == "reviewed"
    assert saved["support"] == {"supports": 3, "partly": 1, "does not": 0, "not judged": 0, "notes": 4, "pairs": 4}
    assert all(pair["judged_by"] == "researcher" and pair["judged_at"] for pair in saved["pairs"])
    assert not any(pair["carried_over"] for pair in saved["pairs"])      # each given on its own sentence
    assert assemble.DRAFT_LINE not in article_file(view)
    assert article_file(view).rstrip().endswith(f"*{assemble.CLOSING_LINE_REVIEWED}*")
    assert "Reviewed: every note has your verdict." in all_text(view)
    assert len(view.model.calls) == 3                                   # reviewing calls no model


def test_a_note_judged_does_not_keeps_the_draft_until_its_sentences_are_removed(view):
    draft(view)
    judge(view, ["supports", "does not", "supports", "supports"])

    assert record(view)["status"] == "draft"
    assert "FIXTURE and it says another [2]." in article_file(view)
    button(view, "Previous").click()
    view.run()
    button(view, "Previous").click()
    view.run()                                                          # back on the note judged "does not"
    assert "**2 of 4**" in all_text(view) and current_verdict(view).value == "does not"
    assert "The article stays a draft until this sentence is edited or deleted." in all_text(view)

    button(view, "Delete this sentence").click()
    view.run()
    saved = record(view)

    assert "FIXTURE and it says another" not in article_file(view)
    assert "FIXTURE the calendar lists rootstock [2]." in article_file(view)       # renumbered, no gap
    assert saved["status"] == "reviewed"
    assert saved["support"] == {"supports": 3, "partly": 0, "does not": 1, "not judged": 0, "notes": 4, "pairs": 4}
    deleted = [pair for pair in saved["pairs"] if not pair["in_article"]]
    assert [(pair["n"], pair["verdict"], pair["sentence_deleted"]) for pair in deleted] == [(None, "does not", True)]
    assert saved["sentences"]["edits"]["0.1"]["original"] == "FIXTURE and it says another [E2]."     # what it said is kept


def test_an_introduction_is_suggested_from_the_articles_own_text_and_printed_only_when_used(view):
    view.model.script["FRAME"] = payload("FIXTURE the ledger and the calendar together tell of the timetable.", [])
    draft(view)
    judge(view, ["supports"] * 4)
    finish(view)
    assert len(view.model.calls) == 3 and assemble.COMMENTARY_LABEL not in article_file(view)

    button(view, "Suggest an introduction (one model call)").click()
    view.run()
    question, items, instructions = view.model.frames[0]
    assert len(view.model.calls) == 4 and items == []                   # one call, and it is shown no passage
    assert "FIXTURE the ledger says one thing." in instructions and "[E" not in instructions and "[1]" not in instructions
    assert view.text_area(key="article_frame_introduction").value == "FIXTURE the ledger and the calendar together tell of the timetable."
    assert "together tell of the timetable" not in article_file(view)   # a suggestion prints nothing by itself

    view.text_area(key="article_frame_introduction").set_value("FIXTURE the ledger and the calendar tell of the timetable.")
    view.run()
    button(view, "Use this introduction").click()
    view.run()
    text, saved = article_file(view), record(view)

    assert "FIXTURE the ledger and the calendar tell of the timetable." in text
    assert assemble.COMMENTARY_LABEL not in text                        # printed as the article's own text
    assert saved["frame"]["introduction"] == {
        "origin": "suggested by model, accepted by researcher",
        "text": "FIXTURE the ledger and the calendar tell of the timetable.",
        "suggestion": "FIXTURE the ledger and the calendar together tell of the timetable.",
        "edited_by_researcher": True}
    assert saved["status"] == "reviewed" and saved["support"]["pairs"] == 4      # it adds nothing to judge
    assert "suggested by model, accepted by researcher" in all_text(view)


def test_a_suggestion_that_adds_a_name_is_not_offered_and_the_reason_is_shown(view):
    view.model.script["FRAME"] = payload("FIXTURE Harland kept the ledger in 1923.", [])
    draft(view)
    finish(view)
    button(view, "Suggest a conclusion (one model call)").click()
    view.run()

    assert view.text_area(key="article_frame_conclusion").value == ""
    assert "The suggestion asked for was not offered: new_terms: the suggestion adds “1923”, “Harland”." in all_text(view)
    assert record(view)["frame_suggestions"]["conclusion"][0]["rejected_because"] != []
    assert record(view)["frame"]["conclusion"] is None and len(view.model.calls) == 4      # asked once, not again


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
    assert "3 of 3 drafted sections kept" in view.expander[0].label
    next(c for c in view.checkbox if c.label == "Keep section: FIXTURE second heading").uncheck()
    view.run()

    assert "FIXTURE second heading" not in article_file(view)
    assert record(view)["sections"][1]["kept_by_researcher"] is False
    assert record(view)["support"]["notes"] == 3


def test_a_saved_article_is_reopened_with_its_verdicts_and_no_model_call(view):
    draft(view)
    judge(view, ["supports"])
    button(view, "Start another article").click()
    view.run()
    assert view.text_input(key="article_title").value == ""             # back on the first step, with a clean plan

    button(view, "Open this article").click()
    view.run()

    assert not view.exception
    assert "**2 of 4** · judged so far: 1 of 4" in all_text(view)        # it opens on the first note still to judge
    assert current_verdict(view).value == "not judged"
    button(view, "Previous").click()
    view.run()
    assert current_verdict(view).value == "supports"                    # the verdict given before is still there
    finish(view)
    assert "#### FIXTURE first heading" in all_text(view)
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
    finish(view)
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

    assert [t.value for t in view.text] == [" ".join(workspace.by_id[notes[0]["chunk_id"]]["text"].split())]
    assert "\n" not in view.text[0].value


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
    assert "**5 of 5** · judged so far: 4 of 5" in all_text(view)        # the commentary is the last thing to judge
    assert current_verdict(view).key == "article_commentary_verdict_0"

    judge(view, ["reject"])

    assert record(view)["status"] == "reviewed"
    assert assemble.COMMENTARY_LABEL not in article_file(view)
    assert record(view)["sections"][0]["commentary"]["verdict"] == "reject"
    assert len(view.model.calls) == 3


# --- the editorial pass (ADR 0005) -----------------------------------------------------------


def test_the_editorial_pass_is_off_by_default_and_shows_what_it_kept_and_what_it_rejected(view):
    view.model.script["EDIT:FIXTURE-B"] = payload("FIXTURE the calendar, moreover, lists rootstock [E3].", ["E3"])
    view.model.script["EDIT:FIXTURE-C"] = payload("FIXTURE Harland changed the timetable [E4].", ["E4"])
    def editorial(at):
        assert at.checkbox(key="article_editorial").value is False
        at.checkbox(key="article_editorial").check()

    draft(view, options=editorial)
    text, saved = article_file(view), record(view)

    assert len(view.model.calls) == 6 and view.model.edits == 3         # one more call per section, once
    assert "FIXTURE the calendar, moreover, lists rootstock [3]." in text
    assert "FIXTURE the timetable changed [4]." in text and "Harland" not in text      # rejected: the original stands
    assert [s["editorial"]["accepted"] for s in saved["sections"]] == [True, True, False]
    assert saved["sections"][2]["editorial"]["rejected_because"] == ["new_terms: the rewrite adds “Harland”"]
    shown = all_text(finish(view))
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


# --- steps, navigation and copying (docs/decisions/0007-steps-navigation-copy.md) -------------


def html_blocks(at: AppTest) -> list[str]:
    return [str(element.proto.body) for element in at.get("html")]


def test_the_three_views_sit_in_one_bar_that_the_page_style_keeps_in_view(view):
    style = page_style(view)
    bar = style[style.index(".st-key-topnav {"):style.index("}", style.index(".st-key-topnav {"))]

    assert view.radio(key="view").options == ["Ask", "Library", "Write"]     # short names, so the bar is one row
    assert "position: fixed" in bar and "top: 0" in bar
    assert "light-dark(" in bar and not __import__("re").search(r"background:\s*#", bar)     # dark in a dark theme
    assert "justify-content: flex-end" in style                         # clear of the open sidebar and its button
    header = style[style.index('[data-testid="stHeader"], [data-testid="stHeader"] *'):]
    assert header.startswith('[data-testid="stHeader"], [data-testid="stHeader"] * {pointer-events: none !important;}')
    assert "scroll-padding-top" in style                                # focus is not left under the bar (WCAG 2.4.11)
    assert any('id="page-top"' in block for block in html_blocks(view))
    assert "[Back to top](#page-top)" in [m.value for m in view.markdown]


def test_the_plan_is_made_one_step_at_a_time_and_going_back_loses_nothing(view):
    assert "Step 1 of 5" in all_text(view) and "**Outline (now)**" in all_text(view)
    fill(view)
    button(view, "Next: frame and options").click()
    view.run()
    assert "Step 2 of 5" in all_text(view) and "Outline (done) · **Frame and options (now)**" in all_text(view)
    assert not [t for t in view.text_input if t.key == "article_title"]         # one thing on the screen at a time
    view.text_area(key="article_conclusion_text").set_value("FIXTURE my closing words.")
    view.checkbox(key="article_commentary").check()
    view.run()
    button(view, "Next: check the plan").click()
    view.run()

    plan = all_text(view)
    assert "Step 3 of 5" in plan and "**FIXTURE harbour title**" in plan
    assert "1. **FIXTURE first heading** — FIXTURE-A what does the harbour ledger say?" in plan
    assert "- Introduction: left out for now" in plan and "- Conclusion: yours" in plan and "- Commentary: on" in plan
    assert "Drafting makes 3 model call(s) for the sections and up to 0" in plan

    button(view, "Back to frame and options").click()
    view.run()
    assert view.text_area(key="article_conclusion_text").value == "FIXTURE my closing words."
    assert view.checkbox(key="article_commentary").value is True
    button(view, "Back to the outline").click()
    view.run()
    assert view.text_input(key="article_title").value == "FIXTURE harbour title"
    assert view.text_area(key="article_outline").value == OUTLINE
    assert view.model.calls == [] and not view.out.exists()            # planning costs nothing and saves nothing


def test_an_outline_that_is_not_ready_does_not_leave_the_first_step(view):
    fill(view, title="")
    button(view, "Next: frame and options").click()
    view.run()

    assert "Give the article a title." in all_text(view) and "Step 1 of 5" in all_text(view)


def test_review_shows_one_note_at_a_time_and_saves_each_verdict_as_it_is_given(view):
    draft(view)
    assert "Step 4 of 5" in all_text(view) and button(view, "Previous").disabled

    judge(view, ["partly"])
    assert [pair["verdict"] for pair in record(view)["pairs"]] == ["partly", None, None, None]     # saved at once
    assert "**2 of 4** · judged so far: 1 of 4" in all_text(view)

    button(view, "Save and next").click()                               # moving on without choosing judges nothing
    view.run()
    assert [pair["verdict"] for pair in record(view)["pairs"]] == ["partly", None, None, None]
    assert "**3 of 4** · judged so far: 1 of 4" in all_text(view)


def test_an_answer_and_an_article_each_have_a_button_that_copies_them(view, monkeypatch):
    draft(view)
    finish(view)
    (locked,) = [b for b in html_blocks(view) if "sgrag-copy-button" in b]
    assert 'class="sgrag-copy-button" disabled>Copy for Medium</button>' in locked      # nothing leaves before review
    assert "**Export is locked** until: 4 of 4 sentences are not judged yet." in all_text(view)
    assert next(d for d in view.get("download_button") if d.label == "Download Markdown").disabled
    assert "FIXTURE the ledger" not in locked                             # and nothing is waiting in the page to be copied

    button(view, "Back to the review").click()
    view.run()
    judge(view, ["supports"] * 4)
    finish(view)
    (block,) = [b for b in html_blocks(view) if "sgrag-copy-button" in b]
    exported = pipeline.export(pipeline.open_workspace(), pipeline.load(next(view.out.glob("*")), pipeline.open_workspace()))

    assert 'class="sgrag-copy-button" >Copy for Medium</button>' in block and "Export is locked" not in all_text(view)
    assert 'role="status"' in block and 'aria-live="polite"' in block
    assert json.dumps(exported["markdown"], ensure_ascii=False).replace("</", "<\\/") in block      # the plain form
    assert json.dumps(exported["html"], ensure_ascii=False).replace("</", "<\\/") in block          # and the formatted one
    assert "document.execCommand(\"copy\")" in block and "navigator.clipboard" in block      # plain http, and https
    assert not next(d for d in view.get("download_button") if d.label == "Download Markdown").disabled

    view.radio(key="view").set_value("Ask questions")
    view.run()
    monkeypatch.setattr(ask, "call_model", lambda question, items: (
        payload("FIXTURE an answer </script> with a tag in it [E1].", ["E1"]), "fixturehash"))
    view.chat_input[0].set_value("FIXTURE: what does the ledger say?")
    view.run()
    (answer,) = [b for b in html_blocks(view) if "sgrag-copy-button" in b]

    assert ">Copy the answer</button>" in answer
    assert "FIXTURE: what does the ledger say?" in answer and "with a tag in it ¹." in answer
    assert "Sources:\\n1. " in answer                                   # the sources travel with it
    assert "RETRIEVAL" not in answer and "score" not in answer and "──" not in answer      # the diagnostics do not
    assert answer.count("</script>") == 1                               # text cannot close the script it sits in


def test_starting_another_article_begins_from_a_clean_plan(view):
    def options(at):
        at.text_area(key="article_conclusion_text").set_value("FIXTURE my closing words.")
        at.checkbox(key="article_editorial").check()

    draft(view, options=options)
    button(view, "Start another article").click()
    view.run()
    fill(view, title="FIXTURE a second title")
    button(view, "Next: frame and options").click()
    view.run()

    assert view.text_area(key="article_conclusion_text").value == ""    # nothing carried over from the last article
    assert view.checkbox(key="article_editorial").value is False


# --- ADR 0008: sentence by sentence --------------------------------------------------------------


def test_a_sentence_with_no_note_is_put_to_the_researcher_before_anything_else(view):
    view.model.script["FIXTURE-C"] = payload("FIXTURE the timetable changed [E4]. FIXTURE this shaped the town.", ["E4"])
    draft(view)

    assert "FIXTURE this shaped the town" not in article_file(view)
    assert "**A sentence with no note**, in “FIXTURE third heading”" in all_text(view)
    assert "it is not printed" in all_text(view) and "**1 of 5**" in all_text(view)
    button(view, "Keep it as my own words").click()
    view.run()

    assert "FIXTURE the timetable changed [4]. FIXTURE this shaped the town." in article_file(view)
    assert record(view)["sentences"]["kept_as_own_words"][0]["origin"] == "researcher"
    assert "**1 of 4**" in all_text(view)                               # only the notes are left to judge


def test_review_puts_one_sentence_beside_its_passage_and_judges_the_pair(view):
    draft(view)
    shown = all_text(view)

    assert "**Sentence with note [1]**, in “FIXTURE first heading”" in shown
    assert "Closest sentences in the passage it cites, shared words in bold" in shown
    assert any(e.label == "The whole passage" for e in view.expander) and len(view.text) == 1
    assert "Does the passage support this sentence?" == current_verdict(view).label
    judge(view, ["supports"])
    pair = record(view)["pairs"][0]
    assert (pair["sid"], pair["verdict"], pair["carried_over"], pair["raw"]) == (
        "0.0", "supports", False, "FIXTURE the ledger says one thing [E1].")


def test_a_sentence_is_edited_in_the_view_and_a_bad_edit_is_refused_there(view):
    draft(view)
    key = "0.0_" + record(view)["pairs"][0]["chunk_id"]

    view.text_area(key=f"article_edit_{key}").set_value("FIXTURE the ledger says one thing, on p. 9 [E1].")
    view.run()
    view.button(key=f"article_save_edit_{key}").click()
    view.run()
    assert "This edit was not saved: no page number: pages come from the notes." in all_text(view)
    assert "FIXTURE the ledger says one thing [1]." in article_file(view)

    view.text_area(key=f"article_edit_{key}").set_value("FIXTURE the ledger records one thing [E1].")
    view.run()
    view.button(key=f"article_save_edit_{key}").click()
    view.run()
    saved = record(view)

    assert "FIXTURE the ledger records one thing [1]." in article_file(view)
    assert saved["sentences"]["edits"]["0.0"]["original"] == "FIXTURE the ledger says one thing [E1]."
    assert "The article says (edited by you)" in all_text(view)
    assert saved["pairs"][0]["verdict"] is None and len(view.model.calls) == 3     # no model call to edit


def test_an_outline_can_ask_for_an_argument_and_no_model_is_called(view):
    from article import topics
    view.selectbox(key="article_topic").set_value(view.selectbox(key="article_topic").options[8])
    view.run()
    assert view.selectbox(key="article_outline_kind").options == list(topics.OUTLINE_KINDS)
    view.selectbox(key="article_outline_kind").set_value(topics.ARGUMENT)
    view.run()
    button(view, "Fill the outline from this chapter's sections").click()
    view.run()
    briefs = [line.split(" | ")[1] for line in view.text_area(key="article_outline").value.splitlines()]

    assert [brief.split(" ")[0] for brief in briefs] == ["How", "How,", "What,"]      # define, explain how, consequences
    assert briefs[0].startswith("How does the thesis define ") and "What does the thesis say about" not in "".join(briefs)
    assert view.model.calls == []


def test_terms_used_in_more_than_one_section_are_listed_in_the_review(view):
    view.model.script["FIXTURE-B"] = payload("FIXTURE the amber beacon draws ships in [E3].", ["E3"])
    view.model.script["FIXTURE-C"] = payload("FIXTURE the amber beacon warns ships off [E4].", ["E4"])
    draft(view)
    shown = all_text(view)

    assert any(e.label == "Terms used in more than one section (1)" for e in view.expander)
    assert "**amber beacon** — in 2 sections" in shown
    assert "- *FIXTURE second heading*: FIXTURE the amber beacon draws ships in [3]." in shown
    assert "- *FIXTURE third heading*: FIXTURE the amber beacon warns ships off [4]." in shown
    assert "Nothing here is checked for you." in shown and len(view.model.calls) == 3



def test_a_second_opinion_is_offered_only_after_a_verdict_and_never_changes_it(view, monkeypatch):
    draft(view)
    assert not [b for b in view.button if b.label.startswith("Ask the model for a second opinion")]     # not before a verdict

    judge(view, ["supports"])
    button(view, "Previous").click()
    view.run()
    monkeypatch.setattr(ask, "call_model", lambda question, items, instructions=None: (
        {"evidence_sufficiency": "insufficient", "answer": None, "limitations": [], "ai_interpretation": [],
         "unsupported_by_evidence": ["FIXTURE the passage gives this to another scholar."], "citations_used": []},
        "fixturehash"))
    button(view, "Ask the model for a second opinion (one model call)").click()
    view.run()
    shown, pair = all_text(view), record(view)["pairs"][0]

    assert "**The model's reading, not a verdict: does not.** FIXTURE the passage gives this to another scholar." in shown
    assert "It differs from your verdict (supports). Read the passage again. Your verdict stands until you change it." in shown
    assert (pair["verdict"], pair["second_opinion"]["opinion"]) == ("supports", "does not")
    assert current_verdict(view).value == "supports"
