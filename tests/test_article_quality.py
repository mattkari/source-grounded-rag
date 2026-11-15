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
