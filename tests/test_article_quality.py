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
