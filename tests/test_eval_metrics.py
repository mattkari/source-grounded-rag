"""Metric functions on hand-built records with known answers (PLAN_V3 §5, §6)."""

from __future__ import annotations

from evaluation import metrics
from evaluation.metrics import Ratio


def rec(expected_type, *, outcome="completed", sufficiency=None, gold=(), retrieved=None,
        cited=None, failures=(), limitations=()):
    """One evaluation record, holding only the fields the metrics read."""
    completed = outcome == "completed"
    return {
        "expected_type": expected_type,
        "outcome": outcome,
        "evidence_sufficiency": sufficiency,
        "gold_pages": list(gold),
        "retrieved": retrieved,
        "cited_pages": list(cited) if cited is not None else ([] if completed else None),
        "validation_failures": list(failures) if completed or failures else None,
        "result": {"limitations": list(limitations)} if completed else None,
    }


def ranked(*page_lists):
    """Retrieved passages in rank order, each covering the given page labels."""
    return [{"rank": rank, "pages": list(pages)} for rank, pages in enumerate(page_lists, start=1)]


def provider_error(expected_type, **kwargs):
    return rec(expected_type, outcome="provider_error", **kwargs)


def malformed(expected_type, **kwargs):
    return rec(expected_type, outcome="malformed_output", **kwargs)


# --- Ratio -----------------------------------------------------------------


def test_a_ratio_prints_the_count_before_the_percentage():
    assert str(Ratio(3, 4)) == "3/4 (75%)"
    assert str(Ratio(0, 7)) == "0/7 (0%)"


def test_an_empty_population_is_not_reported_as_zero_percent():
    assert str(Ratio(0, 0)) == "0/0 (n/a)"


# --- outcomes ----------------------------------------------------------------


def test_every_question_lands_in_exactly_one_outcome_bucket():
    records = [
        rec("ANSWERABLE", sufficiency="sufficient"),
        rec("PARTIAL", sufficiency="partial"),
        rec("UNANSWERABLE", sufficiency="insufficient"),
        malformed("ANSWERABLE"),
        provider_error("ADVERSARIAL"),
        provider_error("ANSWERABLE"),
    ]
    counts = metrics.outcome_counts(records)

    assert counts == {
        "answered": Ratio(2, 6),
        "refused": Ratio(1, 6),
        "malformed_output": Ratio(1, 6),
        "provider_error": Ratio(2, 6),
    }
    assert sum(ratio.n for ratio in counts.values()) == len(records)


def test_only_answers_with_no_validation_failure_count_as_validated():
    records = [
        rec("ANSWERABLE", sufficiency="sufficient"),
        rec("ANSWERABLE", sufficiency="sufficient", failures=["ungrounded_answer: detail"]),
        rec("UNANSWERABLE", sufficiency="insufficient"),
        provider_error("ANSWERABLE"),
    ]
    assert metrics.validated_answers(records) == Ratio(1, 4)


# --- refusal behaviour -------------------------------------------------------


def test_refusal_correctness_counts_insufficient_over_unanswerable_and_adversarial():
    records = [
        rec("UNANSWERABLE", sufficiency="insufficient"),      # correct
        rec("ADVERSARIAL", sufficiency="insufficient"),       # correct
        rec("ADVERSARIAL", sufficiency="sufficient"),         # took the bait
        rec("UNANSWERABLE", sufficiency="partial"),           # answered anyway
        provider_error("UNANSWERABLE"),                       # stays in N, never in n
        malformed("ADVERSARIAL", sufficiency="insufficient"), # malformed is not a refusal
        rec("ANSWERABLE", sufficiency="insufficient"),        # other population
        rec("PARTIAL", sufficiency="insufficient"),           # other population
    ]
    assert metrics.refusal_correctness(records) == Ratio(2, 6)


def test_false_refusal_counts_insufficient_over_answerable_only():
    records = [
        rec("ANSWERABLE", sufficiency="insufficient"),        # case B
        rec("ANSWERABLE", sufficiency="sufficient"),
        rec("ANSWERABLE", sufficiency="partial"),
        provider_error("ANSWERABLE"),                         # an error is not a refusal
        rec("UNANSWERABLE", sufficiency="insufficient"),      # other population
    ]
    assert metrics.false_refusal(records) == Ratio(1, 4)


def test_partial_discipline_needs_the_partial_verdict_and_limitations():
    records = [
        rec("PARTIAL", sufficiency="partial", limitations=["FIXTURE limit"]),   # disciplined
        rec("PARTIAL", sufficiency="partial"),                                  # no limitations
        rec("PARTIAL", sufficiency="sufficient", limitations=["FIXTURE limit"]),  # overclaimed
        rec("PARTIAL", sufficiency="insufficient"),
        provider_error("PARTIAL"),
        rec("ANSWERABLE", sufficiency="partial", limitations=["FIXTURE limit"]),  # other population
    ]
    assert metrics.partial_discipline(records) == Ratio(1, 5)


# --- retrieval ---------------------------------------------------------------


def test_gold_rank_is_the_first_passage_covering_any_gold_page():
    record = rec("ANSWERABLE", gold=["12", "40"], retrieved=ranked(["3"], ["40", "41"], ["12"]))
    assert metrics.gold_rank(record) == 2


def test_gold_rank_is_none_when_no_retrieved_passage_covers_gold():
    assert metrics.gold_rank(rec("ANSWERABLE", gold=["12"], retrieved=ranked(["3"], ["7", "8"]))) is None
    assert metrics.gold_rank(rec("ANSWERABLE", gold=["12"], retrieved=None)) is None


def test_page_labels_match_exactly_never_as_substrings():
    record = rec("ANSWERABLE", gold=["12"], retrieved=ranked(["112"], ["1"], ["2"], ["120", "121"]))
    assert metrics.gold_rank(record) is None


def test_recall_at_k_counts_answerable_questions_with_gold_retrieved():
    records = [
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(["3"], ["9"], ["12"])),   # hit at 3
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(["12"])),                 # hit at 1
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(["3"], ["4"])),           # miss
        provider_error("ANSWERABLE", gold=["12"]),                                # not measured, in N
        rec("PARTIAL", gold=["12"], retrieved=ranked(["12"])),                    # other population
    ]
    assert metrics.recall_at_k(records) == Ratio(2, 4, not_measured=1)


def test_recall_is_independent_of_what_the_model_then_did():
    records = [
        rec("ANSWERABLE", sufficiency="insufficient", gold=["12"], retrieved=ranked(["12"])),
        malformed("ANSWERABLE", gold=["12"], retrieved=ranked(["12"])),
    ]
    assert metrics.recall_at_k(records) == Ratio(2, 2)


def test_gold_rank_distribution_separates_not_retrieved_from_not_measured():
    records = [
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(["12"])),
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(["12"], ["3"])),
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(["3"], ["9"], ["12"])),
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(["3"])),
        provider_error("ANSWERABLE", gold=["12"]),
        rec("UNANSWERABLE", retrieved=ranked(["12"])),
    ]
    assert metrics.gold_rank_distribution(records) == {
        "1": 2,
        "3": 1,
        "not_retrieved": 1,
        "not_measured": 1,
    }


def test_gold_below_rank_counts_gold_retrieved_but_below_the_threshold():
    deep = [["1"], ["2"], ["3"], ["4"], ["5"]]
    records = [
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(*deep, ["12"])),          # rank 6: below
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(*deep[:4], ["12"])),      # rank 5: not below
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(["12"])),                 # rank 1
        rec("ANSWERABLE", gold=["12"], retrieved=ranked(*deep)),                  # never retrieved
        provider_error("ANSWERABLE", gold=["12"]),
    ]
    assert metrics.gold_below_rank(records, threshold=5) == Ratio(1, 5, not_measured=1)


# --- citation ----------------------------------------------------------------


def test_citation_hit_needs_a_cited_page_that_is_a_gold_page():
    records = [
        rec("ANSWERABLE", sufficiency="sufficient", gold=["12", "13"], cited=["9", "13"]),  # hit
        rec("ANSWERABLE", sufficiency="sufficient", gold=["12"], cited=["9"]),              # wrong page
        rec("ANSWERABLE", sufficiency="sufficient", gold=["12"], cited=[]),                 # cited nothing
        rec("ANSWERABLE", sufficiency="insufficient", gold=["12"]),                         # refused
        provider_error("ANSWERABLE", gold=["12"]),                                          # in N
        malformed("ANSWERABLE", gold=["12"], cited=["12"]),                                 # never certified
        rec("PARTIAL", sufficiency="partial", gold=["12"], cited=["12"]),                   # other population
    ]
    assert metrics.citation_hit(records) == Ratio(1, 6)


# --- contract violations -------------------------------------------------------


def test_violation_type_keeps_contract_rules_apart_and_drops_run_detail():
    assert metrics.violation_type("contract: partial requires non-empty limitations") == (
        "contract: partial requires non-empty limitations"
    )
    assert metrics.violation_type("citation_hallucination: ['E9'] not in the evidence set") == (
        "citation_hallucination"
    )
    assert metrics.violation_type("invented_page_reference: model emitted ['p. 4']") == (
        "invented_page_reference"
    )


def test_contract_violations_are_counted_per_question_and_by_type():
    records = [
        rec("ANSWERABLE", sufficiency="sufficient"),
        rec("ANSWERABLE", sufficiency="sufficient",
            failures=["citation_hallucination: ['E9'] not in the evidence set",
                      "citation_hallucination: ['E8'] not in the evidence set"]),
        rec("PARTIAL", sufficiency="partial",
            failures=["contract: partial requires non-empty limitations",
                      "citation_hallucination: ['E7'] not in the evidence set"]),
        rec("UNANSWERABLE", sufficiency="insufficient",
            failures=["contract: insufficient requires answer=null"]),
        provider_error("ANSWERABLE"),   # never validated: in N, flagged as not measured
    ]
    overall, by_type = metrics.contract_violations(records)

    assert overall == Ratio(3, 5, not_measured=1)
    assert by_type == {
        "citation_hallucination": Ratio(2, 5, not_measured=1),
        "contract: insufficient requires answer=null": Ratio(1, 5, not_measured=1),
        "contract: partial requires non-empty limitations": Ratio(1, 5, not_measured=1),
    }


# --- the summary ---------------------------------------------------------------


def test_summarise_reports_every_plan_metric_and_nothing_called_accuracy():
    records = [
        rec("ANSWERABLE", sufficiency="sufficient", gold=["12"], retrieved=ranked(["12"]), cited=["12"]),
        rec("UNANSWERABLE", sufficiency="insufficient", retrieved=ranked(["3"])),
    ]
    summary = metrics.summarise(records)

    assert summary["questions_run"] == 2
    assert summary["refusal_correctness"] == Ratio(1, 1)
    assert summary["false_refusal"] == Ratio(0, 1)
    assert summary["recall_at_k"] == Ratio(1, 1)
    assert summary["gold_rank_distribution"] == {"1": 1}
    assert summary["gold_below_rank"] == Ratio(0, 1)
    assert summary["citation_hit"] == Ratio(1, 1)
    assert summary["contract_violations"] == Ratio(0, 2)
    assert summary["contract_violations_by_type"] == {}
    assert summary["partial_discipline"] == Ratio(0, 0)
    assert not any("accuracy" in key.lower() for key in summary)
    assert not any("score" in key.lower() or "similarity" in key.lower() for key in summary)
