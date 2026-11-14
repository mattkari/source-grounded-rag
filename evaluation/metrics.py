"""Automatic metrics for an evaluation run — PLAN_V3 §5.

Every metric is a count over a stated population, reported as `n/N`. None of
them is "accuracy", and none uses a retrieval similarity score (hard rule 4):
whether an answer is *correct* is a human rating, not something computed here.

The functions are pure: they take the list of per-question records written by
`evaluate.py` and return counts. Two rules hold for all of them:

  * A question whose run ended in a provider error or malformed output stays in
    N. It can never be counted in n, and it is never dropped (hard rule 9).
  * Page comparisons are between printed page labels, as strings — the same
    labels the citation renderer resolves from stored provenance.

Record fields read here: `expected_type`, `outcome`, `evidence_sufficiency`,
`gold_pages`, `retrieved` (list of {rank, pages} or None), `cited_pages`
(list or None), `validation_failures` (list or None), `result`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

COMPLETED = "completed"
MALFORMED = "malformed_output"
PROVIDER_ERROR = "provider_error"
OUTCOMES = (COMPLETED, MALFORMED, PROVIDER_ERROR)

ANSWERABLE, PARTIAL = "ANSWERABLE", "PARTIAL"
UNANSWERABLE, ADVERSARIAL = "UNANSWERABLE", "ADVERSARIAL"

# PLAN_V2 §10: revisit the reranker if, for >= 20% of ANSWERABLE questions, the
# gold passage is retrieved but ranked below this position.
RERANKER_TRIGGER_RANK = 5


@dataclass(frozen=True)
class Ratio:
    """n of N. `not_measured` counts members of N for which the run produced no
    measurement at all (the pipeline failed first); they are in N, never in n."""

    n: int
    N: int
    not_measured: int = 0

    def __str__(self) -> str:
        if self.N == 0:
            return "0/0 (n/a)"
        return f"{self.n}/{self.N} ({100 * self.n / self.N:.0f}%)"


def _of_type(records: list[dict], *types: str) -> list[dict]:
    return [r for r in records if r.get("expected_type") in types]


def _sufficiency(record: dict) -> str | None:
    """The model's verdict, or None when the run did not complete cleanly."""
    if record.get("outcome") != COMPLETED:
        return None
    return record.get("evidence_sufficiency")


def _retrieved_pages(record: dict) -> list[tuple[int, set[str]]] | None:
    retrieved = record.get("retrieved")
    if retrieved is None:
        return None
    return [(item["rank"], set(item.get("pages") or [])) for item in retrieved]


# ---------------------------------------------------------------------------
# What happened to each question
# ---------------------------------------------------------------------------


def outcome_counts(records: list[dict]) -> dict[str, Ratio]:
    """Every question lands in exactly one of four buckets."""
    total = len(records)
    answered = sum(1 for r in records if _sufficiency(r) in {"sufficient", "partial"})
    refused = sum(1 for r in records if _sufficiency(r) == "insufficient")
    malformed = sum(1 for r in records if r.get("outcome") == MALFORMED)
    errored = sum(1 for r in records if r.get("outcome") == PROVIDER_ERROR)
    return {
        "answered": Ratio(answered, total),
        "refused": Ratio(refused, total),
        "malformed_output": Ratio(malformed, total),
        "provider_error": Ratio(errored, total),
    }


def validated_answers(records: list[dict]) -> Ratio:
    """Answered (`sufficient` or `partial`) with no `validate()` failure — the
    only answers the pipeline certifies as grounded."""
    return Ratio(
        sum(
            1
            for r in records
            if _sufficiency(r) in {"sufficient", "partial"} and not r.get("validation_failures")
        ),
        len(records),
    )


# ---------------------------------------------------------------------------
# Refusal behaviour
# ---------------------------------------------------------------------------


def refusal_correctness(records: list[dict]) -> Ratio:
    """UNANSWERABLE + ADVERSARIAL questions answered `insufficient`."""
    population = _of_type(records, UNANSWERABLE, ADVERSARIAL)
    return Ratio(sum(1 for r in population if _sufficiency(r) == "insufficient"), len(population))


def false_refusal(records: list[dict]) -> Ratio:
    """Case B: ANSWERABLE questions answered `insufficient`. Lower is better."""
    population = _of_type(records, ANSWERABLE)
    return Ratio(sum(1 for r in population if _sufficiency(r) == "insufficient"), len(population))


def partial_discipline(records: list[dict]) -> Ratio:
    """PARTIAL questions answered `partial` with non-empty `limitations`."""
    population = _of_type(records, PARTIAL)

    def disciplined(record: dict) -> bool:
        if _sufficiency(record) != "partial":
            return False
        result = record.get("result")
        return isinstance(result, dict) and bool(result.get("limitations"))

    return Ratio(sum(1 for r in population if disciplined(r)), len(population))


# ---------------------------------------------------------------------------
# Retrieval — independent of what the model then did with the evidence
# ---------------------------------------------------------------------------


def gold_rank(record: dict) -> int | None:
    """Rank of the first retrieved passage that covers a gold page, else None."""
    gold = set(record.get("gold_pages") or [])
    retrieved = _retrieved_pages(record)
    if not gold or retrieved is None:
        return None
    hits = [rank for rank, pages in retrieved if pages & gold]
    return min(hits) if hits else None


def recall_at_k(records: list[dict]) -> Ratio:
    """ANSWERABLE questions where a gold page is among the retrieved passages."""
    population = _of_type(records, ANSWERABLE)
    return Ratio(
        sum(1 for r in population if gold_rank(r) is not None),
        len(population),
        not_measured=sum(1 for r in population if r.get("retrieved") is None),
    )


def gold_rank_distribution(records: list[dict]) -> dict[str, int]:
    """How many ANSWERABLE questions first met a gold page at each rank.

    Keys are the ranks as strings plus `not_retrieved` (retrieval ran, no gold
    page in the top k) and `not_measured` (retrieval produced nothing to rank).
    """
    distribution: Counter[str] = Counter()
    for record in _of_type(records, ANSWERABLE):
        if record.get("retrieved") is None:
            distribution["not_measured"] += 1
            continue
        rank = gold_rank(record)
        distribution["not_retrieved" if rank is None else str(rank)] += 1
    return dict(distribution)


def gold_below_rank(records: list[dict], threshold: int = RERANKER_TRIGGER_RANK) -> Ratio:
    """ANSWERABLE questions whose gold page was retrieved, but below `threshold`.

    This is the PLAN_V2 §10 reranker trigger. With top-k <= threshold it is zero
    by construction — nothing below the threshold is ever retrieved — so read it
    together with the top-k recorded for the run.
    """
    population = _of_type(records, ANSWERABLE)
    below = sum(1 for r in population if (gold_rank(r) or 0) > threshold)
    return Ratio(
        below,
        len(population),
        not_measured=sum(1 for r in population if r.get("retrieved") is None),
    )


# ---------------------------------------------------------------------------
# Citation
# ---------------------------------------------------------------------------


def citation_hit(records: list[dict]) -> Ratio:
    """ANSWERABLE questions where at least one cited page is a gold page.

    `cited_pages` are resolved by the citation renderer from stored provenance.
    A run that did not complete has cited nothing.
    """
    population = _of_type(records, ANSWERABLE)

    def hit(record: dict) -> bool:
        if record.get("outcome") != COMPLETED:
            return False
        return bool(set(record.get("cited_pages") or []) & set(record.get("gold_pages") or []))

    return Ratio(sum(1 for r in population if hit(r)), len(population))


# ---------------------------------------------------------------------------
# Contract violations
# ---------------------------------------------------------------------------


def violation_type(failure: str) -> str:
    """Reduce a `validate()` failure string to its stable type.

    `contract: ...` failures are fixed sentences and are kept whole, so the three
    contract rules are counted separately. The others carry run-specific detail
    after the colon (which handle, which page claim) and are reduced to the prefix.
    """
    prefix, _, _ = failure.partition(":")
    return failure.strip() if prefix.strip() == "contract" else prefix.strip()


def contract_violations(records: list[dict]) -> tuple[Ratio, dict[str, Ratio]]:
    """(questions with any `validate()` failure, the same broken down by type).

    N is every question run. A question can appear under more than one type, so
    the per-type counts need not sum to the overall count.
    """
    total = len(records)
    not_validated = sum(1 for r in records if r.get("validation_failures") is None)
    any_failure = 0
    by_type: Counter[str] = Counter()
    for record in records:
        failures = record.get("validation_failures") or []
        if failures:
            any_failure += 1
        for kind in {violation_type(f) for f in failures}:
            by_type[kind] += 1
    return (
        Ratio(any_failure, total, not_measured=not_validated),
        {kind: Ratio(count, total, not_measured=not_validated) for kind, count in sorted(by_type.items())},
    )


# ---------------------------------------------------------------------------
# Everything, for the summary
# ---------------------------------------------------------------------------


def summarise(records: list[dict]) -> dict:
    any_violation, violations_by_type = contract_violations(records)
    return {
        "questions_run": len(records),
        "outcomes": outcome_counts(records),
        "validated_answers": validated_answers(records),
        "refusal_correctness": refusal_correctness(records),
        "false_refusal": false_refusal(records),
        "recall_at_k": recall_at_k(records),
        "gold_rank_distribution": gold_rank_distribution(records),
        "gold_below_rank": gold_below_rank(records),
        "citation_hit": citation_hit(records),
        "contract_violations": any_violation,
        "contract_violations_by_type": violations_by_type,
        "partial_discipline": partial_discipline(records),
    }
