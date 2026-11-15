"""Article quality — ADR 0005, the seven changes made after the first real draft.

Offline. The model is replaced at `ask.call_model`; retrieval, `ask.validate`,
the checks of form and assembly are the real code. Every passage, brief and
scripted answer is synthetic. The defects reproduced here are the ones the
first draft showed, rebuilt from invented text: none of it is from the thesis.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import ask
from article import assemble, checks, pipeline
from test_article import BRIEFS, REFUSAL, SCRIPT, Scripted, payload, trial  # noqa: F401  (trial is a fixture)

ROOT = Path(ask.__file__).resolve().parent


@pytest.fixture
def workspace(trial):
    return pipeline.open_workspace()


def scripted(monkeypatch, **overrides) -> Scripted:
    model = Scripted({**SCRIPT, **overrides})
    monkeypatch.setattr(ask, "call_model", model)
    return model


# =====================================================================================
# 1. Note placement
# =====================================================================================


@pytest.mark.parametrize("text", [
    "[E5] describes three lamps and their states.",
    "FIXTURE the keeper kept a ledger [E1]. [E4] states that the oil came in winter.",
    "FIXTURE the two differ, and [E4] notes a crucial difference.",
    "FIXTURE [E1] and [E2] argue that the harbour silted up.",
    "According to [E2], the tramway closed.",
    "FIXTURE as [E3] shows, the canal froze.",
    "FIXTURE the survey is set out in [E6].",
    "“[E1] says little,” FIXTURE.",
])
def test_a_note_marker_standing_as_a_word_of_the_sentence_is_found(text):
    assert checks.handle_as_subject(text) != []


@pytest.mark.parametrize("text", [
    "The thesis describes three lamps and their states [E5].",
    "FIXTURE the keeper logged oil [E1], and the calendar lists rootstock [E2].",
    "FIXTURE the keeper wrote “oil came late” [E1]. FIXTURE the tramway closed [E3][E4].",
    "FIXTURE the author states that the harbour silted up [E2], which the survey notes too [E6].",
])
def test_a_marker_at_the_end_of_its_clause_is_left_alone(text):
    assert checks.handle_as_subject(text) == []


def test_a_section_with_a_marker_as_its_subject_is_blocked_with_the_reason_and_not_resent(workspace, monkeypatch):
    model = scripted(monkeypatch, lighthouse=payload("[E1] describes the lamp oil ledger. FIXTURE more [E1].", cites=["E1"]))
    section = pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])
    draft = pipeline.Draft("FIXTURE title", [section])
    article = pipeline.render(workspace, draft)

    assert section.outcome.failures == []                              # the grounding contract was met
    assert article.blocked[0]["reason"].startswith("article check failed: handle_used_as_subject")
    assert "“[E1] describes" in article.blocked[0]["reason"]
    assert "FIXTURE heading" not in article.markdown
    record = pipeline.build_record(workspace, draft, article)
    assert record["sections"][0]["article_check_failures"][0].startswith("handle_used_as_subject")
    assert len(model.calls) == 1


def test_the_article_path_sends_its_rules_of_form_as_a_hashed_prompt_file(workspace, monkeypatch):
    model = scripted(monkeypatch)
    text, digest = checks.load_prompt(checks.SECTION_PROMPT)
    section = pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])
    pipeline.draft_introduction("FIXTURE title", [section])
    draft = pipeline.Draft("FIXTURE title", [section])

    assert model.instructions == [text, text]
    assert "at the END of the clause" in text and "[E5] states" in text
    assert re.fullmatch(r"[0-9a-f]{12}", digest)
    assert pipeline.build_record(workspace, draft, pipeline.render(workspace, draft))["prompts"][checks.SECTION_PROMPT] == digest


class FakeClient:
    """Stands where the provider's client is, so the real `ask.call_model` runs."""

    def __init__(self):
        self.requests = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **request):
        self.requests.append(request)
        block = SimpleNamespace(type="text", text=json.dumps(payload("FIXTURE answer [E1].", cites=["E1"])))
        return SimpleNamespace(stop_reason="end_turn", content=[block])


def test_a_question_is_sent_exactly_as_before_and_only_an_article_adds_instructions(items, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(ask, "_get_client", lambda: client)
    monkeypatch.setattr(ask, "settings", __import__("dataclasses").replace(ask.settings, llm_provider="anthropic"))

    ask.call_model("FIXTURE question?", items[:1])
    ask.call_model("FIXTURE question?", items[:1], instructions="FIXTURE rules of form")
    plain, with_rules = (request["messages"][0]["content"] for request in client.requests)

    assert plain == f"EVIDENCE\n========\n{ask.render_evidence_block(items[:1])}\n\nQUESTION\n========\nFIXTURE question?"
    assert with_rules == plain + f"\n\n{ask.INSTRUCTIONS_HEADING}\nFIXTURE rules of form"
    assert client.requests[0]["system"] == client.requests[1]["system"]            # the system prompt is untouched
    assert client.requests[0]["output_config"] == client.requests[1]["output_config"]


def test_questions_and_the_evaluation_never_pass_instructions(fixture_index, monkeypatch):
    seen = []
    monkeypatch.setattr(ask, "call_model", lambda question, items: seen.append(question) or (payload("FIXTURE [E1].", cites=["E1"]), "h"))
    vectors, chunks, _ = ask.load_index()

    ask.run_query(BRIEFS[0], vectors, chunks)                          # a two-argument stand-in is enough
    ask.run_query(BRIEFS[0], vectors, chunks, retrieve_evidence=False)

    assert len(seen) == 2
    for shell in ("evaluate.py", "main.py"):
        assert "instructions=" not in (ROOT / shell).read_text(encoding="utf-8"), shell
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "instructions=" not in app[app.index("def render_chat"):app.index("def main()")]


# =====================================================================================
# 2. Limitations as reader-facing text
# =====================================================================================

REPORT_LINES = ["The evidence does not explain how the ledger was kept [E1].",
                "The evidence addresses only the winter deliveries."]


def limited(answer, cites, limitations):
    return payload(answer, cites=cites, sufficiency="partial", limitations=limitations)


def test_limits_are_gathered_into_one_closing_list_with_one_line_per_section(workspace, monkeypatch):
    scripted(
        monkeypatch,
        lighthouse=limited("FIXTURE the keeper logged lamp oil [E1].", ["E1"],
                           [*REPORT_LINES, "The thesis does not say who paid for the oil [E1].",
                            "The thesis does not discuss the summer months."]),
        orchard=limited("FIXTURE the calendar lists rootstock [E1].", ["E1"],
                        ["The thesis does not name the varieties grafted."]),
        tramway=limited("FIXTURE the timetable changed [E1].", ["E1"], REPORT_LINES),
    )
    sections = [pipeline.draft_section(workspace, f"FIXTURE heading {n + 1}", brief) for n, brief in enumerate(BRIEFS)]
    draft = pipeline.Draft("FIXTURE title", sections, conclusion=pipeline.written("FIXTURE my closing words."))
    article = pipeline.render(workspace, draft)
    text = article.markdown
    closing = text.split(f"## {assemble.NOT_COVERED_HEADING}\n\n")[1].split("\n\n")[0].splitlines()

    assert closing == ["- The thesis does not say who paid for the oil [1].",
                       "- The thesis does not name the varieties grafted."]
    for section in text.split("## ")[1:4]:
        assert "does not" not in section                               # nothing of it in a section's body
    assert "The evidence" not in text and "summer months" not in text
    assert text.index("FIXTURE my closing words.") < text.index(assemble.NOT_COVERED_HEADING) < text.index("## Sources")
    assert article.limits_held_back == 3 + 0 + 2

    record = pipeline.build_record(workspace, draft, article)
    assert [s["limitation_printed"] for s in record["sections"]] == [closing[0][2:], closing[1][2:], None]
    assert record["sections"][0]["result"]["limitations"][:2] == REPORT_LINES       # all of it stays in the record
    assert record["limitations_kept_in_record_only"] == 5


def test_gaps_are_recorded_and_never_printed_and_no_list_is_made_from_nothing(workspace, monkeypatch):
    answer = payload("FIXTURE the keeper logged lamp oil [E1].", cites=["E1"])
    answer["unsupported_by_evidence"] = ["FIXTURE: who built the lighthouse"]
    scripted(monkeypatch, lighthouse=answer)
    draft = pipeline.Draft("FIXTURE title", [pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])])
    article = pipeline.render(workspace, draft)

    assert assemble.NOT_COVERED_HEADING not in article.markdown and "who built" not in article.markdown
    assert pipeline.build_record(workspace, draft, article)["sections"][0]["result"]["unsupported_by_evidence"] == [
        "FIXTURE: who built the lighthouse"]


def test_a_long_or_report_style_limitation_is_not_a_reader_line():
    long_line = "The thesis does not " + "say " * assemble.LIMIT_MAX_WORDS + "[E1]."
    assert assemble.reader_limit({"limitations": [long_line, REPORT_LINES[0]]}) is None
    assert assemble.reader_limit({"limitations": [REPORT_LINES[0], "the thesis does not date it [E2]. "]}) == "the thesis does not date it [E2]."


# =====================================================================================
# 3. Commentary discipline
# =====================================================================================

# The first draft's wrong commentary, rebuilt from invented text. In the passage one
# party gives and another describes; the commentary turns the describer into the giver.
SWAP_PASSAGE = ("FIXTURE: the Maker gives the keeper three lamps and sets no limit on them. "
                "Harland describes the three lamps and what follows when one is left unlit.")
SWAPPED = "FIXTURE Harland's decision to endow the keeper with unlimited lamps shows a concern for freedom [E1]."
FAITHFUL = "FIXTURE the Maker gives the lamps without limit, which Harland describes as a test [E1]."


def test_an_act_given_to_someone_the_passage_does_not_show_doing_it_is_raised():
    assert checks.agent_flags(SWAPPED, [SWAP_PASSAGE]) == [
        "gives “decision” to Harland; the cited passage does not show Harland doing this"]
    assert checks.agent_flags(FAITHFUL, [SWAP_PASSAGE]) == []
    assert checks.agent_flags("FIXTURE Harland decided to endow the keeper [E1].", [SWAP_PASSAGE]) != []
    assert checks.agent_flags("FIXTURE The decision was made early. This gave the keeper time.", [SWAP_PASSAGE]) == []


def commented(workspace, monkeypatch, comments, **draft_options):
    scripted(monkeypatch, lighthouse=payload("FIXTURE the keeper logged lamp oil [E1].", cites=["E1"],
                                             interpretation=comments))
    section = pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])
    return pipeline.Draft("FIXTURE title", [section], **draft_options)


def test_commentary_is_off_by_default_and_stays_in_the_record(workspace, monkeypatch):
    draft = commented(workspace, monkeypatch, [SWAPPED, "FIXTURE a second reading [E1]."])
    article = pipeline.render(workspace, draft)
    record = pipeline.build_record(workspace, draft, article)

    assert assemble.COMMENTARY_LABEL not in article.markdown and "Harland" not in article.markdown
    assert record["commentary_switched_on"] is False
    assert record["sections"][0]["commentary"] == {
        "printed": False, "items_held_back": 1, "verdict": None, "judged_at": None, "judged_by": None,
        "raised": ["gives “decision” to Harland; the cited passage does not show Harland doing this"]}
    assert record["sections"][0]["result"]["ai_interpretation"] == [SWAPPED, "FIXTURE a second reading [E1]."]


def test_switched_on_a_section_prints_one_commentary_paragraph_at_most(workspace, monkeypatch):
    draft = commented(workspace, monkeypatch, [FAITHFUL, "FIXTURE a second reading [E1].", "FIXTURE a third [E1]."],
                      commentary=True)
    text = pipeline.render(workspace, draft).markdown

    assert text.count(assemble.COMMENTARY_LABEL) == 1
    assert f"{assemble.COMMENTARY_LABEL} FIXTURE the Maker gives the lamps without limit" in text
    assert "second reading" not in text and "a third" not in text


def test_commentary_is_never_accepted_without_the_researchers_verdict(workspace, monkeypatch):
    draft = commented(workspace, monkeypatch, [SWAPPED], commentary=True)
    article = pipeline.render(workspace, draft)
    for note in article.notes:
        pipeline.set_verdict(draft, note["chunk_id"], "supports")      # the note is fine; the commentary is not judged

    assert pipeline.status(draft, pipeline.render(workspace, draft)) == "draft"
    assert assemble.DRAFT_LINE in pipeline.render(workspace, draft).markdown
    with pytest.raises(pipeline.ArticleError):
        pipeline.set_commentary_verdict(draft, 0, "fine")

    pipeline.set_commentary_verdict(draft, 0, "reject")
    after = pipeline.render(workspace, draft)
    assert "Harland" not in after.markdown and pipeline.status(draft, after) == "reviewed"
    record = pipeline.build_record(workspace, draft, after)["sections"][0]["commentary"]
    assert (record["printed"], record["verdict"], record["judged_by"]) == (False, "reject", "researcher")

    pipeline.set_commentary_verdict(draft, 0, "accept")
    accepted = pipeline.render(workspace, draft)
    assert SWAPPED.replace("[E1]", "[1]") in accepted.markdown and pipeline.status(draft, accepted) == "reviewed"


def test_a_commentary_verdict_survives_saving_and_reopening(workspace, monkeypatch, tmp_path):
    draft = commented(workspace, monkeypatch, [FAITHFUL], commentary=True)
    pipeline.set_commentary_verdict(draft, 0, "reject")
    reopened = pipeline.load(pipeline.save(workspace, draft, tmp_path / "out"), workspace)

    assert reopened.commentary is True and reopened.commentary_verdicts[0]["verdict"] == "reject"
    assert pipeline.render(workspace, reopened).markdown == pipeline.render(workspace, draft).markdown


# =====================================================================================
# 4. Quotation limit
# =====================================================================================

WORDS = "FIXTURE lamp oil ledger harbour canal tramway orchard viaduct beacon quarry".split()


def words(n: int) -> str:
    return " ".join(WORDS[i % len(WORDS)] for i in range(n))


def test_a_direct_quotation_may_run_to_twenty_five_words_and_no_further():
    at_limit = f"{words(200)} “{words(25)}” [E1]."
    over = f"{words(200)} “{words(26)}” [E1]."

    assert checks.quotation_failures(at_limit) == []
    assert checks.quotation_failures(over) == [
        "quotation_too_long: 1 direct quotation(s) over 25 words (the longest is 26); paraphrase and keep the note"]
    assert checks.quotation_failures(over.replace("“", '"').replace("”", '"')) != []      # straight marks too


def test_quotations_together_may_be_a_fifth_of_a_section_and_no_more():
    def section(quoted_each: int) -> str:                              # 100 words, four quotations
        return " ".join(f"{words(25 - quoted_each)} “{words(quoted_each)}” [E1]." for _ in range(4))

    assert checks.quotation_failures(section(5)) == []                 # 20 of 100
    assert checks.quotation_failures(section(6)) == [
        "too_much_quotation: 24% of the section is direct quotation (the limit is 20%); paraphrase and keep the note"]
    assert checks.quotation_failures(f"{words(40)} ‘{words(30)}’ [E1].") == []     # single marks: a term, not speech


def test_a_section_built_from_long_quotations_is_blocked_and_recorded(workspace, monkeypatch):
    quoting = " ".join(f"FIXTURE the keeper wrote “{words(27)}” [E1]." for _ in range(3))
    model = scripted(monkeypatch, lighthouse=payload(quoting, cites=["E1"]))
    section = pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])
    draft = pipeline.Draft("FIXTURE title", [section])
    article = pipeline.render(workspace, draft)
    failures = pipeline.build_record(workspace, draft, article)["sections"][0]["article_check_failures"]

    assert section.outcome.failures == []
    assert [failure.split(":")[0] for failure in failures] == ["quotation_too_long", "too_much_quotation"]
    assert article.blocked[0]["reason"].startswith("article check failed: quotation_too_long: 3 direct quotation(s)")
    assert "FIXTURE heading" not in article.markdown and len(model.calls) == 1


# =====================================================================================
# 5. The editorial pass
# =====================================================================================

ORIGINAL = "FIXTURE the keeper logged lamp oil [E1]. FIXTURE the oil came in winter [E2]."
REWRITE = "FIXTURE the keeper logged lamp oil [E1]. However, the oil came only in winter [E2]."
TWO_PARAGRAPHS = "FIXTURE the keeper logged lamp oil [E1].\nFIXTURE the oil came in winter [E2]."


class Editor(Scripted):
    """Answers a brief from the script, and an editorial call with the rewrite it was given."""

    def __init__(self, original, rewrite):
        super().__init__({**SCRIPT, "lighthouse": payload(original, cites=["E1", "E2"])})
        self.rewrite, self.edits = rewrite, []

    def __call__(self, question, items, instructions=None):
        if instructions and instructions.startswith("EDITORIAL TASK"):
            self.edits.append((instructions, [item.chunk["chunk_id"] for item in items], [item.handle for item in items]))
            if isinstance(self.rewrite, BaseException):
                raise self.rewrite
            return self.rewrite, "fixturehash"
        return super().__call__(question, items, instructions)


def edited(workspace, monkeypatch, rewrite, original=ORIGINAL):
    if isinstance(rewrite, str):
        rewrite = payload(rewrite, cites=sorted(set(re.findall(r"E\d+", rewrite))))
    model = Editor(original, rewrite)
    monkeypatch.setattr(ask, "call_model", model)
    section = pipeline.edit_section(pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0]))
    return section, model


def test_a_rewrite_that_preserves_replaces_the_original_and_is_recorded(workspace, monkeypatch):
    embedded, embed = [], ask.embed_texts
    monkeypatch.setattr(ask, "embed_texts", lambda texts, **kw: embedded.append(texts) or embed(texts, **kw))
    section, model = edited(workspace, monkeypatch, REWRITE)
    assert len(embedded) == 1                                           # the brief, once; the editor retrieves nothing
    draft = pipeline.Draft("FIXTURE title", [section])
    article = pipeline.render(workspace, draft)
    record = pipeline.build_record(workspace, draft, article)
    prompt, digest = checks.load_prompt(checks.EDITORIAL_PROMPT)
    instructions, chunk_ids, handles = model.edits[0]

    assert "However, the oil came only in winter [2]." in article.markdown and "FIXTURE the oil came in winter" not in article.markdown
    assert instructions == f"{prompt}\nDRAFT\n=====\n{ORIGINAL}"
    assert chunk_ids == [item.chunk["chunk_id"] for item in section.outcome.items]        # the same passages: nothing retrieved
    assert handles == [item.handle for item in section.outcome.items]                      # under the same handles
    assert len(model.calls) == 1 and len(model.edits) == 1
    editorial = record["sections"][0]["editorial"]
    assert editorial["accepted"] is True and editorial["rejected_because"] == []
    assert editorial["prompt_sha256_12"] == digest == record["prompts"][checks.EDITORIAL_PROMPT]
    assert editorial["result"]["answer"] == REWRITE and 0.8 < editorial["similarity_to_original"] < 1
    assert record["sections"][0]["result"]["answer"] == ORIGINAL                           # the original is kept too
    assert editorial["voice_before"]["connectives_per_1000_words"] == 0.0
    assert editorial["voice_after"]["connectives_per_1000_words"] > 0


@pytest.mark.parametrize(("rewrite", "reason"), [
    ("FIXTURE the keeper logged lamp oil, which came in winter [E1].", "handles_changed: paragraph 1 carried [E1] [E2], the rewrite carries [E1]"),
    ("FIXTURE the keeper logged lamp oil [E1]. FIXTURE it came in winter [E2] [E3].", "handles_changed: paragraph 1 carried [E1] [E2], the rewrite carries [E1] [E2] [E3]"),
    ("FIXTURE the keeper Harland logged lamp oil [E1]. FIXTURE the oil came in winter [E2].", "new_terms: the rewrite adds “Harland”"),
    ("FIXTURE the keeper logged lamp oil in 1923 [E1]. FIXTURE the oil came in winter [E2].", "new_terms: the rewrite adds “1923”"),
    ("FIXTURE the keeper logged lamp oil, his amāna [E1]. FIXTURE the oil came in winter [E2].", "new_terms: the rewrite adds “amāna”"),
    ("FIXTURE the keeper logged lamp oil [E1] — and the oil came in winter [E2].", "em_dash: the rewrite uses an em dash"),
    ("[E1] states that the keeper logged lamp oil. FIXTURE the oil came in winter [E2].", "handle_used_as_subject"),
    ("FIXTURE the keeper logged lamp oil [E1]. FIXTURE the oil came in winter [E2] [E9].", "validation failed: citation_hallucination"),
    (RuntimeError("FIXTURE provider outage"), "the pipeline failed: RuntimeError: FIXTURE provider outage"),
    (REFUSAL, "no_rewrite: the model returned no rewritten text"),
])
def test_a_rewrite_that_does_not_preserve_is_rejected_and_the_original_stays(workspace, monkeypatch, rewrite, reason):
    section, model = edited(workspace, monkeypatch, rewrite)
    draft = pipeline.Draft("FIXTURE title", [section])
    article = pipeline.render(workspace, draft)
    editorial = pipeline.build_record(workspace, draft, article)["sections"][0]["editorial"]

    assert editorial["accepted"] is False
    assert any(failure.startswith(reason) for failure in editorial["rejected_because"]), editorial["rejected_because"]
    assert "FIXTURE the keeper logged lamp oil [1]. FIXTURE the oil came in winter [2]." in article.markdown
    assert article.blocked == []                                        # the section itself is still good
    pipeline.edit_section(section)
    assert len(model.edits) == 1                                        # rejected, recorded, not sent again


def test_a_marker_may_not_move_from_one_paragraph_to_another(workspace, monkeypatch):
    moved = "FIXTURE the keeper logged lamp oil [E1] [E2].\nFIXTURE the oil came in winter."
    merged = "FIXTURE the keeper logged lamp oil [E1], and it came in winter [E2]."
    kept = "FIXTURE the keeper logged lamp oil [E1].\nMoreover, the oil came in winter [E2]."

    assert edited(workspace, monkeypatch, moved, TWO_PARAGRAPHS)[0].editorial["rejected_because"][0].startswith("handles_changed: paragraph 1")
    assert edited(workspace, monkeypatch, merged, TWO_PARAGRAPHS)[0].editorial["rejected_because"] == [
        "paragraphs_changed: the draft has 2 paragraph(s), the rewrite 1"]
    assert edited(workspace, monkeypatch, kept, TWO_PARAGRAPHS)[0].editorial["accepted"] is True


def test_a_joining_word_is_not_a_new_name_but_a_name_in_its_place_is():
    assert checks.new_terms(ORIGINAL, "However, FIXTURE the keeper logged oil [E1]. Together, FIXTURE these came in winter [E2].") == []
    assert checks.new_terms(ORIGINAL, "Harland logged lamp oil [E1].") == ["Harland"]
    assert checks.new_terms(ORIGINAL, "FIXTURE the Keeper logged 2 lamps of oil [E1].") == ["2"]      # "keeper" is known


def test_no_editorial_call_is_made_for_a_section_that_is_blocked(workspace, monkeypatch):
    section, model = edited(workspace, monkeypatch, REWRITE, original="[E1] states that oil was logged [E2].")

    assert model.edits == [] and section.editorial is None and section.prose is None


def test_an_accepted_rewrite_survives_saving_and_reopening_without_a_call(workspace, monkeypatch, tmp_path):
    section, model = edited(workspace, monkeypatch, REWRITE)
    draft = pipeline.Draft("FIXTURE title", [section])
    folder = pipeline.save(workspace, draft, tmp_path / "out")
    monkeypatch.setattr(ask, "call_model", lambda *a, **k: pytest.fail("reopening called the model"))

    reopened = pipeline.load(folder, workspace)

    assert reopened.sections[0].prose == REWRITE
    assert pipeline.render(workspace, reopened).markdown == pipeline.render(workspace, draft).markdown


def test_the_known_targets_of_the_voice_profile_are_checked_and_the_rest_are_not_invented():
    from article import voice
    flat = voice.measure("FIXTURE one thing. FIXTURE another thing — a third.")
    joined = voice.measure("FIXTURE one thing. However, another thing. Therefore, a third follows from it.")

    assert voice.profile_checks(flat) == [
        {"check": "connectives_per_1000_words", "target": "at least 12.0", "value": 0.0, "met": False},
        {"check": "em_dashes", "target": "at most 0", "value": 1, "met": False}]
    assert [check["met"] for check in voice.profile_checks(joined)] == [True, True]
    assert len(voice.PROFILE) == 2


# =====================================================================================
# 6. Save as you go, and resume
# =====================================================================================

OUTLINE = [(f"FIXTURE heading {n + 1}", brief) for n, brief in enumerate(BRIEFS)]


class Restart(BaseException):
    """The container going away in the middle of a call. Not an error the pipeline records."""


class Dying(Scripted):
    """Answers until the call numbered `at`, then the process is gone."""

    def __init__(self, at, script=None):
        super().__init__({**SCRIPT, **(script or {})})
        self.at, self.kinds = at, []

    def __call__(self, question, items, instructions=None):
        self.kinds.append("edit" if instructions and instructions.startswith("EDITORIAL TASK") else question[:28])
        if len(self.kinds) == self.at:
            raise Restart()
        return super().__call__(question, items, instructions)


def on_disk(folder) -> dict:
    return json.loads((folder / "record.json").read_text(encoding="utf-8"))


def interrupted(workspace, monkeypatch, tmp_path, at, **plan):
    draft = pipeline.new_draft("FIXTURE harbour title", OUTLINE, **plan)
    monkeypatch.setattr(ask, "call_model", Dying(at))
    with pytest.raises(Restart):
        pipeline.run(workspace, draft, tmp_path / "out")
    (folder,) = (tmp_path / "out").iterdir()
    return folder


def test_the_plan_is_on_disk_before_the_first_call_and_each_section_as_it_finishes(workspace, monkeypatch, tmp_path):
    folder = interrupted(workspace, monkeypatch, tmp_path, at=2, conclusion="researcher",
                         conclusion_text="FIXTURE my closing words.")
    record = on_disk(folder)

    assert record["status"] == "drafting" and record["drafting"]["complete"] is False
    assert [bool(s.get("pending")) for s in record["sections"]] == [False, True, True]
    assert record["sections"][0]["result"]["answer"] == SCRIPT["lighthouse"]["answer"]      # the paid section is kept
    assert [s["brief"] for s in record["sections"]] == BRIEFS                               # the plan, in full
    assert record["frame"]["conclusion"] == {"origin": "researcher", "text": "FIXTURE my closing words."}
    assert record["drafting"]["model_calls_remaining"] == 2
    assert "FIXTURE the keeper logged lamp oil [1]." in (folder / "article.md").read_text(encoding="utf-8")
    assert not list(folder.glob("*.partial"))


def test_a_restart_before_the_first_answer_still_leaves_the_plan(workspace, monkeypatch, tmp_path):
    record = on_disk(interrupted(workspace, monkeypatch, tmp_path, at=1))

    assert [bool(s.get("pending")) for s in record["sections"]] == [True, True, True]
    assert record["drafting"]["model_calls_remaining"] == 3 and record["title"]["text"] == "FIXTURE harbour title"


def test_resuming_sends_only_what_is_missing(workspace, monkeypatch, tmp_path):
    folder = interrupted(workspace, monkeypatch, tmp_path, at=3, introduction="generated", conclusion="generated")
    model = Scripted(SCRIPT)
    monkeypatch.setattr(ask, "call_model", model)

    draft = pipeline.load(folder, workspace)
    assert pipeline.planned_calls(draft) == {"sections": 1, "editorial": 0, "introduction": 1, "transitions": 0,
                                             "conclusion": 1, "model_calls": 3, "embedding_calls": 1}
    pipeline.run(workspace, draft, tmp_path / "out")
    asked = [question for question, _, _ in model.calls]

    assert [q for q in asked if "FIXTURE:" in q] == [BRIEFS[2]]         # sections 1 and 2 are not sent again
    assert len(asked) == 3 and sum("introduce" in q for q in asked) == 1 and sum("establish" in q for q in asked) == 1
    record = on_disk(folder)
    assert record["status"] == "draft" and record["drafting"] == {
        "complete": True, "frame_steps_done": ["conclusion", "introduction"], "model_calls_remaining": 0}
    assert len(list((tmp_path / "out").iterdir())) == 1                 # the same article, not a second one
    assert record["support"]["notes"] == 3

    pipeline.run(workspace, pipeline.load(folder, workspace), tmp_path / "out")
    assert len(model.calls) == 3                                        # a finished article asks for nothing


def test_a_restart_in_the_frame_or_the_editorial_pass_loses_only_the_step_in_flight(workspace, monkeypatch, tmp_path):
    # calls: 3 sections, 3 rewrites, introduction, 2 transitions, conclusion. The 8th is the first transition.
    folder = interrupted(workspace, monkeypatch, tmp_path, at=8, editorial=True, introduction="generated",
                         transitions="generated", conclusion="generated")
    record = on_disk(folder)
    assert [s["editorial"]["accepted"] for s in record["sections"]] == [True, True, True]
    assert record["drafting"]["frame_steps_done"] == ["introduction"] and record["drafting"]["model_calls_remaining"] == 3

    model = Dying(at=99)
    monkeypatch.setattr(ask, "call_model", model)
    pipeline.run(workspace, pipeline.load(folder, workspace), tmp_path / "out")

    assert "edit" not in model.kinds and len(model.kinds) == 3          # two transitions and the conclusion
    assert not any(kind.startswith("FIXTURE:") for kind in model.kinds)
    assert on_disk(folder)["drafting"]["complete"] is True


def test_a_section_that_failed_is_a_recorded_outcome_and_is_not_sent_again_on_resume(workspace, monkeypatch, tmp_path):
    draft = pipeline.new_draft("FIXTURE harbour title", OUTLINE)
    monkeypatch.setattr(ask, "call_model", Dying(at=3, script={"orchard": RuntimeError("FIXTURE provider outage")}))
    with pytest.raises(Restart):
        pipeline.run(workspace, draft, tmp_path / "out")
    (folder,) = (tmp_path / "out").iterdir()
    assert on_disk(folder)["sections"][1]["error"] == "RuntimeError: FIXTURE provider outage"

    model = Scripted(SCRIPT)
    monkeypatch.setattr(ask, "call_model", model)
    pipeline.run(workspace, pipeline.load(folder, workspace), tmp_path / "out")

    assert [question for question, _, _ in model.calls] == [BRIEFS[2]]
    assert on_disk(folder)["sections"][1]["blocked"] == "the pipeline failed: RuntimeError: FIXTURE provider outage"


def test_an_article_saved_before_plans_existed_still_opens_as_finished(workspace, monkeypatch, tmp_path):
    scripted(monkeypatch)
    draft = pipeline.Draft("FIXTURE title", [pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])])
    folder = pipeline.save(workspace, draft, tmp_path / "out")
    record = on_disk(folder)
    record["schema_version"] = 2
    for key in ("plan", "drafting", "commentary_switched_on", "prompts"):
        record.pop(key)
    (folder / "record.json").write_text(json.dumps(record), encoding="utf-8")

    reopened = pipeline.load(folder, workspace)

    assert reopened.complete is True and pipeline.planned_calls(reopened)["model_calls"] == 0
    assert pipeline.render(workspace, reopened).markdown == pipeline.render(workspace, draft).markdown


def test_a_restart_during_the_editorial_pass_resumes_the_rewrites_still_owed(workspace, monkeypatch, tmp_path):
    folder = interrupted(workspace, monkeypatch, tmp_path, at=5, editorial=True)      # dies in the second rewrite
    assert [bool(s["editorial"]) for s in on_disk(folder)["sections"]] == [True, False, False]

    model = Dying(at=99)
    monkeypatch.setattr(ask, "call_model", model)
    draft = pipeline.load(folder, workspace)
    assert pipeline.planned_calls(draft)["editorial"] == 2
    pipeline.run(workspace, draft, tmp_path / "out")

    assert model.kinds == ["edit", "edit"]                              # the two rewrites owed, and no section
    assert [bool(s["editorial"]) for s in on_disk(folder)["sections"]] == [True, True, True]


# =====================================================================================
# Combined handles (ADR 0006): one handle per bracket, and no raw handle in print
# =====================================================================================

COMBINED = ["[E1, E2]", "[E1,E2]", "[E1, 2]", "[E1; E2]", "[E1-E3]"]


@pytest.mark.parametrize("bracket", COMBINED)
def test_an_article_section_with_a_combined_handle_is_blocked(workspace, monkeypatch, bracket):
    model = scripted(monkeypatch, lighthouse=payload(
        f"FIXTURE the keeper logged lamp oil [E1]. FIXTURE virtue arises from balance {bracket}.", cites=["E1", "E2", "E3"]))
    section = pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])
    draft = pipeline.Draft("FIXTURE title", [section])
    article = pipeline.render(workspace, draft)

    assert article.blocked[0]["reason"].startswith("validation failed: malformed_handle:")
    assert bracket in article.blocked[0]["reason"]
    assert "[E" not in article.markdown and "FIXTURE heading" not in article.markdown
    assert pipeline.build_record(workspace, draft, article)["sections"][0]["validation_failures"] != []
    assert len(model.calls) == 1


@pytest.mark.parametrize("bracket", COMBINED)
def test_an_editorial_rewrite_with_a_combined_handle_is_rejected(workspace, monkeypatch, bracket):
    rewrite = payload(f"FIXTURE the keeper logged lamp oil, and it came in winter {bracket}.", cites=["E1", "E2"])
    section, _ = edited(workspace, monkeypatch, rewrite)
    article = pipeline.render(workspace, pipeline.Draft("FIXTURE title", [section]))

    assert section.editorial["accepted"] is False and section.prose is None
    assert section.editorial["rejected_because"][0].startswith("validation failed: malformed_handle:")
    assert "FIXTURE the keeper logged lamp oil [1]. FIXTURE the oil came in winter [2]." in article.markdown
    assert "[E" not in article.markdown


def test_a_generated_frame_element_with_a_combined_handle_is_blocked(workspace, monkeypatch):
    scripted(monkeypatch, introduce=payload("FIXTURE an opening that joins two [E1, E2].", cites=["E1", "E2"]))
    section = pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])
    draft = pipeline.Draft("FIXTURE title", [section], introduction=pipeline.draft_introduction("FIXTURE title", [section]))
    article = pipeline.render(workspace, draft)

    assert article.blocked[0]["what"] == "introduction" and "malformed_handle" in article.blocked[0]["reason"]
    assert "[E" not in article.markdown


def test_a_draft_saved_before_the_fix_is_blocked_when_it_is_reopened(workspace, monkeypatch, tmp_path):
    """The two drafts on the Pi have `validation_failures: []` in their records and a
    combined handle in their text. Reopened, they must not print it."""
    scripted(monkeypatch)
    draft = pipeline.Draft("FIXTURE title", [pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])])
    folder = pipeline.save(workspace, draft, tmp_path / "out")
    record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    record["sections"][0]["result"]["answer"] = "FIXTURE virtue arises from balance [E1, E2]."
    record["sections"][0]["result"]["citations_used"] = ["E1", "E2"]
    assert record["sections"][0]["validation_failures"] == []          # as recorded at the time
    (folder / "record.json").write_text(json.dumps(record), encoding="utf-8")

    article = pipeline.render(workspace, pipeline.load(folder, workspace))

    assert "[E" not in article.markdown and "FIXTURE heading" not in article.markdown
    assert article.blocked[0]["reason"].startswith("validation failed: malformed_handle:")


def test_the_assembled_article_never_holds_a_raw_handle_whatever_was_let_through(workspace, monkeypatch):
    """The final guard, with every earlier check switched off."""
    scripted(monkeypatch, lighthouse=payload("FIXTURE oil [E1]. FIXTURE balance [E1, E2]. FIXTURE more [E9].", cites=["E1"]))
    section = pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])
    monkeypatch.setattr(assemble, "block_reason", lambda outcome, error=None: None)
    monkeypatch.setattr(ask, "MARKER_RE", re.compile(r"\[E(1)\]"))     # and a renumberer that leaves [E9] behind
    article = pipeline.render(workspace, pipeline.Draft("FIXTURE title", [section]))
    text = article.markdown

    assert "FIXTURE oil [1]." in text and "[E" not in text
    # Since ADR 0008 a sentence with no handle that resolves is not printed at all.
    assert [held["text"] for held in article.held_back] == ["FIXTURE balance [E1, E2].", "FIXTURE more [E9]."]
    assert ask.scrub_handles("FIXTURE [E1, E2] and [E9].").count(ask.UNRESOLVED_NOTE) == 2


def test_the_prompts_state_the_handle_format_and_their_new_versions_are_what_is_recorded(workspace, monkeypatch):
    rule = "never `[E1, E2]`"
    system = ask.settings.prompt_path.read_text(encoding="utf-8")
    old = (ask.settings.prompt_path.parent / "system_grounded_v2.md").read_text(encoding="utf-8")

    assert ask.settings.prompt_path.name == "system_grounded_v3.md"
    assert "One handle per bracket" in system and "`[E1, E2]`" in system and "`[E1, E2]`" not in old
    assert system.replace(system[system.index("7. **One handle per bracket.**"):system.index("# Reference apparatus")], "\n") == old
    assert (checks.SECTION_PROMPT, checks.EDITORIAL_PROMPT) == ("article_section_v2.md", "article_editorial_v2.md")
    for name in (checks.SECTION_PROMPT, checks.EDITORIAL_PROMPT):
        text, digest = checks.load_prompt(name)
        assert rule in text
        assert digest != checks.load_prompt(name.replace("_v2", "_v1"))[1]          # the record shows the change

    section, _ = edited(workspace, monkeypatch, REWRITE)
    draft = pipeline.Draft("FIXTURE title", [section])
    prompts = pipeline.build_record(workspace, draft, pipeline.render(workspace, draft))["prompts"]
    assert set(prompts) == {"article_section_v2.md", "article_editorial_v2.md"}


def test_em_dashes_in_a_section_are_reported_and_printed_exactly_as_written(workspace, monkeypatch):
    dashed = "FIXTURE the three lamps—red, green and white—stand in a row [E1]. FIXTURE one is lit — the red [E1]."
    scripted(monkeypatch, lighthouse=payload(dashed, cites=["E1"]))
    draft = pipeline.Draft("FIXTURE title", [pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])])
    article = pipeline.render(workspace, draft)

    assert dashed.replace("[E1]", "[1]") in article.markdown           # not a character of it is changed
    assert article.blocked == []                                        # a matter of style: reported, not blocked
    assert pipeline.em_dashes(draft) == {"FIXTURE heading": 3}
    assert pipeline.build_record(workspace, draft, article)["em_dashes_in_print"] == {"FIXTURE heading": 3}


def test_a_section_without_em_dashes_reports_none(workspace, monkeypatch):
    scripted(monkeypatch)
    draft = pipeline.Draft("FIXTURE title", [pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])])

    assert pipeline.em_dashes(draft) == {}


def test_a_rewrite_accepted_before_the_fix_gives_way_to_the_original_when_reopened(workspace, monkeypatch, tmp_path):
    section, _ = edited(workspace, monkeypatch, REWRITE)
    folder = pipeline.save(workspace, pipeline.Draft("FIXTURE title", [section]), tmp_path / "out")
    record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    record["sections"][0]["editorial"]["result"]["answer"] = "FIXTURE oil was logged, and it came in winter [E1, E2]."
    (folder / "record.json").write_text(json.dumps(record), encoding="utf-8")

    text = pipeline.render(workspace, pipeline.load(folder, workspace)).markdown

    assert "FIXTURE the keeper logged lamp oil [1]. FIXTURE the oil came in winter [2]." in text      # the validated original
    assert "[E" not in text and ask.UNRESOLVED_NOTE not in text


# =====================================================================================
# ADR 0008, item 1: every sourced sentence carries a note
# =====================================================================================

UNNOTED = ("FIXTURE the keeper logged lamp oil [E1]. FIXTURE the oil came in winter [E2]. "
           "FIXTURE this is why the harbour prospered.")


def one_section(workspace, monkeypatch, answer, **options):
    scripted(monkeypatch, lighthouse=payload(answer, cites=sorted(set(re.findall(r"E\d+", answer))), **options))
    return pipeline.Draft("FIXTURE title", [pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])])


def test_a_sentence_with_no_note_is_held_back_and_not_printed_as_sourced_prose(workspace, monkeypatch):
    """The sixth error of the first published draft: the last sentence of a section
    carried no handle, passed validation (the section cited something), and was printed."""
    draft = one_section(workspace, monkeypatch, UNNOTED)
    article = pipeline.render(workspace, draft)

    assert draft.sections[0].outcome.failures == [] and article.blocked == []       # the section itself is sound
    assert "this is why the harbour prospered" not in article.markdown
    assert "FIXTURE the keeper logged lamp oil [1]. FIXTURE the oil came in winter [2]." in article.markdown
    assert article.held_back == [{"sid": "0.2", "section": 0, "heading": "FIXTURE heading",
                                  "text": "FIXTURE this is why the harbour prospered."}]
    assert pipeline.status(draft, article) == "draft"


def test_a_held_back_sentence_keeps_the_article_in_draft_until_it_is_deleted_or_kept(workspace, monkeypatch):
    draft = one_section(workspace, monkeypatch, UNNOTED)
    for note in pipeline.render(workspace, draft).notes:
        pipeline.set_verdict(draft, note["chunk_id"], "supports")
    assert pipeline.status(draft, pipeline.render(workspace, draft)) == "draft"     # judged, but one sentence waits

    pipeline.delete_sentence(draft, "0.2")
    deleted = pipeline.render(workspace, draft)
    assert deleted.held_back == [] and "prospered" not in deleted.markdown
    assert pipeline.status(draft, deleted) == "reviewed"
    edit = pipeline.build_record(workspace, draft, deleted)["sentences"]["edits"]["0.2"]
    assert (edit["text"], edit["original"], edit["edited_by"]) == (None, "FIXTURE this is why the harbour prospered.", "researcher")


def test_a_sentence_kept_as_the_researchers_own_words_is_printed_without_a_note_and_recorded_as_theirs(workspace, monkeypatch):
    draft = one_section(workspace, monkeypatch, UNNOTED)
    with pytest.raises(pipeline.ArticleError):
        pipeline.keep_as_own_words(draft, "0.0")                        # a sourced sentence is not the researcher's
    pipeline.keep_as_own_words(draft, "0.2")
    article = pipeline.render(workspace, draft)
    kept = pipeline.build_record(workspace, draft, article)["sentences"]["kept_as_own_words"]

    assert "FIXTURE the oil came in winter [2]. FIXTURE this is why the harbour prospered." in article.markdown
    assert article.held_back == [] and len(article.notes) == 2          # it adds no note
    assert [(k["sid"], k["origin"], k["text"]) for k in kept] == [("0.2", "researcher", "FIXTURE this is why the harbour prospered.")]
    assert kept[0]["kept_at"].startswith("20")


def test_what_was_decided_about_a_sentence_survives_saving_and_reopening(workspace, monkeypatch, tmp_path):
    draft = one_section(workspace, monkeypatch, UNNOTED + " FIXTURE and so it goes.")
    pipeline.keep_as_own_words(draft, "0.2")
    pipeline.delete_sentence(draft, "0.3")
    reopened = pipeline.load(pipeline.save(workspace, draft, tmp_path / "out"), workspace)

    assert reopened.own_words.keys() == {"0.2"} and reopened.sentence_edits["0.3"]["text"] is None
    assert pipeline.render(workspace, reopened).markdown == pipeline.render(workspace, draft).markdown


@pytest.mark.parametrize(("text", "expected"), [
    ("FIXTURE one thing [E1]. FIXTURE another [E2].", 2),
    ("FIXTURE the scholar (d. 1111) wrote much, e.g. on lamps [E1]. FIXTURE another [E2].", 2),
    ("FIXTURE as A. Harland wrote, oil is dear [E1]. al-FIXTURE agreed [E2].", 2),
    ("FIXTURE one thing. [E1] FIXTURE another [E2].", 2),
    ("FIXTURE is it so? FIXTURE it is [E1]!", 2),
])
def test_sentences_are_split_at_their_ends_and_not_at_abbreviations(text, expected):
    from article import sentences
    assert len(sentences.split(text)) == expected


# =====================================================================================
# ADR 0008, item 2: one verdict per sentence and note
# =====================================================================================

# One note on three sentences, as in the published draft, where one note covered six
# sentences and three of them were wrong.
ONE_NOTE_THREE_SENTENCES = ("FIXTURE the keeper logged lamp oil [E1]. FIXTURE the oil came by sea [E1]. "
                            "FIXTURE the ledger was kept in winter [E1] [E2].")


def test_a_note_on_several_sentences_is_judged_once_for_each_sentence(workspace, monkeypatch):
    draft = one_section(workspace, monkeypatch, ONE_NOTE_THREE_SENTENCES)
    article = pipeline.render(workspace, draft)

    assert len(article.notes) == 2
    assert [(pair["sid"], pair["n"]) for pair in article.pairs] == [("0.0", 1), ("0.1", 1), ("0.2", 1), ("0.2", 2)]
    assert article.pairs[1]["sentence"] == "FIXTURE the oil came by sea [1]." and article.pairs[1]["raw"].endswith("[E1].")

    pipeline.set_pair_verdict(draft, article.pairs[0], "supports")
    pipeline.set_pair_verdict(draft, article.pairs[1], "does not", "FIXTURE reason: the passage says by road")
    assert pipeline.status(draft, article) == "draft"                   # two pairs not judged, one judged against
    pipeline.set_pair_verdict(draft, article.pairs[2], "partly")
    pipeline.set_pair_verdict(draft, article.pairs[3], "supports")
    assert pipeline.status(draft, article) == "draft"                   # every pair judged; one "does not" remains
    rows = pipeline.build_record(workspace, draft, article)["pairs"]
    assert [(row["sid"], row["verdict"], row["carried_over"], row["judged_by"]) for row in rows] == [
        ("0.0", "supports", False, "researcher"), ("0.1", "does not", False, "researcher"),
        ("0.2", "partly", False, "researcher"), ("0.2", "supports", False, "researcher")]

    pipeline.delete_sentence(draft, "0.1")
    after = pipeline.render(workspace, draft)
    record = pipeline.build_record(workspace, draft, after)
    assert pipeline.status(draft, after) == "reviewed" and "came by sea" not in after.markdown
    assert record["support"] == {"supports": 2, "partly": 1, "does not": 1, "not judged": 0, "notes": 2, "pairs": 4}
    gone = record["pairs"][-1]
    assert (gone["in_article"], gone["sentence_deleted"], gone["verdict"]) == (False, True, "does not")
    with pytest.raises(pipeline.ArticleError):
        pipeline.set_pair_verdict(draft, after.pairs[0], "probably")


def test_a_verdict_given_per_note_opens_as_the_verdict_of_each_of_its_sentences_marked_carried_over(workspace, monkeypatch, tmp_path):
    draft = one_section(workspace, monkeypatch, ONE_NOTE_THREE_SENTENCES)
    first = pipeline.render(workspace, draft)
    pipeline.set_verdict(draft, first.notes[0]["chunk_id"], "supports", "FIXTURE given to the whole note")
    folder = pipeline.save(workspace, draft, tmp_path / "out")
    record = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    record["schema_version"] = 3                                        # as saved before ADR 0008
    for key in ("pairs", "sentences"):
        record.pop(key)
    (folder / "record.json").write_text(json.dumps(record), encoding="utf-8")

    reopened = pipeline.load(folder, workspace)
    article = pipeline.render(workspace, reopened)
    rows = pipeline.pairs_record(reopened, article)

    assert [(row["verdict"], row["carried_over"]) for row in rows] == [
        ("supports", True), ("supports", True), ("supports", True), (None, False)]
    assert rows[0]["reason"] == "FIXTURE given to the whole note"
    assert pipeline.status(reopened, article) == "draft"                # the second note was never judged

    pipeline.set_pair_verdict(reopened, article.pairs[1], "partly")     # the author looks again at one sentence
    rows = pipeline.pairs_record(reopened, pipeline.render(workspace, reopened))
    assert [(row["verdict"], row["carried_over"]) for row in rows][:3] == [
        ("supports", True), ("partly", False), ("supports", True)]


def test_pair_verdicts_survive_saving_and_reopening(workspace, monkeypatch, tmp_path):
    draft = one_section(workspace, monkeypatch, ONE_NOTE_THREE_SENTENCES)
    article = pipeline.render(workspace, draft)
    pipeline.set_pair_verdict(draft, article.pairs[2], "partly", "FIXTURE half of it")
    reopened = pipeline.load(pipeline.save(workspace, draft, tmp_path / "out"), workspace)

    given = pipeline.pair_verdict(reopened, pipeline.render(workspace, reopened).pairs[2])
    assert (given["verdict"], given["reason"], given["carried_over"]) == ("partly", "FIXTURE half of it", False)
    assert pipeline.pair_verdict(reopened, article.pairs[0]) is None


PASSAGE = ("FIXTURE: the keeper logged every delivery of lamp oil in a ledger. Harland describes the ledger "
           "as exact. The harbour (see fig. 2) froze in winter. Nothing here concerns orchards.")


def test_the_passage_sentences_shown_are_the_ones_that_share_most_words():
    from article import sentences
    matches = sentences.best_matches("FIXTURE the keeper kept a ledger of lamp oil deliveries [E1].", PASSAGE)

    assert [match.text for match in matches][:2] == [
        "FIXTURE: the keeper logged every delivery of lamp oil in a ledger.", "Harland describes the ledger as exact."]
    assert matches[0].shared == {"fixture", "keeper", "ledger", "lamp"} and matches[0].share == 4 / 6
    assert len(sentences.best_matches("FIXTURE the keeper, the ledger, the harbour, the winter [E1].", PASSAGE)) == 3
    assert len(sentences.best_matches("FIXTURE keeper ledger harbour winter orchards [E1].", PASSAGE, limit=2)) == 2
    assert sentences.best_matches("Glaciers retreat quickly [E1].", PASSAGE) == []          # nothing shared: nothing shown
    late = "Nothing here concerns orchards. Harland is named. FIXTURE: the keeper logged lamp oil in a ledger."
    assert sentences.best_matches("FIXTURE the keeper logged lamp oil; Harland agreed [E1].", late)[0].text.startswith("FIXTURE:")
    four = "The keeper came. The ledger lay open. The harbour froze. The winter was long."
    assert len(sentences.best_matches("FIXTURE keeper ledger harbour winter [E1].", four)) == 3      # never more than three
    assert len(sentences.split(PASSAGE)) == 4                           # "fig." does not end a sentence


def test_shared_words_are_made_bold_and_the_passage_can_never_be_read_as_formatting():
    from article import sentences
    marked = sentences.highlight("The *keeper* logged [oil] in a ledger_book <b>.", {"keeper", "logged"})

    assert marked == "The \\***keeper**\\* **logged** \\[oil\\] in a ledger\\_book \\<b\\>."


# =====================================================================================
# ADR 0008, item 3: reported speech is raised
# =====================================================================================

# Errors 2 and 3 of the published draft, rebuilt with invented names: the passage gives
# the claim to a named scholar; the drafted sentence states it as the thesis's own.
AS_CLAIMS = "FIXTURE: the lamp, as Harland claims, was never lit before dusk."
ARGUES = "FIXTURE: commenting on the ledger, Brandt argues that the keeper forged two entries."


@pytest.mark.parametrize(("passage_sentence", "name"), [
    (AS_CLAIMS, "Harland"),
    (ARGUES, "Brandt"),
    ("FIXTURE: according to al-Fixtūrī, the harbour was older than the town.", "al-Fixtūrī"),
    ("FIXTURE: in Harland's view the ledger is exact.", "Harland"),
    ("FIXTURE: Ada Brandt notes that the oil came late.", "Ada Brandt"),
])
def test_a_claim_the_passage_gives_to_a_named_person_is_raised_when_the_sentence_drops_the_name(passage_sentence, name):
    (flag,) = checks.reported_speech_flags("FIXTURE the thesis holds that this was so [E1].", passage_sentence)

    assert flag.startswith(f"the passage gives this to {name} (“") and flag.endswith(f"the sentence does not name {name}")


@pytest.mark.parametrize(("sentence", "passage_sentence"), [
    ("FIXTURE Harland claims the lamp was never lit before dusk [E1].", AS_CLAIMS),
    ("FIXTURE the keeper forged two entries, in Brandt's reading [E1].", ARGUES),
    ("FIXTURE the lamp was lit at dusk [E1].", "FIXTURE: the lamp was lit at dusk, and this gave the town its hours."),
    ("FIXTURE the lamp was lit at dusk [E1].", "FIXTURE: The author argues it was so. He notes the hour. This suggests care."),
])
def test_nothing_is_raised_when_the_name_is_kept_or_nobody_is_named(sentence, passage_sentence):
    assert checks.reported_speech_flags(sentence, passage_sentence) == []


def test_the_flag_is_raised_on_the_pair_and_recorded_and_never_blocks(workspace, monkeypatch):
    chunk = workspace.sources.chunks[0]
    chunk["text"] = AS_CLAIMS + " FIXTURE passage: the lighthouse keeper logged lamp oil deliveries every winter."
    draft = one_section(workspace, monkeypatch, "FIXTURE the lamp was never lit before dusk [E1]. FIXTURE the keeper logged lamp oil [E1].")
    article = pipeline.render(workspace, draft)

    assert article.blocked == [] and len(article.pairs) == 2            # it raises; it does not block
    assert pipeline.pair_flags(workspace, article.pairs[0]) == [
        "the passage gives this to Harland (“Harland claims”); the sentence does not name Harland"]
    assert pipeline.pair_flags(workspace, article.pairs[1]) == []
    raised = [row["raised"] for row in pipeline.build_record(workspace, draft, article)["pairs"]]
    assert len(raised[0]) == 1 and raised[1] == []
    for pair in article.pairs:                                          # and it accepts nothing either
        assert pipeline.pair_verdict(draft, pair) is None


# =====================================================================================
# ADR 0008, item 4: the researcher edits or deletes a sentence in the app
# =====================================================================================

TWO = "FIXTURE the keeper logged lamp oil [E1]. FIXTURE the oil came by sea [E1] [E2]."


def test_an_edited_sentence_is_printed_keeps_its_notes_and_needs_a_fresh_verdict(workspace, monkeypatch):
    draft = one_section(workspace, monkeypatch, TWO)
    before = pipeline.render(workspace, draft)
    for pair in before.pairs:
        pipeline.set_pair_verdict(draft, pair, "supports")
    assert pipeline.status(draft, before) == "reviewed"

    pipeline.edit_sentence(draft, "0.1", "FIXTURE the oil came by road [E2], the ledger says [E1].")
    after = pipeline.render(workspace, draft)

    assert "FIXTURE the oil came by road [2], the ledger says [1]." in after.markdown and "by sea" not in after.markdown
    assert [note["chunk_id"] for note in after.notes] == [note["chunk_id"] for note in before.notes]      # the same notes
    assert [pipeline.pair_verdict(draft, pair) is not None for pair in after.pairs] == [True, False, False]
    assert pipeline.status(draft, after) == "draft"                     # the old verdict was on the old wording
    edit = pipeline.build_record(workspace, draft, after)["sentences"]["edits"]["0.1"]
    assert edit["original"] == "FIXTURE the oil came by sea [E1] [E2]." and edit["edited_by"] == "researcher"
    assert edit["text"] == "FIXTURE the oil came by road [E2], the ledger says [E1]." and edit["edited_at"].startswith("20")
    assert all(pair["edited"] for pair in after.pairs[1:]) and not after.pairs[0]["edited"]


@pytest.mark.parametrize(("text", "reason"), [
    ("FIXTURE the oil came by road [E1].", "the sentence must keep its markers exactly ([E1] [E2])"),
    ("FIXTURE the oil came by road [E1] [E2] [E3].", "the sentence must keep its markers exactly ([E1] [E2])"),
    ("FIXTURE the oil came by road [E1, E2].", "one marker per bracket, written as [E1]"),
    ("FIXTURE the oil came by road, see p. 44 [E1] [E2].", "no page number: pages come from the notes"),
    ("[E1] states the oil came by road [E2].", "a marker closes its clause and is never a word of the sentence"),
    ("FIXTURE the oil came by road [E1] [E2]. FIXTURE and that is why the town grew.", "every sentence of the edit needs a marker of its own"),
    ("FIXTURE the ledger says “" + "oil " * 26 + "” [E1] [E2].", "quotation too long"),
    ("   ", "An edited sentence cannot be empty"),
])
def test_an_edit_that_breaks_a_rule_is_refused_with_the_reason_and_changes_nothing(workspace, monkeypatch, text, reason):
    draft = one_section(workspace, monkeypatch, TWO)

    with pytest.raises(pipeline.ArticleError, match=re.escape(reason)):
        pipeline.edit_sentence(draft, "0.1", text)
    assert draft.sentence_edits == {} and "by sea" in pipeline.render(workspace, draft).markdown


def test_an_edit_can_be_taken_back_and_survives_saving_and_reopening(workspace, monkeypatch, tmp_path):
    draft = one_section(workspace, monkeypatch, TWO)
    pipeline.edit_sentence(draft, "0.0", "FIXTURE the keeper kept a ledger of lamp oil [E1].")
    reopened = pipeline.load(pipeline.save(workspace, draft, tmp_path / "out"), workspace)
    assert "FIXTURE the keeper kept a ledger of lamp oil [1]." in pipeline.render(workspace, reopened).markdown
    assert reopened.sentence_edits["0.0"]["original"] == "FIXTURE the keeper logged lamp oil [E1]."

    pipeline.edit_sentence(reopened, "0.0", "FIXTURE the keeper logged lamp oil [E1].")      # the original wording again
    assert reopened.sentence_edits == {}


def test_a_verdict_carried_over_from_a_note_does_not_cover_an_edited_sentence(workspace, monkeypatch):
    draft = one_section(workspace, monkeypatch, TWO)
    article = pipeline.render(workspace, draft)
    for note in article.notes:
        pipeline.set_verdict(draft, note["chunk_id"], "supports")       # as an older record holds it
    pipeline.edit_sentence(draft, "0.0", "FIXTURE the keeper kept a ledger of lamp oil [E1].")
    after = pipeline.render(workspace, draft)

    assert [bool(pipeline.pair_verdict(draft, pair)) for pair in after.pairs] == [False, True, True]


# =====================================================================================
# ADR 0008, item 5: export only when reviewed
# =====================================================================================


def reviewed(workspace, monkeypatch, answer=TWO, **options):
    draft = one_section(workspace, monkeypatch, answer, **options)
    for pair in pipeline.render(workspace, draft).pairs:
        pipeline.set_pair_verdict(draft, pair, "supports")
    return draft


def with_owner(monkeypatch, name):
    import dataclasses
    monkeypatch.setattr(ask, "settings", dataclasses.replace(ask.settings, owner_name=name))


def test_nothing_is_exported_until_every_sentence_is_judged_and_none_is_judged_against(workspace, monkeypatch):
    draft = one_section(workspace, monkeypatch, UNNOTED)
    article = pipeline.render(workspace, draft)
    assert pipeline.export_blockers(draft, article) == [
        "1 sentence(s) with no note are waiting to be deleted or kept as yours", "2 of 2 sentences are not judged yet"]
    with pytest.raises(pipeline.ArticleError, match="cannot be exported yet: 1 sentence"):
        pipeline.export(workspace, draft)

    pipeline.delete_sentence(draft, "0.2")
    pipeline.set_pair_verdict(draft, article.pairs[0], "supports")
    pipeline.set_pair_verdict(draft, article.pairs[1], "does not")
    assert pipeline.export_blockers(draft, pipeline.render(workspace, draft)) == [
        "1 sentence(s) judged “does not” are still in the article"]
    assert pipeline.build_record(workspace, draft, pipeline.render(workspace, draft))["export"]["ready"] is False

    pipeline.set_pair_verdict(draft, article.pairs[1], "partly")
    assert pipeline.export_blockers(draft, pipeline.render(workspace, draft)) == []
    assert pipeline.build_record(workspace, draft, pipeline.render(workspace, draft))["export"] == {"ready": True, "blocked_by": []}
    assert set(pipeline.export(workspace, draft)) == {"markdown", "html"}


def test_the_export_opens_with_the_disclosure_drops_the_draft_line_and_lists_compact_sources(workspace, monkeypatch):
    workspace.sources.chunks[0].update(section="5.2 FIXTURE THE STATE OF THE LAMP", chapter="FIXTURE a very long chapter title")
    draft = reviewed(workspace, monkeypatch, limitations=["The thesis does not say who paid for the oil [E1]."], sufficiency="partial")
    document = workspace.document
    exported = pipeline.export(workspace, draft)
    lines = exported["markdown"].splitlines()

    assert lines[0] == "# FIXTURE title" and lines[2].startswith("This article was drafted with an AI system from ")
    assert f"{document.author} ({document.year}), {document.title}" in lines[2]              # the source is named at the top
    assert "DRAFT" not in exported["markdown"] and "Drawn from" not in exported["markdown"]
    assert "—" not in exported["markdown"].replace(document.title, "")                       # no em dash of the export's own
    sources = exported["markdown"].split("## Sources\n\n")[1].strip().split("\n\n")
    assert sources[0] == f"[1] {document.author} ({document.year}), § 5.2, p. 3."            # pages from stored provenance
    assert sources[1].startswith(f"[2] {document.author} ({document.year}), FIXTURE ") and sources[1].endswith(".")
    assert "Ch. “" not in exported["markdown"] and "THE STATE OF THE LAMP" not in exported["markdown"]
    assert "## What this article does not cover\n\n- The thesis does not say who paid for the oil [1]." in exported["markdown"]
    assert "[E" not in exported["markdown"] + exported["html"]

    page = exported["html"]
    assert page.startswith("<h1>FIXTURE title</h1>\n<p>This article was drafted with an AI system")
    assert "<h2>FIXTURE heading</h2>" in page and "<ul><li>The thesis does not say who paid for the oil [1].</li></ul>" in page
    assert "<p>FIXTURE the keeper logged lamp oil [1]. FIXTURE the oil came by sea [1] [2].</p>" in page
    assert "<h2>Sources</h2>" in page and "<script" not in page


def test_the_export_says_whose_work_the_source_is(workspace, monkeypatch):
    draft = reviewed(workspace, monkeypatch)
    surname = workspace.document.author.split(",")[0]

    with_owner(monkeypatch, None)
    unknown = pipeline.export(workspace, draft)["markdown"].splitlines()[2]
    with_owner(monkeypatch, f"FIXTURE Firstname {surname}")
    mine = pipeline.export(workspace, draft)["markdown"].splitlines()[2]
    with_owner(monkeypatch, "FIXTURE Someone Else")
    theirs = pipeline.export(workspace, draft)["markdown"].splitlines()[2]

    assert "my own work" in mine and "another author" not in mine
    assert "It summarises the work of another author: " in theirs and "the ideas are that author's" in theirs
    assert "my own" not in unknown and "another author" not in unknown           # no owner set: no claim either way
    for line in (mine, theirs, unknown):
        assert line.startswith("This article was drafted with an AI system") and workspace.document.title in line
        assert "—" not in line.replace(workspace.document.title, "")     # whichever wording: no em dash of the export's own


def test_an_edited_sentence_and_kept_own_words_are_what_is_exported(workspace, monkeypatch):
    draft = one_section(workspace, monkeypatch, UNNOTED)
    pipeline.keep_as_own_words(draft, "0.2")
    pipeline.edit_sentence(draft, "0.1", "FIXTURE the oil arrived each winter [E2].")
    for pair in pipeline.render(workspace, draft).pairs:
        pipeline.set_pair_verdict(draft, pair, "supports")
    text = pipeline.export(workspace, draft)["markdown"]

    assert "FIXTURE the keeper logged lamp oil [1]. FIXTURE the oil arrived each winter [2]. FIXTURE this is why the harbour prospered." in text
    assert "came in winter" not in text


def test_exported_html_cannot_carry_markup_from_the_text(workspace, monkeypatch):
    draft = reviewed(workspace, monkeypatch, answer="FIXTURE the keeper wrote <b>oil</b> & more [E1].")
    page = pipeline.export(workspace, draft)["html"]

    assert "<p>FIXTURE the keeper wrote &lt;b&gt;oil&lt;/b&gt; &amp; more [1].</p>" in page


# =====================================================================================
# ADR 0008, item 6: the frame is a suggestion, not printed commentary
# =====================================================================================

GOOD_FRAME = "FIXTURE the keeper logged the oil that came by sea."


class Framer(Scripted):
    """Answers a brief from the script and a frame task with what it was given."""

    def __init__(self, frame):
        super().__init__({**SCRIPT, "lighthouse": payload(TWO, cites=["E1", "E2"])})
        self.frame, self.frames = frame, []

    def __call__(self, question, items, instructions=None):
        if instructions and instructions.startswith("FRAME TASK"):
            self.frames.append((question, list(items), instructions))
            if isinstance(self.frame, BaseException):
                raise self.frame
            return payload(self.frame, cites=[]), "fixturehash"
        return super().__call__(question, items, instructions)


def framed(workspace, monkeypatch, frame):
    model = Framer(frame)
    monkeypatch.setattr(ask, "call_model", model)
    draft = pipeline.Draft("FIXTURE title", [pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])])
    return draft, model


def test_a_frame_suggestion_sees_only_the_articles_own_text_and_prints_nothing(workspace, monkeypatch):
    draft, model = framed(workspace, monkeypatch, GOOD_FRAME)
    embedded, embed = [], ask.embed_texts
    monkeypatch.setattr(ask, "embed_texts", lambda texts, **kw: embedded.append(texts) or embed(texts, **kw))
    before = pipeline.render(workspace, draft).markdown

    suggestion = pipeline.suggest_frame(workspace, draft, "introduction")
    question, items, instructions = model.frames[0]
    prompt, digest = checks.load_prompt(checks.FRAME_PROMPT)

    assert items == [] and embedded == []                               # no passage, no retrieval
    assert instructions == (f"{prompt}\nARTICLE\n=======\nFIXTURE heading\n\n"
                            "FIXTURE the keeper logged lamp oil. FIXTURE the oil came by sea.")
    assert question == "Write an introduction to the article titled “FIXTURE title”."
    assert suggestion["text"] == GOOD_FRAME and suggestion["rejected_because"] == []
    assert pipeline.render(workspace, draft).markdown == before         # a suggestion prints nothing by itself
    record = pipeline.build_record(workspace, draft, pipeline.render(workspace, draft))
    assert record["prompts"][checks.FRAME_PROMPT] == digest == record["frame_suggestions"]["introduction"][0]["prompt_sha256_12"]
    assert record["frame"]["introduction"] is None and len(model.frames) == 1


@pytest.mark.parametrize(("frame", "reason"), [
    ("FIXTURE Harland kept the oil ledger.", "new_terms: the suggestion adds “Harland”"),
    ("FIXTURE the keeper logged oil in 1923.", "new_terms: the suggestion adds “1923”"),
    ("FIXTURE the keeper kept his amāna.", "new_terms: the suggestion adds “amāna”"),
    ("FIXTURE the keeper logged oil [E1].", "brackets: the suggestion holds a bracket or a note marker"),
    ("FIXTURE the keeper logged oil [1].", "brackets: the suggestion holds a bracket or a note marker"),
    ("FIXTURE the keeper — the oil came by sea.", "em_dash: the suggestion uses an em dash"),
    (RuntimeError("FIXTURE provider outage"), "the pipeline failed: RuntimeError: FIXTURE provider outage"),
    ("", "no_text: the model returned nothing to suggest"),
])
def test_a_suggestion_that_adds_what_the_sections_do_not_hold_is_recorded_and_not_offered(workspace, monkeypatch, frame, reason):
    draft, model = framed(workspace, monkeypatch, frame)
    suggestion = pipeline.suggest_frame(workspace, draft, "conclusion")

    assert any(problem.startswith(reason) for problem in suggestion["rejected_because"]), suggestion["rejected_because"]
    assert pipeline.offered(draft, "conclusion") is None and len(model.frames) == 1          # not asked again
    assert pipeline.build_record(workspace, draft, pipeline.render(workspace, draft))["frame_suggestions"]["conclusion"][0]["rejected_because"]


def test_an_accepted_suggestion_is_printed_without_the_commentary_label_and_recorded_as_accepted(workspace, monkeypatch, tmp_path):
    draft, _ = framed(workspace, monkeypatch, GOOD_FRAME)
    pipeline.suggest_frame(workspace, draft, "conclusion")
    pipeline.set_frame(draft, "conclusion", GOOD_FRAME)
    article = pipeline.render(workspace, draft)
    record = pipeline.build_record(workspace, draft, article)["frame"]["conclusion"]

    assert f"\n{GOOD_FRAME}\n" in article.markdown and assemble.COMMENTARY_LABEL not in article.markdown
    assert record == {"origin": "suggested by model, accepted by researcher", "text": GOOD_FRAME,
                      "suggestion": GOOD_FRAME, "edited_by_researcher": False}
    assert len(article.pairs) == 3                                      # it adds nothing to judge

    reopened = pipeline.load(pipeline.save(workspace, draft, tmp_path / "out"), workspace)
    assert pipeline.render(workspace, reopened).markdown == article.markdown
    assert reopened.conclusion.origin == assemble.SUGGESTED and reopened.frame_suggestions["conclusion"][0]["text"] == GOOD_FRAME


def test_text_written_with_no_suggestion_on_offer_is_the_researchers_own(workspace, monkeypatch):
    draft, _ = framed(workspace, monkeypatch, "FIXTURE Harland kept the ledger.")
    pipeline.set_frame(draft, "introduction", "FIXTURE my own opening.")
    assert pipeline.build_record(workspace, draft, pipeline.render(workspace, draft))["frame"]["introduction"] == {
        "origin": "researcher", "text": "FIXTURE my own opening."}

    pipeline.suggest_frame(workspace, draft, "introduction")            # rejected: it adds a name
    pipeline.set_frame(draft, "introduction", "FIXTURE my own opening, again.")
    assert draft.introduction.origin == "researcher"
    pipeline.set_frame(draft, "introduction", "  ")
    assert draft.introduction is None
    with pytest.raises(pipeline.ArticleError):
        pipeline.suggest_frame(workspace, draft, "transition")


def test_no_shell_calls_the_model_without_evidence_itself():
    for shell in ("app.py", "main.py", "evaluate.py", "write_article.py"):
        assert "suggest_from_text" not in (ROOT / shell).read_text(encoding="utf-8"), shell
    source = (ROOT / "ask.py").read_text(encoding="utf-8")
    assert "suggest_from_text" not in source[source.index("def main()"):]


# =====================================================================================
# ADR 0008, item 7: a retrieval preview before paying
# =====================================================================================

IN_CORPUS = [*BRIEFS, "FIXTURE: what did the canal survey measure about locks and weirs?",
             "FIXTURE: what does the unnumbered plate show of the harbour chart?"]
OUT_OF_CORPUS = ["FIXTURE: what is the glacier melt rate?", "FIXTURE: how do volcanoes form islands?",
                 "FIXTURE: who invented the bicycle and in which year?",
                 "FIXTURE: describe photosynthesis in desert cactus plants",
                 "FIXTURE: which treaties ended the northern wars?"]
STAND_IN_THRESHOLD = 0.515          # for the offline embedding stand-in only; says nothing of a real model


def set_threshold(monkeypatch, value):
    import dataclasses
    monkeypatch.setattr(ask, "settings", dataclasses.replace(ask.settings, preview_min_score=value))


def test_the_preview_shows_pages_and_scores_from_the_embedding_step_alone(workspace, monkeypatch):
    monkeypatch.setattr(ask, "call_model", lambda *a, **k: pytest.fail("the preview called the model"))
    shown = pipeline.preview(workspace, BRIEFS[0])

    assert [passage["pages"] for passage in shown["passages"]][0] == "p. 3"          # from stored provenance
    assert shown["passages"][0]["where"] == "FIXTURE lamp oil ledger" and len(shown["passages"]) == 3
    assert shown["best_score"] == shown["passages"][0]["score"] == max(p["score"] for p in shown["passages"])
    assert shown["below_threshold"] is None and shown["threshold"] is None           # no threshold: no flag
    assert not any(p["chunk_id"].startswith("fixture-document::00004") for p in shown["passages"])     # never the reference list
    text = pipeline.format_preview([shown])
    assert "scores are diagnostics, not confidence" in text and "No threshold is set (PREVIEW_MIN_SCORE)" in text
    assert "LOOK" not in text and "FIXTURE passage:" not in text        # pages and titles, never passage text


def test_a_threshold_separates_questions_the_fixture_covers_from_ones_it_does_not(workspace, monkeypatch):
    set_threshold(monkeypatch, STAND_IN_THRESHOLD)
    covered = [pipeline.preview(workspace, brief) for brief in IN_CORPUS]
    not_covered = [pipeline.preview(workspace, brief) for brief in OUT_OF_CORPUS]

    assert max(p["best_score"] for p in not_covered) < STAND_IN_THRESHOLD < min(p["best_score"] for p in covered)
    assert [p["below_threshold"] for p in covered] == [False] * 5
    assert [p["below_threshold"] for p in not_covered] == [True] * 5
    warned = pipeline.format_preview(not_covered[:1])
    assert "LOOK: the best score," in warned and "The thesis may not cover this question." in warned
    assert "LOOK" not in pipeline.format_preview(covered)


def test_the_preview_refuses_nothing(workspace, monkeypatch):
    set_threshold(monkeypatch, 0.99)                                    # everything is "low"
    scripted(monkeypatch)
    assert pipeline.preview(workspace, BRIEFS[0])["below_threshold"] is True
    section = pipeline.draft_section(workspace, "FIXTURE heading", BRIEFS[0])

    assert pipeline.usable(section)                                     # a score never blocks a draft (hard rule 4)


# =====================================================================================
# ADR 0008, item 8: an outline helper with no model call
# =====================================================================================


def a_topic():
    from article import topics
    return topics.Topic("FIXTURE chapter", 9, "1", "9", [
        topics.Section("5.1 FIXTURE THE LAMP OIL LEDGER", 4, "1", "3"),
        topics.Section("5.2 FIXTURE grafting calendar", 1, "4", "4"),
        topics.Section("5.3 FIXTURE Tramway Timetable", 3, "5", "7"),
        topics.Section("FIXTURE canal survey", 2, "8", "9"),
    ])


def test_briefs_are_offered_by_rhetorical_move_from_the_thesiss_own_section_titles():
    from article import topics
    topic = a_topic()

    assert topics.outline(topic, "define") == [
        ("Fixture the lamp oil ledger", "How does the thesis define fixture the lamp oil ledger?"),
        ("FIXTURE Tramway Timetable", "How does the thesis define FIXTURE Tramway Timetable?"),
        ("FIXTURE canal survey", "How does the thesis define FIXTURE canal survey?")]
    assert [brief for _, brief in topics.outline(topic, topics.ARGUMENT)] == [
        "How does the thesis define fixture the lamp oil ledger?",
        "How, according to the thesis, does FIXTURE Tramway Timetable work?",
        "What, according to the thesis, follows from FIXTURE canal survey?"]
    assert topics.outline(topic, "compare")[0][1] == (
        "How does the thesis compare fixture the lamp oil ledger with FIXTURE Tramway Timetable?")
    assert topics.outline(topic, "what is not covered")[2][1] == "What does the thesis leave open about FIXTURE canal survey?"
    assert topics.outline(topic, "consequences")[1][1] == "What, according to the thesis, follows from FIXTURE Tramway Timetable?"


def test_the_summary_outline_is_what_it_was_and_every_kind_uses_only_printed_titles():
    from article import topics
    topic = a_topic()

    assert [brief for _, brief in topics.outline(topic, topics.SUMMARY)] == topics.default_briefs(topic, 3)
    assert topics.outline(topic)[0][0] == "5.1 FIXTURE THE LAMP OIL LEDGER"         # the heading as printed
    words = {"fixture", "the", "lamp", "oil", "ledger", "grafting", "calendar", "tramway", "timetable", "canal", "survey"}
    for kind in topics.OUTLINE_KINDS:
        pairs = topics.outline(topic, kind)
        assert len(pairs) == 3 and all(brief.endswith("?") for _, brief in pairs)
        for heading, _ in pairs:
            assert set(re.findall(r"[a-z]+", heading.lower())) <= words           # nothing added to a title
    with pytest.raises(ValueError):
        topics.outline(topic, "persuade")
