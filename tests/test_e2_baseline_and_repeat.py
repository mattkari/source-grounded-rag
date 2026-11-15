"""Sprint E2 — the no-retrieval baseline and repeated runs (PLAN_V5, Jira LAB-49).

As in the E1 runner tests, the generation model is replaced at `ask.call_model`
and nowhere else, and the embedding provider by the offline fake. Retrieval,
validation, the metrics and every output file are the real code.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

import ask
import evaluate
from config import settings
from evaluation import metrics
from evaluation.metrics import Ratio
from test_evaluate_runner import GROUNDED, QUESTIONS, REFUSAL, harness  # noqa: F401  (harness is a fixture)

ROOT = Path(evaluate.__file__).resolve().parent
BASELINE = "baseline_no_rag"


def answer(text: str, sufficiency: str = "sufficient", cites=()) -> dict:
    return {
        "evidence_sufficiency": sufficiency,
        "answer": text,
        "limitations": [],
        "ai_interpretation": [],
        "unsupported_by_evidence": [],
        "citations_used": list(cites),
    }


class Recorder:
    """Stand-in for `ask.call_model` that keeps what it was given."""

    def __init__(self, reply=None):
        self.reply = reply or (lambda question, items, call: REFUSAL)
        self.calls: list[tuple[str, list]] = []

    def __call__(self, question, items):
        self.calls.append((question, list(items)))
        reply = self.reply(question, items, len(self.calls))
        if isinstance(reply, BaseException):
            raise reply
        return reply, ask._get_prompt()[1]


@pytest.fixture
def model(harness, monkeypatch):  # noqa: F811
    def install(reply=None) -> Recorder:
        recorder = Recorder(reply)
        monkeypatch.setattr(ask, "call_model", recorder)
        return recorder

    return install


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# The one pipeline, with retrieval switched off
# ---------------------------------------------------------------------------


def test_with_retrieval_off_the_model_gets_the_same_question_and_no_evidence(harness, model, monkeypatch):  # noqa: F811
    recorder = model()
    vectors, chunks, _ = ask.load_index()

    def embedding_must_not_run(texts, **kwargs):
        raise AssertionError("the baseline called the embedding provider")

    with_evidence = ask.run_query("FIXTURE: what is the glacier melt rate?", vectors, chunks)
    monkeypatch.setattr(ask, "embed_texts", embedding_must_not_run)
    without = ask.run_query("FIXTURE: what is the glacier melt rate?", vectors, chunks, retrieve_evidence=False)

    (question_a, items_a), (question_b, items_b) = recorder.calls
    assert question_a == question_b
    assert len(items_a) == settings.top_k and items_b == []
    assert without.items == []
    assert without.prompt_hash == with_evidence.prompt_hash       # the same prompt file, byte for byte


def test_the_same_validation_runs_on_a_baseline_answer(harness, model):  # noqa: F811
    vectors, chunks, _ = ask.load_index()

    model(lambda q, items, n: answer("FIXTURE claim citing evidence it was never given [E1].", cites=["E1"]))
    cited = ask.run_query("FIXTURE: question?", vectors, chunks, retrieve_evidence=False)
    model(lambda q, items, n: answer("FIXTURE fluent claim with no handle at all."))
    uncited = ask.run_query("FIXTURE: question?", vectors, chunks, retrieve_evidence=False)
    model()
    refused = ask.run_query("FIXTURE: question?", vectors, chunks, retrieve_evidence=False)

    assert cited.failures == ["citation_hallucination: ['E1'] not in the evidence set"]
    assert [f.split(":")[0] for f in uncited.failures] == ["ungrounded_answer"]
    assert refused.failures == []
    # Even with no validation failure, an answer given without evidence is not grounded.
    assert refused.grounded is False


def test_a_baseline_answer_can_never_be_rendered_as_a_cited_answer(harness, model):  # noqa: F811
    model(lambda q, items, n: answer("FIXTURE claim from nowhere."))
    vectors, chunks, _ = ask.load_index()
    outcome = ask.run_query("FIXTURE: question?", vectors, chunks, retrieve_evidence=False)

    with pytest.raises(RuntimeError) as refused:
        outcome.rendered()

    assert str(refused.value) == (
        "A no-retrieval baseline answer is an evaluation record. It is never rendered as an answer."
    )
    assert outcome.evidence_retrieved is False
    assert outcome.grounded is False            # nothing was retrieved, so nothing is grounded


def test_an_ordinary_answer_is_still_rendered_and_marked_as_retrieved(harness, model):  # noqa: F811
    model()
    vectors, chunks, _ = ask.load_index()
    outcome = ask.run_query("FIXTURE: question?", vectors, chunks)

    assert outcome.evidence_retrieved is True
    assert "REFUSAL — the authorised research collection" in outcome.rendered()


def test_the_baseline_switch_is_reachable_only_from_the_evaluation_runner():
    """PLAN_V5 §5: not from the web UI, the interactive loop, or ask.py's command line."""
    for shell in ("app.py", "main.py"):
        source = (ROOT / shell).read_text(encoding="utf-8")
        assert "retrieve_evidence" not in source and "baseline" not in source.lower(), shell

    command_line = (ROOT / "ask.py").read_text(encoding="utf-8").split("def main() -> int:")[1]
    assert "retrieve_evidence" not in command_line and "baseline" not in command_line.lower()
    assert "retrieve_evidence=False" in (ROOT / "evaluate.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# evaluate.py --baseline no-rag
# ---------------------------------------------------------------------------


def test_a_baseline_run_is_labelled_in_every_record_file_name_and_summary(harness, model):  # noqa: F811
    recorder = model()
    result = harness.run(baseline="no-rag")
    summary = result.summary_path.read_text(encoding="utf-8")

    assert re.fullmatch(r"eval_\d{8}T\d{6}Z_baseline-no-rag\.jsonl", result.jsonl_path.name)
    assert result.summary_path.name == result.jsonl_path.stem + ".md"
    assert read_jsonl(result.jsonl_path) == result.records
    assert [r["condition"] for r in result.records] == [BASELINE] * 4
    assert all(r["run_id"].endswith("_baseline-no-rag") for r in result.records)
    assert "— BASELINE (no retrieval)" in summary.splitlines()[0]
    assert "| Condition | `baseline_no_rag` — no evidence was retrieved" in summary
    assert all(items == [] for _, items in recorder.calls)
    assert [q for q, _ in recorder.calls] == [text for _, _, text, _ in QUESTIONS]


def test_an_ordinary_run_is_labelled_rag_and_named_as_before(harness, model):  # noqa: F811
    model()
    result = harness.run()

    assert re.fullmatch(r"eval_\d{8}T\d{6}Z\.jsonl", result.jsonl_path.name)
    assert [r["condition"] for r in result.records] == ["rag"] * 4
    assert "| Condition | `rag` — answers drawn from retrieved passages |" in result.summary_path.read_text(encoding="utf-8")
    assert "BASELINE" not in result.summary_path.read_text(encoding="utf-8")


def test_a_baseline_record_holds_no_retrieval_no_citation_and_no_rendered_answer(harness, model):  # noqa: F811
    model(lambda q, items, n: answer("FIXTURE claim from nowhere [E1].", cites=["E1"]))
    record = harness.run(baseline="no-rag").records[0]

    assert record["outcome"] == metrics.COMPLETED
    assert record["evidence_sufficiency"] == "sufficient"
    assert record["retrieved"] is None
    assert record["citations"] is None and record["cited_pages"] is None
    assert record["rendered"] is None
    assert record["validation_failures"] == ["citation_hallucination: ['E1'] not in the evidence set"]
    assert record["result"]["answer"] == "FIXTURE claim from nowhere [E1]."   # kept as evidence


def test_the_two_conditions_differ_in_evidence_and_nothing_else(harness, model, tmp_path):  # noqa: F811
    model()
    rag = harness.run().records
    harness.out_dir = tmp_path / "runs-baseline"
    baseline = harness.run(baseline="no-rag").records

    same = ("model", "provider", "embedding_model", "prompt_sha256_12", "top_k", "corpus_text_sha256",
            "questions_sha256", "question_id", "question", "expected_type", "gold_pages")
    for with_evidence, without in zip(rag, baseline, strict=True):
        assert {k: with_evidence[k] for k in same} == {k: without[k] for k in same}
        assert with_evidence["retrieved"] is not None and without["retrieved"] is None


def test_retrieval_metrics_are_not_applicable_to_a_baseline_never_zero(harness, model):  # noqa: F811
    model()
    summary = harness.run(baseline="no-rag").summary_path.read_text(encoding="utf-8")
    k = settings.top_k

    assert f"| Retrieval recall@{k} | ANSWERABLE | n/a | n/a | no retrieval in this condition |" in summary
    assert "| Gold retrieved below rank 5 | ANSWERABLE | n/a | n/a | no retrieval in this condition |" in summary
    assert "| Citation hit | ANSWERABLE | n/a | — | no retrieval in this condition |" in summary
    assert "| Refusal correctness | UNANSWERABLE + ADVERSARIAL | 1/1 (100%) |" in summary
    assert "| False refusal (case B) | ANSWERABLE | 2/2 (100%) |" in summary
    assert "retrieval not measured" not in summary.split("## Per question")[1]


def test_a_baseline_run_gets_its_own_rating_sheet_with_the_condition_on_every_row(harness, model):  # noqa: F811
    model(lambda q, items, n: answer("FIXTURE claim from nowhere.") if "lighthouse" in q else REFUSAL)
    result = harness.run(baseline="no-rag")

    assert result.rating_sheet_path.name == f"rating_sheet_v1_{result.records[0]['run_id']}.csv"
    assert not harness.sheet.exists()                 # the RAG sheet is never touched
    with result.rating_sheet_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(r["question_id"], r["condition"], r["supported"]) for r in rows] == [("F001", BASELINE, "")]


def test_an_unknown_baseline_is_refused_before_anything_runs(harness, model):  # noqa: F811
    recorder = model()
    result = harness.run(baseline="some-other-baseline")

    assert result.exit_code == evaluate.EXIT_REFUSED
    assert "REFUSING TO START — unknown baseline 'some-other-baseline'" in harness.log.getvalue()
    assert recorder.calls == [] and not harness.out_dir.exists()


# ---------------------------------------------------------------------------
# Page numbers the model wrote, checked against the printed labels
# ---------------------------------------------------------------------------


def test_page_numbers_the_model_wrote_are_checked_against_the_printed_labels(harness, model):  # noqa: F811
    # The fixture document prints 1-4 and 6-20. There is no page 300, and page 5's number did not print.
    model(lambda q, items, n: answer("FIXTURE claim, see p. 3, pages 7–300 and page 5; also pp. 12.")
          if "lighthouse" in q else REFUSAL)
    result = harness.run(baseline="no-rag")
    first, second = result.records[0], result.records[1]

    assert first["page_claims"] == [
        {"label": "3", "exists": True},
        {"label": "7", "exists": True},
        {"label": "300", "exists": False},
        {"label": "5", "exists": False},
        {"label": "12", "exists": True},
    ]
    assert second["page_claims"] == []
    summary = result.summary_path.read_text(encoding="utf-8")
    assert "| Wrote a page number | all questions run | 1/4 (25%) |" in summary
    assert "| Wrote a page number that the thesis does not print (fabricated citation) | all questions run | 1/4 (25%) |" in summary
    assert (
        "| F001 | ANSWERABLE | completed | sufficient | 3 | — | — | invented_page_reference; ungrounded_answer "
        "| 3, 7, 300 (not printed), 5 (not printed), 12 |"
    ) in summary


def test_page_numbers_are_extracted_from_every_field_the_model_writes():
    result = {
        "evidence_sufficiency": "partial",
        "answer": "FIXTURE claim (p. 3).",
        "limitations": ["FIXTURE limit, Page 4."],
        "ai_interpretation": ["FIXTURE inference from pp. 6-7."],
        "unsupported_by_evidence": ["FIXTURE gap, p.999."],
        "citations_used": [],
    }
    labels = {"3", "4", "6", "7"}

    assert evaluate.extract_page_claims(result, labels) == [
        {"label": "3", "exists": True},
        {"label": "4", "exists": True},
        {"label": "6", "exists": True},
        {"label": "7", "exists": True},
        {"label": "999", "exists": False},
    ]


@pytest.mark.parametrize("text", ["FIXTURE: 300 pages were read.", "FIXTURE in 2017 the paper appeared.",
                                  "FIXTURE step 4 of the method.", "FIXTURE evidence [E3] says so."])
def test_a_number_that_is_not_a_page_reference_is_not_counted(text):
    assert evaluate.extract_page_claims({"answer": text}, {"3", "4"}) == []


def test_a_question_that_did_not_complete_has_no_page_claims_to_count(harness, model):  # noqa: F811
    model(lambda q, items, n: RuntimeError("FIXTURE provider outage"))
    record = harness.run(baseline="no-rag").records[0]

    assert record["outcome"] == metrics.PROVIDER_ERROR
    assert record["page_claims"] is None


def test_page_claim_metrics_count_questions_not_claims():
    def rec(claims):
        return {"expected_type": "ANSWERABLE", "outcome": "completed", "page_claims": claims}

    records = [
        rec([{"label": "3", "exists": True}]),
        rec([{"label": "3", "exists": True}, {"label": "300", "exists": False}, {"label": "301", "exists": False}]),
        rec([]),
        {"expected_type": "ANSWERABLE", "outcome": "provider_error", "page_claims": None},
    ]

    assert metrics.page_claims(records) == Ratio(2, 4, not_measured=1)
    assert metrics.fabricated_page_citations(records) == Ratio(1, 4, not_measured=1)
    summary = metrics.summarise(records)
    assert summary["page_claims"] == Ratio(2, 4, not_measured=1)
    assert summary["fabricated_page_citations"] == Ratio(1, 4, not_measured=1)


# ---------------------------------------------------------------------------
# evaluate.py --repeat N
# ---------------------------------------------------------------------------


def varying(question, items, call):
    """The lighthouse question is answered in the first run and refused afterwards."""
    if "lighthouse" in question and call <= 4:
        return GROUNDED
    return REFUSAL


def test_repeat_runs_the_whole_set_n_times_under_one_group_id(harness, model):  # noqa: F811
    recorder = model(varying)
    result = harness.run(repeat=3)

    assert len(result.runs) == 3
    files = sorted(harness.out_dir.glob("eval_*.jsonl"))
    assert [re.sub(r"\d{8}T\d{6}Z", "TS", f.name) for f in files] == [
        "eval_TS_r1of3.jsonl", "eval_TS_r2of3.jsonl", "eval_TS_r3of3.jsonl",
    ]
    groups = {r["run_group"] for run in result.runs for r in run.records}
    assert len(groups) == 1 and re.fullmatch(r"eval_group_\d{8}T\d{6}Z", groups.pop())
    assert [[r["run_number"] for r in run.records] for run in result.runs] == [[1] * 4, [2] * 4, [3] * 4]
    assert all(r["runs_in_group"] == 3 for run in result.runs for r in run.records)
    assert len({run.records[0]["run_id"] for run in result.runs}) == 3

    # Every question asked exactly three times, in order, and the index loaded once.
    assert [q for q, _ in recorder.calls] == [text for _, _, text, _ in QUESTIONS] * 3
    assert harness.index_loads == 1


def test_the_group_summary_gives_each_metric_per_run_with_its_min_and_max(harness, model):  # noqa: F811
    model(varying)
    result = harness.run(repeat=3)
    summary = result.group_summary_path.read_text(encoding="utf-8")

    assert result.group_summary_path.name == result.runs[0].records[0]["run_group"] + ".md"
    assert "| Metric | Population | Run 1 | Run 2 | Run 3 | Min | Max |" in summary
    assert "| Answered (`sufficient` or `partial`) | all questions run | 1/4 | 0/4 | 0/4 | 0/4 | 1/4 |" in summary
    assert "| False refusal (case B) | ANSWERABLE | 1/2 | 2/2 | 2/2 | 1/2 | 2/2 |" in summary
    assert "| Citation hit | ANSWERABLE | 1/2 | 0/2 | 0/2 | 0/2 | 1/2 |" in summary
    assert f"| Retrieval recall@{settings.top_k} | ANSWERABLE | 2/2 | 2/2 | 2/2 | 2/2 | 2/2 |" in summary
    for run in result.runs:
        assert f"`{run.records[0]['run_id']}`" in summary


def test_the_group_summary_prints_no_average(harness, model):  # noqa: F811
    model(varying)
    summary = harness.run(repeat=2).group_summary_path.read_text(encoding="utf-8").lower()

    for word in ("mean", "avg", "accuracy", "on average"):
        assert word not in summary
    # The word appears once, in the sentence saying why there is none.
    assert summary.count("average") == 1 and "no average is given" in summary


def test_a_failure_in_one_run_stays_in_that_run_and_is_not_retried(harness, model):  # noqa: F811
    def flaky(question, items, call):
        return RuntimeError("FIXTURE provider outage") if call == 2 else REFUSAL

    recorder = model(flaky)
    result = harness.run(repeat=2)

    assert len(recorder.calls) == 8                       # 4 questions x 2 runs, no extra call
    assert [r["outcome"] for r in result.runs[0].records] == ["completed", "provider_error", "completed", "completed"]
    assert [r["outcome"] for r in result.runs[1].records] == ["completed"] * 4
    assert result.exit_code == evaluate.EXIT_INCOMPLETE
    assert "| Provider error | all questions run | 1/4 | 0/4 | 0/4 | 1/4 |" in result.group_summary_path.read_text(encoding="utf-8")


def test_a_single_run_has_no_group_and_no_group_summary(harness, model):  # noqa: F811
    model()
    result = harness.run()

    assert result.group_summary_path is None
    assert [(r["run_group"], r["run_number"], r["runs_in_group"]) for r in result.records] == [(None, 1, 1)] * 4
    assert list(harness.out_dir.glob("eval_group_*")) == []


def test_each_repeated_run_gets_its_own_rating_sheet(harness, model):  # noqa: F811
    model(varying)
    result = harness.run(repeat=2)

    names = [run.rating_sheet_path.name for run in result.runs]
    assert names == [f"rating_sheet_v1_{run.records[0]['run_id']}.csv" for run in result.runs]
    assert len(set(names)) == 2 and not harness.sheet.exists()


def test_repeat_and_baseline_combine_and_both_show_in_the_names(harness, model):  # noqa: F811
    recorder = model()
    result = harness.run(repeat=2, baseline="no-rag")

    assert [re.sub(r"\d{8}T\d{6}Z", "TS", run.jsonl_path.name) for run in result.runs] == [
        "eval_TS_baseline-no-rag_r1of2.jsonl", "eval_TS_baseline-no-rag_r2of2.jsonl",
    ]
    assert re.fullmatch(r"eval_group_\d{8}T\d{6}Z_baseline-no-rag\.md", result.group_summary_path.name)
    group = result.group_summary_path.read_text(encoding="utf-8")
    assert "BASELINE (no retrieval)" in group.splitlines()[0]
    assert "| Citation hit | ANSWERABLE | n/a | n/a | n/a | n/a |" in group        # not applicable, never 0/2
    assert "| Refused (`insufficient`) | all questions run | 4/4 | 4/4 | 4/4 | 4/4 |" in group
    assert all(items == [] for _, items in recorder.calls)


@pytest.mark.parametrize("repeat", [0, -1])
def test_a_repeat_count_below_one_is_refused(harness, model, repeat):  # noqa: F811
    recorder = model()
    result = harness.run(repeat=repeat)

    assert result.exit_code == evaluate.EXIT_REFUSED
    assert "REFUSING TO START — --repeat must be 1 or more" in harness.log.getvalue()
    assert recorder.calls == []


def test_spread_is_the_smallest_and_largest_count_across_runs():
    assert metrics.spread([Ratio(3, 5), Ratio(1, 5), Ratio(4, 5)]) == (Ratio(1, 5), Ratio(4, 5))
    assert metrics.spread([Ratio(2, 5)]) == (Ratio(2, 5), Ratio(2, 5))


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def test_the_command_line_offers_only_the_one_baseline(capsys):
    with pytest.raises(SystemExit):
        evaluate.main(["--baseline", "something-else"])

    assert "invalid choice: 'something-else' (choose from no-rag)" in capsys.readouterr().err.replace("'no-rag'", "no-rag")
