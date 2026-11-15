"""The evaluation runner — `evaluate.py` (PLAN_V3 §4, Jira LAB-46).

The generation model is replaced at `ask.call_model` and nowhere else. The fake
below is scripted to give the four outcomes a real run can produce; everything
around it — index loading, retrieval ranking, validation, citation resolution,
rendering, the metrics and the three output files — is the real code.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

import pytest
import yaml

import ask
import evaluate
from config import settings
from evaluation import metrics

ROOT = Path(evaluate.__file__).resolve().parent

GROUNDED = {
    "evidence_sufficiency": "sufficient",
    "answer": "FIXTURE answer: the keeper logged lamp oil deliveries [E1].",
    "limitations": [],
    "ai_interpretation": [],
    "unsupported_by_evidence": [],
    "citations_used": ["E1"],
}
REFUSAL = {
    "evidence_sufficiency": "insufficient",
    "answer": None,
    "limitations": [],
    "ai_interpretation": [],
    "unsupported_by_evidence": ["FIXTURE: glacier melt rates"],
    "citations_used": [],
}
MALFORMED = {"evidence_sufficiency": "probably", "answer": "FIXTURE half a payload"}

QUESTIONS = [
    ("F001", "ANSWERABLE", "FIXTURE: what did the lighthouse keeper log about lamp oil?", ["3"]),
    ("F002", "UNANSWERABLE", "FIXTURE: what is the glacier melt rate?", []),
    ("F003", "ANSWERABLE", "FIXTURE: what does the orchard grafting calendar list?", ["7"]),
    ("F004", "PARTIAL", "FIXTURE: when did the tramway timetable change?", ["12"]),
]


class ScriptedModel:
    """Stand-in for `ask.call_model`: one scripted behaviour per fixture question."""

    def __init__(self, script: dict | None = None):
        self.script = script or {
            "lighthouse": GROUNDED,
            "glacier": REFUSAL,
            "orchard": MALFORMED,
            "tramway": RuntimeError("FIXTURE provider outage"),
        }
        self.calls: list[str] = []

    def __call__(self, question, items):
        self.calls.append(question)
        behaviour = next(value for key, value in self.script.items() if key in question)
        if isinstance(behaviour, BaseException):
            raise behaviour
        return behaviour, ask._get_prompt()[1]


def write_questions(path: Path, questions=QUESTIONS, empty_slots: int = 1) -> Path:
    entries = [
        {"id": qid, "batch": "FIXTURE", "question": text, "expected_type": kind,
         "gold_pages": gold, "expected_answer_summary": "", "notes": ""}
        for qid, kind, text, gold in questions
    ]
    entries += [
        {"id": f"EMPTY{n}", "batch": "FIXTURE", "question": "", "expected_type": "ADVERSARIAL",
         "gold_pages": [], "expected_answer_summary": "", "notes": ""}
        for n in range(empty_slots)
    ]
    path.write_text(yaml.safe_dump({"questions": entries}, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def harness(tmp_path, monkeypatch, fixture_index, pages_path):
    """Everything a run needs, on disk under tmp_path, with a scripted model."""

    class Harness:
        manifest = fixture_index
        model = ScriptedModel()
        out_dir = tmp_path / "runs"
        sheet = tmp_path / "evaluation" / "rating_sheet_v1.csv"
        questions = tmp_path / "questions.yaml"
        log = io.StringIO()
        index_loads = 0

        def use(self, script: dict) -> None:
            self.model = ScriptedModel(script)
            monkeypatch.setattr(ask, "call_model", self.model)

        def run(self, **kwargs) -> evaluate.RunResult:
            return evaluate.run(
                questions_path=self.questions,
                pages_path=pages_path,
                out_dir=self.out_dir,
                rating_sheet_path=self.sheet,
                stream=self.log,
                **kwargs,
            )

    h = Harness()
    write_questions(h.questions)
    monkeypatch.setattr(ask, "call_model", h.model)

    real_load_index = ask.load_index

    def counting_load_index():
        h.index_loads += 1
        return real_load_index()

    monkeypatch.setattr(ask, "load_index", counting_load_index)
    return h


def by_id(result: evaluate.RunResult) -> dict[str, dict]:
    return {record["question_id"]: record for record in result.records}


# ---------------------------------------------------------------------------
# The four outcomes
# ---------------------------------------------------------------------------


def test_all_four_outcomes_are_recorded_one_line_per_question(harness):
    result = harness.run()

    lines = harness.out_dir.joinpath(result.jsonl_path.name).read_text(encoding="utf-8").splitlines()
    on_disk = [json.loads(line) for line in lines]
    assert on_disk == result.records
    assert [(r["question_id"], r["outcome"], r["evidence_sufficiency"]) for r in on_disk] == [
        ("F001", "completed", "sufficient"),
        ("F002", "completed", "insufficient"),
        ("F003", "malformed_output", None),
        ("F004", "provider_error", None),
    ]
    assert result.exit_code == evaluate.EXIT_INCOMPLETE


def test_all_four_outcomes_appear_in_the_summary_and_none_leaves_the_denominator(harness):
    result = harness.run()
    summary = result.summary_path.read_text(encoding="utf-8")

    assert "| Grounded answer (`sufficient` or `partial`) | 1/4 (25%) |" in summary
    assert "| Refusal (`insufficient`) | 1/4 (25%) |" in summary
    assert "| Malformed output | 1/4 (25%) |" in summary
    assert "| Provider error | 1/4 (25%) |" in summary
    assert "| Questions run | 4 of 5 slots (1 not written yet) |" in summary

    # The malformed and the errored ANSWERABLE/PARTIAL questions stay in N.
    assert "| False refusal (case B) | ANSWERABLE | 0/2 (0%) |" in summary
    assert "| Citation hit | ANSWERABLE | 1/2 (50%) |" in summary
    assert "| Partial discipline | PARTIAL | 0/1 (0%) |" in summary
    assert "| Refusal correctness | UNANSWERABLE + ADVERSARIAL | 1/1 (100%) |" in summary
    assert "| F003 | ANSWERABLE | malformed_output (validation: SchemaViolation) |" in summary
    assert "| F004 | PARTIAL | provider_error (generation: RuntimeError) |" in summary


def test_the_summary_holds_no_question_text_no_score_and_nothing_called_accuracy(harness):
    summary = harness.run().summary_path.read_text(encoding="utf-8")

    assert "accuracy" not in summary.lower()
    for word in ("lighthouse", "glacier", "orchard", "tramway", "FIXTURE answer"):
        assert word not in summary
    assert "score=" not in summary
    assert "Retrieval similarity scores are diagnostics and are not reported here." in summary


def test_a_grounded_answer_records_cited_pages_resolved_from_provenance(harness):
    record = by_id(harness.run())["F001"]

    assert record["validation_failures"] == []
    assert record["citations"] == [
        {"handle": "E1", "chunk_id": "fixture-document::00000::fixture", "pages": ["3"]}
    ]
    assert record["cited_pages"] == ["3"]
    assert record["result"] == GROUNDED
    assert "p. 3." in record["rendered"]


def test_a_refusal_is_recorded_with_its_retrieval_and_no_citation(harness):
    record = by_id(harness.run())["F002"]

    assert record["evidence_sufficiency"] == "insufficient"
    assert record["cited_pages"] == []
    assert len(record["retrieved"]) == settings.top_k
    assert "REFUSAL — the authorised research collection" in record["rendered"]


def test_malformed_output_is_recorded_as_such_with_what_was_wrong(harness):
    record = by_id(harness.run())["F003"]

    assert record["outcome"] == metrics.MALFORMED
    assert record["error_stage"] == "validation"
    assert record["error_type"] == "SchemaViolation"
    assert "result: missing `limitations`" in record["error_message"]
    assert "result.evidence_sufficiency: not one of" in record["error_message"]
    assert record["result"] == MALFORMED          # kept verbatim as evidence
    assert record["evidence_sufficiency"] is None  # an invalid verdict is not a verdict
    assert record["cited_pages"] is None and record["rendered"] is None
    assert record["retrieved"][0]["pages"] == ["7", "8"]  # retrieval still measured


def test_a_provider_error_is_recorded_not_raised(harness):
    record = by_id(harness.run())["F004"]

    assert record["outcome"] == metrics.PROVIDER_ERROR
    assert record["error_stage"] == "generation"
    assert record["error_type"] == "RuntimeError"
    assert record["error_message"] == "FIXTURE provider outage"
    assert record["result"] is None and record["retrieved"] is None
    assert record["validation_failures"] is None


# ---------------------------------------------------------------------------
# No retry, nothing swallowed
# ---------------------------------------------------------------------------


def test_the_model_is_called_exactly_once_per_question_even_when_it_fails(harness):
    harness.use({"FIXTURE": RuntimeError("FIXTURE provider outage")})
    result = harness.run()

    assert harness.model.calls == [text for _, _, text, _ in QUESTIONS]
    assert [r["outcome"] for r in result.records] == ["provider_error"] * 4
    assert "| Provider error | 4/4 (100%) |" in result.summary_path.read_text(encoding="utf-8")
    assert "4 of 4 question(s) ended in a provider error or malformed output" in harness.log.getvalue()


def test_the_index_is_loaded_once_for_the_whole_run(harness):
    harness.run()
    assert harness.index_loads == 1


def test_text_that_is_not_json_is_malformed_output(harness):
    harness.use({"FIXTURE": json.JSONDecodeError("Expecting value", "FIXTURE not json", 0)})
    record = harness.run().records[0]

    assert (record["outcome"], record["error_stage"], record["error_type"]) == (
        "malformed_output", "generation", "JSONDecodeError",
    )


def test_a_payload_that_validation_cannot_read_is_malformed_output(harness):
    harness.use({"FIXTURE": {**GROUNDED, "limitations": "FIXTURE: a string where a list belongs"}})
    record = harness.run().records[0]

    assert (record["outcome"], record["error_stage"], record["error_type"]) == (
        "malformed_output", "validation", "TypeError",
    )


def test_a_pipeline_that_exits_the_process_is_recorded_as_a_provider_error(harness):
    harness.use({"FIXTURE": SystemExit("FIXTURE: model declined the request")})
    result = harness.run()

    assert [r["outcome"] for r in result.records] == ["provider_error"] * 4
    assert result.records[0]["error_type"] == "SystemExit"
    assert result.records[0]["error_message"] == "FIXTURE: model declined the request"


def test_an_embedding_failure_is_a_provider_error_at_the_retrieval_stage(harness, monkeypatch):
    def embedding_outage(texts, **kwargs):
        raise ConnectionError("FIXTURE embedding outage")

    monkeypatch.setattr(ask, "embed_texts", embedding_outage)
    result = harness.run()

    assert harness.model.calls == []
    assert [(r["outcome"], r["error_stage"]) for r in result.records] == [("provider_error", "retrieval")] * 4
    summary = result.summary_path.read_text(encoding="utf-8")
    assert f"| Retrieval recall@{settings.top_k} | ANSWERABLE | 0/2 (0%) | 2 |" in summary


def test_retrieval_not_measured_is_its_own_count_beside_each_retrieval_metric(harness):
    """An ANSWERABLE question that errors stays in N; the summary says why N is larger."""
    harness.use({
        "lighthouse": GROUNDED,
        "glacier": REFUSAL,
        "orchard": RuntimeError("FIXTURE provider outage"),   # F003, ANSWERABLE, gold 7
        "tramway": REFUSAL,
    })
    summary = harness.run().summary_path.read_text(encoding="utf-8")
    k = settings.top_k

    assert "| Metric | Population | n/N | Retrieval not measured | Note |" in summary
    assert f"| Retrieval recall@{k} | ANSWERABLE | 1/2 (50%) | 1 |" in summary
    assert "| Gold retrieved below rank 5 | ANSWERABLE | 0/2 (0%) | 1 |" in summary
    assert "| 1 | 1 |\n| retrieval not measured | 1 |" in summary            # rank table
    assert "| F003 | ANSWERABLE | provider_error (generation: RuntimeError) | — | 7 | retrieval not measured |" in summary
    # Metrics that do not depend on retrieval carry no such count.
    assert "| Citation hit | ANSWERABLE | 1/2 (50%) | — |" in summary
    assert "| False refusal (case B) | ANSWERABLE | 0/2 (0%) | — |" in summary
    assert "| Any contract violation | all questions run | 0/4 (0%) | — | 1 of the 4 never reached validation |" in summary


def test_the_not_measured_count_is_shown_even_when_it_is_zero(harness):
    harness.use({"lighthouse": GROUNDED, "FIXTURE": REFUSAL})
    summary = harness.run().summary_path.read_text(encoding="utf-8")

    assert f"| Retrieval recall@{settings.top_k} | ANSWERABLE | 2/2 (100%) | 0 |" in summary
    assert "| Gold retrieved below rank 5 | ANSWERABLE | 0/2 (0%) | 0 |" in summary
    assert "| retrieval not measured |" not in summary   # no such row in the rank table


def test_an_interrupt_stops_the_run_and_keeps_what_was_measured(harness):
    harness.use({"lighthouse": GROUNDED, "glacier": KeyboardInterrupt()})

    with pytest.raises(KeyboardInterrupt):
        harness.run()

    (jsonl,) = harness.out_dir.glob("eval_*.jsonl")
    assert [json.loads(line)["question_id"] for line in jsonl.read_text(encoding="utf-8").splitlines()] == ["F001"]


def test_nothing_key_shaped_reaches_the_run_record(harness):
    secret = "sk-" + "F" * 24
    harness.use({"FIXTURE": RuntimeError(f"FIXTURE auth failed for {secret}\nsecond line")})
    result = harness.run()

    assert result.records[0]["error_message"] == "FIXTURE auth failed for [REDACTED] second line"
    assert secret not in result.jsonl_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# What every record carries
# ---------------------------------------------------------------------------


def test_every_record_carries_the_run_configuration_read_from_config(harness):
    result = harness.run()
    prompt_hash = ask._get_prompt()[1]

    assert re.fullmatch(r"eval_\d{8}T\d{6}Z", result.records[0]["run_id"])
    assert result.jsonl_path.name == result.records[0]["run_id"] + ".jsonl"
    assert result.summary_path.name == result.records[0]["run_id"] + ".md"
    for record in result.records:
        assert record["model"] == settings.llm_model
        assert record["provider"] == settings.llm_provider
        assert record["embedding_model"] == harness.manifest["embedding_model"]
        assert record["corpus_text_sha256"] == "fixture-corpus-hash"
        assert record["prompt_sha256_12"] == prompt_hash
        assert record["top_k"] == settings.top_k
        assert record["schema_version"] == evaluate.SCHEMA_VERSION
        assert len(record["questions_sha256"]) == 64
        assert record["timestamp"]

    summary = result.summary_path.read_text(encoding="utf-8")
    assert f"| Generation model | `{settings.llm_model}` ({settings.llm_provider}) |" in summary
    assert f"| Embedding model | `{harness.manifest['embedding_model']}` |" in summary
    assert f"| Prompt hash (sha256, first 12) | `{prompt_hash}` |" in summary
    assert f"| top-k | {settings.top_k} |" in summary


def test_retrieved_passages_are_recorded_with_rank_and_stored_page_labels(harness):
    record = by_id(harness.run())["F001"]

    assert [item["rank"] for item in record["retrieved"]] == list(range(1, settings.top_k + 1))
    assert [item["handle"] for item in record["retrieved"]] == [f"E{n}" for n in range(1, settings.top_k + 1)]
    top = record["retrieved"][0]
    assert top["chunk_id"] == "fixture-document::00000::fixture"
    assert top["pages"] == ["3"]
    assert metrics.gold_rank(record) == 1
    # The unnumbered plate is retrieved somewhere in the top k, with no page label invented for it.
    unresolved = [item for item in record["retrieved"] if item["chunk_id"].startswith("fixture-document::00003")]
    assert [item["pages"] for item in unresolved] == [[]]


def test_top_k_is_passed_to_retrieval_and_recorded(harness):
    result = harness.run(top_k=2)

    completed = [r for r in result.records if r["retrieved"] is not None]
    assert completed and all(len(r["retrieved"]) == 2 for r in completed)
    assert all(r["top_k"] == 2 for r in result.records)
    assert "| top-k | 2 |" in result.summary_path.read_text(encoding="utf-8")


def test_the_run_exits_zero_when_every_question_completed(harness):
    harness.use({"lighthouse": GROUNDED, "FIXTURE": REFUSAL})
    assert harness.run().exit_code == evaluate.EXIT_OK


# ---------------------------------------------------------------------------
# The rating sheet
# ---------------------------------------------------------------------------


def test_the_rating_sheet_has_one_row_per_answered_question_with_blank_ratings(harness):
    result = harness.run()

    with harness.sheet.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "run_id": result.records[0]["run_id"],
            "condition": "rag",
            "question_id": "F001",
            "expected_type": "ANSWERABLE",
            "evidence_sufficiency": "sufficient",
            "cited_pages": "3",
            "validation_failures": "0",
            "supported": "",
            "faithful_qualification": "",
            "attribution": "",
        }
    ]


def test_a_rating_sheet_that_holds_ratings_is_never_overwritten(harness):
    harness.sheet.parent.mkdir(parents=True)
    rated = "run_id,question_id,supported,faithful_qualification,attribution\neval_old,F001,yes,,\n"
    harness.sheet.write_text(rated, encoding="utf-8")

    result = harness.run()

    assert result.exit_code == evaluate.EXIT_REFUSED
    assert harness.sheet.read_text(encoding="utf-8") == rated
    assert "already holds 1 rated row(s)" in harness.log.getvalue()
    assert harness.model.calls == [] and harness.index_loads == 0
    assert not harness.out_dir.exists()


def test_an_unrated_sheet_from_an_earlier_run_is_replaced(harness):
    harness.sheet.parent.mkdir(parents=True)
    harness.sheet.write_text(
        "run_id,question_id,supported,faithful_qualification,attribution\neval_old,F009,,,\n", encoding="utf-8"
    )

    assert harness.run().exit_code == evaluate.EXIT_INCOMPLETE
    assert "eval_old" not in harness.sheet.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Refusing to start
# ---------------------------------------------------------------------------


def test_the_runner_refuses_to_start_when_no_question_is_written(harness):
    write_questions(harness.questions, questions=[], empty_slots=30)

    result = harness.run()

    assert result.exit_code == evaluate.EXIT_REFUSED
    assert "REFUSING TO START — no question is written yet" in harness.log.getvalue()
    assert "(30 empty slots)" in harness.log.getvalue()
    assert harness.model.calls == [] and harness.index_loads == 0
    assert not harness.out_dir.exists() and not harness.sheet.exists()


def test_the_runner_refuses_to_start_when_the_gold_check_fails(harness):
    broken = QUESTIONS[:3] + [("F004", "PARTIAL", "FIXTURE: when did the tramway timetable change?", [])]
    write_questions(harness.questions, questions=broken)

    result = harness.run()

    log = harness.log.getvalue()
    assert result.exit_code == evaluate.EXIT_REFUSED
    assert "REFUSING TO START — the gold check failed" in log
    assert "PARTIAL needs at least one gold page" in log   # the table says which row and why
    assert "tramway" not in log                            # and never prints the question
    assert harness.model.calls == [] and harness.index_loads == 0
    assert not harness.out_dir.exists()


def test_the_command_line_refuses_on_the_committed_empty_template(tmp_path, capsys):
    """With no question written, `python evaluate.py` stops before touching the index."""
    if evaluate.check_gold.check().questions:
        pytest.skip("the researcher has written questions; the empty-template case no longer applies")

    code = evaluate.main(["--out-dir", str(tmp_path / "runs"), "--rating-sheet", str(tmp_path / "sheet.csv")])

    assert code == evaluate.EXIT_REFUSED
    assert "REFUSING TO START — no question is written yet" in capsys.readouterr().out
    assert not (tmp_path / "runs").exists()


# ---------------------------------------------------------------------------
# Hard rule 1 — the harness never names a model
# ---------------------------------------------------------------------------


def test_no_vendor_model_string_appears_in_the_harness_or_its_tests():
    # Built from parts so this file does not contain what it searches for.
    vendor_patterns = [
        "clau" + r"de-\w", "gp" + r"t-\d", "text-embed" + "ding", "ba" + "ai/", r"\bo\d-(?:mini|preview)",
        "gemi" + "ni-", "lla" + r"ma\d", "mist" + "ral-",
    ]
    pattern = re.compile("|".join(vendor_patterns), re.IGNORECASE)

    sources = [ROOT / "evaluate.py"]
    for folder in ("evaluation", "scripts", "tests"):
        sources += sorted((ROOT / folder).rglob("*.py"))
    assert len(sources) >= 10

    offenders = [str(path.relative_to(ROOT)) for path in sources if pattern.search(path.read_text(encoding="utf-8"))]
    assert offenders == []
