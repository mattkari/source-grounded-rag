"""The post-generation contract — `ask.validate` (PLAN_V2 §13.5, PLAN_V3 §6).

Each case states the exact failure list, so a validator that reports too much
is caught as surely as one that reports too little.
"""

from __future__ import annotations

import pytest

import ask


def test_a_sufficient_answer_citing_supplied_evidence_passes(items, answer):
    assert ask.validate(answer(), items) == []


def test_a_clean_refusal_passes(items, answer):
    refusal = answer(evidence_sufficiency="insufficient", answer=None, citations_used=[])
    assert ask.validate(refusal, items) == []


def test_a_partial_answer_with_limitations_passes(items, answer):
    partial = answer(evidence_sufficiency="partial", limitations=["FIXTURE: only one winter is covered [E1]."])
    assert ask.validate(partial, items) == []


def test_insufficient_with_an_answer_is_a_contract_violation(items, answer):
    result = answer(evidence_sufficiency="insufficient", answer="FIXTURE prose with no handle.", citations_used=[])
    assert ask.validate(result, items) == ["contract: insufficient requires answer=null"]


def test_insufficient_with_citations_is_a_contract_violation(items, answer):
    result = answer(evidence_sufficiency="insufficient", answer=None, citations_used=["E1"])
    assert ask.validate(result, items) == ["contract: insufficient requires empty citations_used"]


def test_partial_without_limitations_is_a_contract_violation(items, answer):
    result = answer(evidence_sufficiency="partial", limitations=[])
    assert ask.validate(result, items) == ["contract: partial requires non-empty limitations"]


@pytest.mark.parametrize("sufficiency", ["sufficient", "partial"])
def test_an_answer_that_cites_nothing_is_ungrounded(items, answer, sufficiency):
    result = answer(
        evidence_sufficiency=sufficiency,
        answer="FIXTURE fluent prose that never references the evidence.",
        limitations=["FIXTURE limitation with no handle."],
        citations_used=[],
    )
    failures = ask.validate(result, items)
    assert len(failures) == 1
    assert failures[0].startswith(f"ungrounded_answer: evidence_sufficiency={sufficiency} ")


@pytest.mark.parametrize(
    "overrides",
    [
        {"answer": "FIXTURE claim [E1] and another [E9]."},
        {"citations_used": ["E1", "E9"]},
        {"citations_used": ["E1", "[E9]"]},
        {"ai_interpretation": ["FIXTURE inference [E9]."]},
        {"evidence_sufficiency": "partial", "limitations": ["FIXTURE limit [E9]."]},
    ],
    ids=["in-answer", "in-citations_used", "bracketed-in-citations_used", "in-interpretation", "in-limitations"],
)
def test_a_handle_that_was_never_supplied_is_a_citation_hallucination(items, answer, overrides):
    assert ask.validate(answer(**overrides), items) == [
        "citation_hallucination: ['E9'] not in the evidence set"
    ]


@pytest.mark.parametrize("claim", ["p. 12", "p.12", "pp. 3", "P. 44"])
def test_a_page_number_written_by_the_model_is_flagged(items, answer, claim):
    result = answer(answer=f"FIXTURE claim, see {claim} [E1].")
    failures = ask.validate(result, items)
    assert len(failures) == 1
    assert failures[0].startswith("invented_page_reference: ")


def test_several_violations_are_all_reported(items, answer):
    result = answer(
        evidence_sufficiency="insufficient",
        answer="FIXTURE claim on p. 4 [E9].",
        citations_used=["E9"],
    )
    failures = ask.validate(result, items)
    assert [f.split(":")[0] for f in failures] == [
        "citation_hallucination",
        "contract",
        "contract",
        "invented_page_reference",
    ]


@pytest.mark.xfail(
    strict=True,
    reason="Known gap in ask.PAGE_CLAIM_RE: it matches 'p. 12' but not the word 'page 12'. "
    "Reported in the E1 pull request; ask.py is outside this sprint's scope.",
)
def test_a_spelled_out_page_reference_is_flagged(items, answer):
    result = answer(answer="FIXTURE claim, see page 12 [E1].")
    assert any(f.startswith("invented_page_reference") for f in ask.validate(result, items))


# --- combined handles (ADR 0006) -------------------------------------------------------------

COMBINED = ["[E1, E2]", "[E1,E2]", "[E1, 2]", "[E1; E2]", "[E1-E3]"]


@pytest.mark.parametrize("bracket", COMBINED)
def test_a_combined_handle_fails_validation_even_when_citations_used_lists_its_parts(items, answer, bracket):
    """The first real drafts: the model wrote one bracket for two passages and listed
    both in `citations_used`, so nothing failed and the bracket was printed raw."""
    result = answer(answer=f"FIXTURE the keeper logged lamp oil {bracket}.", citations_used=["E1", "E2", "E3"])

    failures = ask.validate(result, items)

    assert len(failures) == 1 and failures[0].startswith("malformed_handle:")
    assert bracket in failures[0] and "one handle per bracket" in failures[0]


@pytest.mark.parametrize("field", ["limitations", "ai_interpretation"])
def test_a_combined_handle_is_found_in_every_field_that_is_printed(items, answer, field):
    result = answer(**{field: ["FIXTURE a further line [E1, E2]."]})

    assert any(f.startswith("malformed_handle:") for f in ask.validate(result, items))


def test_separate_handles_and_ordinary_brackets_are_not_malformed(items, answer):
    result = answer(answer="FIXTURE oil [E1] [E2], pears [E3][E4], and [sic] an [Editor's note] [E5].",
                    citations_used=["E1", "E2", "E3", "E4", "E5"])

    assert ask.validate(result, items) == []
    assert ask.malformed_handles("FIXTURE [E1] and [1] and [see Example 2] and [E 12, E3] and [e4]") == ["[E 12, E3]", "[e4]"]
