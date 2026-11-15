"""Reader-facing rendering — `ask.render` (hard rules 4 and 11, PLAN_V3 §6)."""

from __future__ import annotations

import pytest

import ask

QUESTION = "FIXTURE: what is the glacier melt rate?"


def refusal(build, **overrides):
    payload = {"evidence_sufficiency": "insufficient", "answer": None, "citations_used": []}
    return build(**{**payload, **overrides})


def test_a_refusal_is_a_statement_about_the_collection(items, answer):
    rendered = ask.render(QUESTION, refusal(answer), items, verbose=False)

    assert "Evidence sufficiency: INSUFFICIENT" in rendered
    assert (
        "REFUSAL — the authorised research collection does not contain sufficient "
        "evidence to answer this question."
    ) in rendered
    assert "This is a statement about the collection, not about the topic." in rendered


def test_a_refusal_names_what_retrieval_searched_from_stored_metadata(items):
    notice = ask.refusal_notice(items)

    # Section labels where a chunk has one, the chapter where it does not; four at most.
    assert (
        "returned passages from: FIXTURE lamp oil ledger; FIXTURE grafting calendar; "
        "FIXTURE tramway timetable; FIXTURE unnumbered plate. "
    ) in notice
    assert "FIXTURE canal survey" not in notice


def test_a_refusal_never_shows_prose_the_model_wrote_as_an_answer(items, answer):
    smuggled = refusal(answer, answer="FIXTURE smuggled claim about the world.")
    rendered = ask.render(QUESTION, smuggled, items, verbose=False)

    assert "FIXTURE smuggled claim" not in rendered
    assert "REFUSAL — the authorised research collection" in rendered


def test_a_refusal_carries_no_citation_footnotes(items, answer):
    rendered = ask.render(QUESTION, refusal(answer), items, verbose=False)
    assert "\n" + "─" * 30 + "\n" not in rendered


def test_a_missing_answer_is_rendered_as_a_refusal_not_as_empty_prose(items, answer):
    rendered = ask.render(QUESTION, answer(answer=None), items, verbose=False)
    assert "REFUSAL — the authorised research collection" in rendered


def test_an_answer_is_shown_with_its_limits_and_what_the_collection_lacks(items, answer):
    result = answer(
        evidence_sufficiency="partial",
        limitations=["FIXTURE: only one winter is covered [E1]."],
        unsupported_by_evidence=["FIXTURE: the price of the oil."],
    )
    rendered = ask.render(QUESTION, result, items, verbose=False)

    assert "Evidence sufficiency: PARTIAL" in rendered
    assert "FIXTURE answer about the lamp oil ledger ¹." in rendered
    assert "REFUSAL" not in rendered
    assert "LIMITS OF THIS ANSWER\n  • FIXTURE: only one winter is covered ¹." in rendered
    assert "NOT COVERED BY THE COLLECTION\n  • FIXTURE: the price of the oil." in rendered


def test_model_inference_is_labelled_as_not_the_authors_position(items, answer):
    result = answer(ai_interpretation=["FIXTURE inference drawn from the ledger [E1]."])
    rendered = ask.render(QUESTION, result, items, verbose=False)

    assert (
        "[AI INTERPRETATION] — inference beyond what the source states;\n"
        "not the author's published position.\n"
        "  • FIXTURE inference drawn from the ledger ¹."
    ) in rendered


def test_retrieval_scores_are_only_ever_presented_as_diagnostics(items, answer):
    rendered = ask.render(QUESTION, answer(), items, verbose=True)

    assert "RETRIEVAL DIAGNOSTICS (not a confidence measure)" in rendered
    assert "retrieval score (diagnostic, not confidence)" in rendered
    for line in rendered.splitlines():
        if "confidence" in line.lower():
            assert "not" in line.lower()


# --- no raw handle reaches a reader (ADR 0006) -----------------------------------------------


@pytest.mark.parametrize("bracket", ["[E1, E2]", "[E1,E2]", "[E1, 2]", "[E1; E2]", "[E1-E3]", "[E9]"])
def test_an_answer_never_prints_a_raw_handle(items, answer, bracket):
    """The last line of defence, behind validation: whatever the model wrote, a
    bracket that looks like a handle and was not resolved is not shown."""
    result = answer(answer=f"FIXTURE the keeper logged lamp oil [E1]. FIXTURE and more {bracket}.",
                    limitations=[f"FIXTURE a limit {bracket}."], ai_interpretation=[f"FIXTURE a reading {bracket}."])

    shown = ask.render("FIXTURE question?", result, items, verbose=False).split("RETRIEVAL DIAGNOSTICS")[0]

    assert "[E" not in shown and bracket not in shown
    assert shown.count(ask.UNRESOLVED_NOTE) == 3
    assert "lamp oil ¹." in shown or "lamp oil¹." in shown or "¹" in shown        # the good note still resolves


def test_scrubbing_leaves_resolved_notes_and_ordinary_brackets_alone():
    assert ask.scrub_handles("FIXTURE one [1] and [sic] and ¹.") == "FIXTURE one [1] and [sic] and ¹."
    assert ask.scrub_handles("FIXTURE [E1, E2] and [E3].") == f"FIXTURE {ask.UNRESOLVED_NOTE} and {ask.UNRESOLVED_NOTE}."
