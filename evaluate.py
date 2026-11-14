"""Run the gold question set through the one pipeline and record every outcome.

    python evaluate.py                 # every written question, top-k from config
    python evaluate.py --top-k 10

Sprint E1 runner (PLAN_V3 §4, Jira LAB-46). It adds no retrieval, generation,
validation or citation logic: each question goes through `ask.run_query()`,
exactly as a question typed into the CLI or the web UI does.

Writes, per run:

    runs/eval_<timestamp>.jsonl          one record per question
    runs/eval_<timestamp>.md             counts and metrics; ids and page labels only
    evaluation/rating_sheet_v1.csv       one row per answered question, ratings blank

What the runner will not do:

  * Start without a question set it can trust. No written question, or a failed
    gold check, stops it before the index is loaded or any credit is spent.
  * Retry. A provider error or malformed output is written down as that
    question's outcome and the run moves on (hard rule 9). Such a question stays
    in every denominator.
  * Choose a model. Model names are read from config and recorded (hard rule 1).
  * Report a similarity score as a result. Scores are kept in the JSONL as
    retrieval diagnostics and appear in no metric (hard rule 4).
  * Overwrite a rating sheet that already holds a human rating.

Exit status: 0 = every question completed; 1 = the run was recorded but at least
one question ended in a provider error or malformed output; 2 = refused to start.

Known limit, stated rather than hidden: when the pipeline fails inside
`run_query`, the passages it had already retrieved are not returned, so that
question's retrieval is recorded as not measured. It still counts in N.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ask
from config import ROOT, settings
from evaluation import metrics
from scripts import check_gold

SCHEMA_VERSION = 1

DEFAULT_OUT_DIR = settings.runs_path.parent
DEFAULT_RATING_SHEET = ROOT / "evaluation" / "rating_sheet_v1.csv"

RATING_COLUMNS = ("supported", "faithful_qualification", "attribution")
SHEET_COLUMNS = (
    "run_id",
    "question_id",
    "expected_type",
    "evidence_sufficiency",
    "cited_pages",
    "validation_failures",
) + RATING_COLUMNS

EXIT_OK, EXIT_INCOMPLETE, EXIT_REFUSED = 0, 1, 2

_KEY_SHAPED = re.compile(r"\b(?:sk|pk|key)-[A-Za-z0-9_\-]{8,}")
_ERROR_MESSAGE_LIMIT = 500


@dataclass
class RunResult:
    exit_code: int
    records: list[dict] = field(default_factory=list)
    jsonl_path: Path | None = None
    summary_path: Path | None = None
    rating_sheet_path: Path | None = None


# ---------------------------------------------------------------------------
# Refusing to start
# ---------------------------------------------------------------------------


def _rated_rows(path: Path) -> int:
    """How many rows of an existing rating sheet carry at least one rating."""
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", newline="") as handle:
        return sum(
            1
            for row in csv.DictReader(handle)
            if any((row.get(column) or "").strip() for column in RATING_COLUMNS)
        )


def _refuse(message: str, stream) -> RunResult:
    print(f"REFUSING TO START — {message}", file=stream)
    return RunResult(EXIT_REFUSED)


# ---------------------------------------------------------------------------
# One question
# ---------------------------------------------------------------------------


def _schema_problems(value: object, schema: dict, where: str = "result") -> list[str]:
    """Check a payload against `ask.ANSWER_SCHEMA`. Supports exactly the JSON
    Schema keywords that schema uses, so the contract is defined in one place."""
    if "anyOf" in schema:
        if any(not _schema_problems(value, option, where) for option in schema["anyOf"]):
            return []
        return [f"{where}: matches none of the allowed types"]

    kind = schema.get("type")
    if kind == "null":
        return [] if value is None else [f"{where}: expected null"]
    if kind == "string":
        if not isinstance(value, str):
            return [f"{where}: expected a string"]
        if "enum" in schema and value not in schema["enum"]:
            return [f"{where}: not one of {schema['enum']}"]
        return []
    if kind == "array":
        if not isinstance(value, list):
            return [f"{where}: expected an array"]
        problems: list[str] = []
        for index, element in enumerate(value):
            problems += _schema_problems(element, schema.get("items", {}), f"{where}[{index}]")
        return problems
    if kind == "object":
        if not isinstance(value, dict):
            return [f"{where}: expected an object"]
        problems = [f"{where}: missing `{name}`" for name in schema.get("required", []) if name not in value]
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(str(name) for name in value if name not in properties)
            if extra:
                problems.append(f"{where}: {len(extra)} unexpected field(s)")
        for name, subschema in properties.items():
            if name in value:
                problems += _schema_problems(value[name], subschema, f"{where}.{name}")
        return problems
    return []


def _failure_stage(exc: BaseException) -> str:
    """Where in `run_query` an exception was raised, read from its traceback."""
    frames = set()
    tb = exc.__traceback__
    while tb is not None:
        frames.add(tb.tb_frame.f_code)
        tb = tb.tb_next
    if ask.validate.__code__ in frames:
        return "validation"
    if ask.retrieve.__code__ in frames:
        return "retrieval"
    return "generation"


def _classify(exc: BaseException) -> tuple[str, str]:
    """(outcome, stage) for an exception that escaped `run_query`.

    Malformed output is the model returning something that is not the agreed
    JSON object: unparseable text, or a payload validation cannot even read.
    Everything else — network, auth, rate limit, an API-level refusal, the
    embedding call failing — is a provider error.
    """
    stage = _failure_stage(exc)
    not_json = isinstance(exc, json.JSONDecodeError) or isinstance(exc.__cause__, json.JSONDecodeError)
    if stage == "validation" or (stage == "generation" and not_json):
        return metrics.MALFORMED, stage
    return metrics.PROVIDER_ERROR, stage


def _safe_message(exc: BaseException) -> str:
    """The error as recorded: single line, bounded, nothing key-shaped (hard rule 3)."""
    text = " ".join(str(exc).split())
    text = _KEY_SHAPED.sub("[REDACTED]", text)
    return text[:_ERROR_MESSAGE_LIMIT]


def chunk_pages(chunk: dict, pdf_to_label: dict[int, str | None]) -> list[str]:
    """Printed labels of the pages in a chunk's stored range, for retrieval.

    Every page of the range that carries a printed label counts, so a passage
    that runs onto a page whose number did not print is still found under the
    labels it does have.
    """
    labels: list[str] = []
    for pdf_page in range(chunk["pdf_page_start"], chunk["pdf_page_end"] + 1):
        label = pdf_to_label.get(pdf_page)
        if label is not None and label not in labels:
            labels.append(label)
    return labels


def cited_chunk_pages(chunk: dict, pdf_to_label: dict[int, str | None]) -> list[str]:
    """Printed labels a citation of this chunk puts in front of the reader.

    Follows the citation renderer exactly: when either end of the range is
    unresolved it prints "page not printed ... [VERIFY]" and no page number, so
    such a citation carries no label and cannot score a citation hit.
    """
    if chunk.get("page_start") is None or chunk.get("page_end") is None:
        return []
    labels = chunk_pages(chunk, pdf_to_label)
    for label in (chunk["page_start"], chunk["page_end"]):  # what the renderer prints
        if label not in labels:
            labels.append(label)
    return labels


def _retrieved(items: list, pdf_to_label: dict) -> list[dict]:
    return [
        {
            "rank": rank,
            "handle": item.handle,
            "chunk_id": item.chunk["chunk_id"],
            "kind": item.chunk.get("kind"),
            "pages": chunk_pages(item.chunk, pdf_to_label),
            # Diagnostic only — never a confidence figure, never a metric.
            "score": float(item.score),
        }
        for rank, item in enumerate(items, start=1)
    ]


def _cited(result: dict, items: list, pdf_to_label: dict) -> tuple[list[dict], list[str]]:
    """Citations as the renderer resolves them: handles in the model's prose,
    pages from the chunk. A page number the model wrote is never read here."""
    order = ask.assign_order(result, items)
    by_handle = {item.handle: item for item in items}
    citations, pages = [], []
    for handle, _ in sorted(order.items(), key=lambda pair: pair[1]):
        labels = cited_chunk_pages(by_handle[handle].chunk, pdf_to_label)
        citations.append({"handle": handle, "chunk_id": by_handle[handle].chunk["chunk_id"], "pages": labels})
        pages += [label for label in labels if label not in pages]
    return citations, pages


def evaluate_question(question: dict, vectors, chunks, top_k: int, run_meta: dict, pdf_to_label: dict) -> dict:
    record = {
        **run_meta,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question_id": question["id"],
        "batch": question["batch"],
        "expected_type": question["expected_type"],
        "question": question["question"],
        "gold_pages": question["gold_pages"],
        "outcome": None,
        "error_stage": None,
        "error_type": None,
        "error_message": None,
        "evidence_sufficiency": None,
        "retrieved": None,
        "citations": None,
        "cited_pages": None,
        "validation_failures": None,
        "result": None,
        "rendered": None,
    }

    try:
        outcome = ask.run_query(question["question"], vectors, chunks, top_k)
    except (Exception, SystemExit) as exc:  # recorded, never retried (hard rule 9)
        record["outcome"], record["error_stage"] = _classify(exc)
        record["error_type"] = type(exc).__name__
        record["error_message"] = _safe_message(exc)
        return record

    record["prompt_sha256_12"] = outcome.prompt_hash
    record["retrieved"] = _retrieved(outcome.items, pdf_to_label)
    record["validation_failures"] = list(outcome.failures)
    record["result"] = outcome.result

    problems = _schema_problems(outcome.result, ask.ANSWER_SCHEMA)
    if problems:
        record["outcome"] = metrics.MALFORMED
        record["error_stage"] = "validation"
        record["error_type"] = "SchemaViolation"
        record["error_message"] = "; ".join(problems)[:_ERROR_MESSAGE_LIMIT]
        return record

    record["outcome"] = metrics.COMPLETED
    record["evidence_sufficiency"] = outcome.result["evidence_sufficiency"]
    record["citations"], record["cited_pages"] = _cited(outcome.result, outcome.items, pdf_to_label)
    record["rendered"] = outcome.rendered()
    return record


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


def _is_answered(record: dict) -> bool:
    return record["outcome"] == metrics.COMPLETED and record["evidence_sufficiency"] in {"sufficient", "partial"}


def write_rating_sheet(path: Path, records: list[dict]) -> int:
    """One row per answered question, rating columns left blank for the human."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r for r in records if _is_answered(r)]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for record in rows:
            writer.writerow(
                {
                    "run_id": record["run_id"],
                    "question_id": record["question_id"],
                    "expected_type": record["expected_type"],
                    "evidence_sufficiency": record["evidence_sufficiency"],
                    "cited_pages": " ".join(record["cited_pages"]),
                    "validation_failures": len(record["validation_failures"]),
                    **{column: "" for column in RATING_COLUMNS},
                }
            )
    return len(rows)


def _note(ratio: metrics.Ratio) -> str:
    return f"{ratio.not_measured} of the {ratio.N} not measured" if ratio.not_measured else ""


def render_summary(records: list[dict], run_meta: dict, report: check_gold.Report) -> str:
    """Markdown summary. Ids, categories, page labels and counts only — no
    question text, no answer text, no thesis text — so it is safe to commit."""
    s = metrics.summarise(records)
    total = s["questions_run"]
    out: list[str] = []

    out.append(f"# Evaluation run `{run_meta['run_id']}`")
    out.append("")
    out.append("| Recorded | Value |")
    out.append("|---|---|")
    out.append(f"| Started (UTC) | {run_meta['run_started']} |")
    out.append(f"| Generation model | `{run_meta['model']}` ({run_meta['provider']}) |")
    out.append(f"| Embedding model | `{run_meta['embedding_model']}` |")
    out.append(f"| Prompt hash (sha256, first 12) | `{run_meta['prompt_sha256_12']}` |")
    out.append(f"| top-k | {run_meta['top_k']} |")
    out.append(f"| Corpus text sha256 | `{run_meta['corpus_text_sha256']}` |")
    out.append(f"| Question file | `{run_meta['questions_file']}` (sha256 `{run_meta['questions_sha256'][:12]}`) |")
    out.append(
        f"| Questions run | {total} of {len(report.rows)} slots "
        f"({len(report.not_written)} not written yet) |"
    )
    out.append("")

    out.append("## Question set")
    out.append("")
    out.append("| Category | Run | Target |")
    out.append("|---|---|---|")
    for name, counts in report.category_counts().items():
        out.append(f"| {name} | {counts['pass']} | {counts['target']} |")
    out.append("")

    out.append("## Outcomes")
    out.append("")
    out.append("Every question run is in exactly one row. Nothing is dropped and nothing was retried.")
    out.append("")
    out.append("| Outcome | n/N |")
    out.append("|---|---|")
    o = s["outcomes"]
    out.append(f"| Grounded answer (`sufficient` or `partial`) | {o['answered']} |")
    out.append(f"| Refusal (`insufficient`) | {o['refused']} |")
    out.append(f"| Malformed output | {o['malformed_output']} |")
    out.append(f"| Provider error | {o['provider_error']} |")
    out.append("")
    out.append(
        f"Answers that also passed every validation check: {s['validated_answers']}. "
        "An answer with a validation failure is not certified grounded."
    )
    out.append("")

    k = run_meta["top_k"]
    out.append("## Automatic metrics")
    out.append("")
    out.append(
        "Counts over the stated population. Whether an answer is correct is a human rating "
        "(`evaluation/rating_sheet_v1.csv`); none of these rows measures it. "
        "Retrieval similarity scores are diagnostics and are not reported here."
    )
    out.append("")
    out.append("| Metric | Population | n/N | Note |")
    out.append("|---|---|---|---|")
    out.append(f"| Refusal correctness | UNANSWERABLE + ADVERSARIAL | {s['refusal_correctness']} | answered `insufficient` |")
    out.append(f"| False refusal (case B) | ANSWERABLE | {s['false_refusal']} | answered `insufficient`; lower is better |")
    out.append(f"| Retrieval recall@{k} | ANSWERABLE | {s['recall_at_k']} | {_note(s['recall_at_k'])} |")
    below = s["gold_below_rank"]
    out.append(
        f"| Gold retrieved below rank {metrics.RERANKER_TRIGGER_RANK} | ANSWERABLE | {below} | "
        f"reranker trigger at ≥20% (PLAN_V2 §10); zero by construction when top-k ≤ {metrics.RERANKER_TRIGGER_RANK} |"
    )
    out.append(f"| Citation hit | ANSWERABLE | {s['citation_hit']} | at least one cited page is a gold page |")
    out.append(f"| Partial discipline | PARTIAL | {s['partial_discipline']} | `partial` with non-empty limitations |")
    out.append(f"| Any contract violation | all questions run | {s['contract_violations']} | {_note(s['contract_violations'])} |")
    out.append("")

    out.append("### Contract violations by type")
    out.append("")
    if s["contract_violations_by_type"]:
        out.append("| `validate()` failure | n/N |")
        out.append("|---|---|")
        for kind, ratio in s["contract_violations_by_type"].items():
            out.append(f"| {kind} | {ratio} |")
    else:
        out.append("None recorded.")
    out.append("")

    out.append("### Rank of the first gold page (ANSWERABLE)")
    out.append("")
    distribution = s["gold_rank_distribution"]
    if distribution:
        out.append("| Rank | Questions |")
        out.append("|---|---|")
        for rank in sorted((key for key in distribution if key.isdecimal()), key=int):
            out.append(f"| {rank} | {distribution[rank]} |")
        for key, label in (("not_retrieved", f"not in the top {k}"), ("not_measured", "not measured")):
            if key in distribution:
                out.append(f"| {label} | {distribution[key]} |")
    else:
        out.append("No ANSWERABLE question in this run.")
    out.append("")

    out.append("## Per question")
    out.append("")
    out.append("| Id | Category | Outcome | Sufficiency | Gold pages | Gold rank | Cited pages | Violations |")
    out.append("|---|---|---|---|---|---|---|---|")
    for record in records:
        if record["outcome"] == metrics.COMPLETED:
            outcome = "completed"
        else:
            outcome = f"{record['outcome']} ({record['error_stage']}: {record['error_type']})"
        rank = metrics.gold_rank(record)
        violations = sorted({metrics.violation_type(f) for f in record["validation_failures"] or []})
        out.append(
            f"| {record['question_id']} | {record['expected_type']} | {outcome} "
            f"| {record['evidence_sufficiency'] or '—'} "
            f"| {', '.join(record['gold_pages']) or '—'} "
            f"| {rank if rank is not None else '—'} "
            f"| {', '.join(record['cited_pages'] or []) or '—'} "
            f"| {'; '.join(violations) or '—'} |"
        )
    out.append("")

    out.append("## Limits of this run")
    out.append("")
    out.append("- One document and about 30 questions: the counts describe this corpus, not RAG in general.")
    out.append("- One human rater, who wrote the thesis and built the system — a disclosed bias.")
    out.append("- Generation is nondeterministic. This is a single run, which is a sample, not a rate.")
    out.append("- A gold page counts as retrieved or cited when it lies in a passage's stored page range.")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def run(
    *,
    questions_path: Path = check_gold.DEFAULT_QUESTIONS,
    pages_path: Path = check_gold.DEFAULT_PAGES,
    out_dir: Path = DEFAULT_OUT_DIR,
    rating_sheet_path: Path = DEFAULT_RATING_SHEET,
    top_k: int | None = None,
    stream=None,
) -> RunResult:
    stream = stream or sys.stdout
    top_k = top_k or settings.top_k

    # --- gates: all of them before the index is loaded or a call is made ----
    report = check_gold.check(questions_path, pages_path)
    if not report.ok:
        print(check_gold.format_table(report), file=stream)
        return _refuse(
            "the gold check failed. Fix the rows marked FAIL above "
            "(python scripts/check_gold.py), then run again.",
            stream,
        )
    if not report.questions:
        return _refuse(
            f"no question is written yet in {questions_path} "
            f"({len(report.not_written)} empty slots). The researcher writes the questions; "
            "this runner never generates them.",
            stream,
        )
    rated = _rated_rows(rating_sheet_path)
    if rated:
        return _refuse(
            f"{rating_sheet_path} already holds {rated} rated row(s) and would be overwritten. "
            "Move or rename it, or pass --rating-sheet with a new path.",
            stream,
        )

    started = datetime.now(timezone.utc)
    run_id = "eval_" + started.strftime("%Y%m%dT%H%M%SZ")
    jsonl_path = out_dir / f"{run_id}.jsonl"
    summary_path = out_dir / f"{run_id}.md"
    if jsonl_path.exists() or summary_path.exists():
        return _refuse(f"{jsonl_path} already exists; a run record is never overwritten.", stream)

    pdf_to_label = report.page_map.pdf_to_label
    vectors, chunks, manifest = ask.load_index()  # once for the whole run

    questions_bytes = Path(questions_path).read_bytes()
    try:
        questions_file = str(Path(questions_path).resolve().relative_to(ROOT))
    except ValueError:
        questions_file = Path(questions_path).name
    run_meta = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_started": started.isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "provider": settings.llm_provider,
        "embedding_model": manifest.get("embedding_model"),
        "top_k": top_k,
        # The prompt the pipeline is configured to send. A completed question
        # overwrites this with the hash call_model actually reported.
        "prompt_sha256_12": ask._get_prompt()[1],
        "corpus_text_sha256": manifest.get("corpus_text_sha256"),
        "document_id": manifest.get("document_id"),
        "questions_file": questions_file,
        "questions_sha256": hashlib.sha256(questions_bytes).hexdigest(),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    total = len(report.questions)
    with jsonl_path.open("x", encoding="utf-8") as handle:
        for position, question in enumerate(report.questions, start=1):
            record = evaluate_question(question, vectors, chunks, top_k, run_meta, pdf_to_label)
            # Written and flushed per question: an interrupted run keeps what it measured.
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            records.append(record)
            detail = record["evidence_sufficiency"] or f"{record['error_stage']}: {record['error_type']}"
            print(
                f"[{position}/{total}] {record['question_id']} {record['expected_type']} "
                f"-> {record['outcome']} ({detail})",
                file=stream,
            )

    summary_path.write_text(render_summary(records, run_meta, report), encoding="utf-8")
    sheet_rows = write_rating_sheet(rating_sheet_path, records)

    incomplete = sum(1 for r in records if r["outcome"] != metrics.COMPLETED)
    print(f"\nRecords : {jsonl_path}", file=stream)
    print(f"Summary : {summary_path}", file=stream)
    print(f"Ratings : {rating_sheet_path} ({sheet_rows} answered question(s) to rate)", file=stream)
    if incomplete:
        print(
            f"\n{incomplete} of {total} question(s) ended in a provider error or malformed output. "
            "They are recorded and counted; nothing was retried.",
            file=stream,
        )
    return RunResult(
        EXIT_INCOMPLETE if incomplete else EXIT_OK,
        records,
        jsonl_path,
        summary_path,
        rating_sheet_path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the gold question set and record every outcome.")
    parser.add_argument("--questions", type=Path, default=check_gold.DEFAULT_QUESTIONS)
    parser.add_argument("--pages", type=Path, default=check_gold.DEFAULT_PAGES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--rating-sheet", type=Path, default=DEFAULT_RATING_SHEET)
    parser.add_argument("-k", "--top-k", type=int, default=settings.top_k)
    args = parser.parse_args(argv)

    return run(
        questions_path=args.questions,
        pages_path=args.pages,
        out_dir=args.out_dir,
        rating_sheet_path=args.rating_sheet,
        top_k=args.top_k,
    ).exit_code


if __name__ == "__main__":
    raise SystemExit(main())
