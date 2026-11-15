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

Two further modes belong to Sprint E2 (docs/plans/PLAN_V5.md):

    python evaluate.py --repeat 3            # three runs, one run group, min and max per metric
    python evaluate.py --baseline no-rag     # the same questions with retrieval switched off

The baseline uses the identical prompt and model with an empty evidence block,
through the same `ask.run_query`. Its records, summary and rating sheet are
labelled `baseline_no_rag`, and its answers are never rendered as citations.

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
    "condition",
    "question_id",
    "expected_type",
    "evidence_sufficiency",
    "cited_pages",
    "validation_failures",
) + RATING_COLUMNS

EXIT_OK, EXIT_INCOMPLETE, EXIT_REFUSED = 0, 1, 2

# The two conditions of the comparison (PLAN_V2 §20). They differ in exactly
# one variable: whether evidence was retrieved.
RAG, BASELINE_NO_RAG = "rag", "baseline_no_rag"
BASELINES = {"no-rag": BASELINE_NO_RAG}
CONDITION_NOTES = {
    RAG: "answers drawn from retrieved passages",
    BASELINE_NO_RAG: "no evidence was retrieved; the model saw the same prompt with an empty evidence block",
}
NOT_APPLICABLE = "no retrieval in this condition"

# A page reference written in prose: "p. 3", "pp. 12–14", "page 7". Arabic
# numbers only — roman numerals would match ordinary words.
_PAGE_REFERENCE = re.compile(r"\b(?:pp?\.|pages?)\s*(\d{1,4})(?:\s*[–-]\s*(\d{1,4}))?", re.IGNORECASE)
_MODEL_TEXT_FIELDS = ("answer", "limitations", "ai_interpretation", "unsupported_by_evidence")

_KEY_SHAPED = re.compile(r"\b(?:sk|pk|key)-[A-Za-z0-9_\-]{8,}")
_ERROR_MESSAGE_LIMIT = 500


@dataclass
class RunResult:
    exit_code: int
    records: list[dict] = field(default_factory=list)
    jsonl_path: Path | None = None
    summary_path: Path | None = None
    rating_sheet_path: Path | None = None
    # With --repeat: one RunResult per run, and the group summary. A single run
    # holds itself in `runs` and has no group summary.
    runs: list = field(default_factory=list)
    group_summary_path: Path | None = None


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


def extract_page_claims(result: dict, printed_labels) -> list[dict]:
    """Page numbers the model wrote, each checked against the printed labels.

    A number the thesis does not print is a fabricated citation (PLAN_V5 §3).
    One that it does print is only a claim: whether the page says what the
    model says is for the human rater.
    """
    claims: list[dict] = []
    seen: set[str] = set()
    for name in _MODEL_TEXT_FIELDS:
        value = result.get(name)
        texts = [value] if isinstance(value, str) else [t for t in value or [] if isinstance(t, str)]
        for text in texts:
            for match in _PAGE_REFERENCE.finditer(text):
                for label in match.groups():
                    if label is not None and label not in seen:
                        seen.add(label)
                        claims.append({"label": label, "exists": label in printed_labels})
    return claims


def evaluate_question(
    question: dict,
    vectors,
    chunks,
    top_k: int,
    run_meta: dict,
    page_map: check_gold.PageMap,
) -> dict:
    pdf_to_label = page_map.pdf_to_label
    baseline = run_meta["condition"] != RAG
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
        "page_claims": None,
    }

    try:
        if baseline:
            outcome = ask.run_query(question["question"], vectors, chunks, top_k, retrieve_evidence=False)
        else:
            outcome = ask.run_query(question["question"], vectors, chunks, top_k)
    except (Exception, SystemExit) as exc:  # recorded, never retried (hard rule 9)
        record["outcome"], record["error_stage"] = _classify(exc)
        record["error_type"] = type(exc).__name__
        record["error_message"] = _safe_message(exc)
        return record

    record["prompt_sha256_12"] = outcome.prompt_hash
    # In the baseline nothing was retrieved: None, not an empty list, so that
    # no retrieval metric can mistake "not applicable" for "found nothing".
    record["retrieved"] = None if baseline else _retrieved(outcome.items, pdf_to_label)
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
    record["page_claims"] = extract_page_claims(outcome.result, page_map.label_to_pdf)
    if not baseline:
        # A baseline answer has no evidence to cite and is never rendered.
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
                    "condition": record["condition"],
                    "question_id": record["question_id"],
                    "expected_type": record["expected_type"],
                    "evidence_sufficiency": record["evidence_sufficiency"],
                    "cited_pages": " ".join(record["cited_pages"] or []),
                    "validation_failures": len(record["validation_failures"]),
                    **{column: "" for column in RATING_COLUMNS},
                }
            )
    return len(rows)


NOT_MEASURED = "retrieval not measured"


def render_summary(records: list[dict], run_meta: dict, report: check_gold.Report) -> str:
    """Markdown summary. Ids, categories, page labels and counts only — no
    question text, no answer text, no thesis text — so it is safe to commit."""
    s = metrics.summarise(records)
    total = s["questions_run"]
    condition = run_meta["condition"]
    baseline = condition != RAG
    out: list[str] = []

    out.append(f"# Evaluation run `{run_meta['run_id']}`" + (" — BASELINE (no retrieval)" if baseline else ""))
    out.append("")
    out.append("| Recorded | Value |")
    out.append("|---|---|")
    out.append(f"| Condition | `{condition}` — {CONDITION_NOTES[condition]} |")
    if run_meta["run_group"]:
        out.append(
            f"| Run group | `{run_meta['run_group']}` — run {run_meta['run_number']} of {run_meta['runs_in_group']} |"
        )
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
    recall, below, violations = s["recall_at_k"], s["gold_below_rank"], s["contract_violations"]
    out.append(
        f"**{NOT_MEASURED.capitalize()}** counts questions that ended in a provider error before "
        "`run_query` returned the passages it had retrieved. They stay in N and are never counted "
        "in n, which is why N can exceed the number of questions with a retrieval result."
    )
    out.append("")
    out.append(f"| Metric | Population | n/N | {NOT_MEASURED.capitalize()} | Note |")
    out.append("|---|---|---|---|---|")
    out.append(f"| Refusal correctness | UNANSWERABLE + ADVERSARIAL | {s['refusal_correctness']} | — | answered `insufficient` |")
    out.append(f"| False refusal (case B) | ANSWERABLE | {s['false_refusal']} | — | answered `insufficient`; lower is better |")
    if baseline:
        # Not zero: these cannot be measured where nothing is retrieved (PLAN_V5 §3).
        out.append(f"| Retrieval recall@{k} | ANSWERABLE | n/a | n/a | {NOT_APPLICABLE} |")
        out.append(f"| Gold retrieved below rank {metrics.RERANKER_TRIGGER_RANK} | ANSWERABLE | n/a | n/a | {NOT_APPLICABLE} |")
        out.append(f"| Citation hit | ANSWERABLE | n/a | — | {NOT_APPLICABLE} |")
    else:
        out.append(
            f"| Retrieval recall@{k} | ANSWERABLE | {recall} | {recall.not_measured} "
            "| a gold page is among the retrieved passages |"
        )
        out.append(
            f"| Gold retrieved below rank {metrics.RERANKER_TRIGGER_RANK} | ANSWERABLE | {below} | {below.not_measured} "
            f"| reranker trigger at ≥20% (PLAN_V2 §10); zero by construction when top-k ≤ {metrics.RERANKER_TRIGGER_RANK} |"
        )
        out.append(f"| Citation hit | ANSWERABLE | {s['citation_hit']} | — | at least one cited page is a gold page |")
    out.append(f"| Partial discipline | PARTIAL | {s['partial_discipline']} | — | `partial` with non-empty limitations |")
    out.append(
        f"| Any contract violation | all questions run | {violations} | — "
        f"| {violations.not_measured} of the {violations.N} never reached validation |"
    )
    out.append(
        f"| Wrote a page number | all questions run | {s['page_claims']} | — "
        "| the model is told never to; any page number in its text is its own |"
    )
    out.append(
        "| Wrote a page number that the thesis does not print (fabricated citation) | all questions run "
        f"| {s['fabricated_page_citations']} | — | checked against the printed labels; a number that exists is not thereby correct |"
    )
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
    if baseline:
        out.append(f"Not applicable: {NOT_APPLICABLE}.")
    elif distribution:
        out.append("| Rank | Questions |")
        out.append("|---|---|")
        for rank in sorted((key for key in distribution if key.isdecimal()), key=int):
            out.append(f"| {rank} | {distribution[rank]} |")
        for key, label in (("not_retrieved", f"not in the top {k}"), ("not_measured", NOT_MEASURED)):
            if key in distribution:
                out.append(f"| {label} | {distribution[key]} |")
    else:
        out.append("No ANSWERABLE question in this run.")
    out.append("")

    out.append("## Per question")
    out.append("")
    out.append(
        "| Id | Category | Outcome | Sufficiency | Gold pages | Gold rank | Cited pages | Violations "
        "| Page numbers the model wrote |"
    )
    out.append("|---|---|---|---|---|---|---|---|---|")
    for record in records:
        if record["outcome"] == metrics.COMPLETED:
            outcome = "completed"
        else:
            outcome = f"{record['outcome']} ({record['error_stage']}: {record['error_type']})"
        rank = metrics.gold_rank(record)
        if rank is not None:
            rank_cell = str(rank)
        elif record["gold_pages"] and record["retrieved"] is None and not baseline:
            rank_cell = NOT_MEASURED
        else:
            rank_cell = "—"
        violations = sorted({metrics.violation_type(f) for f in record["validation_failures"] or []})
        out.append(
            f"| {record['question_id']} | {record['expected_type']} | {outcome} "
            f"| {record['evidence_sufficiency'] or '—'} "
            f"| {', '.join(record['gold_pages']) or '—'} "
            f"| {rank_cell} "
            f"| {', '.join(record['cited_pages'] or []) or '—'} "
            f"| {'; '.join(violations) or '—'} "
            f"| {_page_claims_cell(record)} |"
        )
    out.append("")

    out.append("## Limits of this run")
    out.append("")
    out.append("- One document and about 30 questions: the counts describe this corpus, not RAG in general.")
    out.append("- One human rater, who wrote the thesis and built the system — a disclosed bias.")
    out.append("- Generation is nondeterministic. This is a single run, which is a sample, not a rate.")
    out.append("- A gold page counts as retrieved or cited when it lies in a passage's stored page range.")
    out.append("- A page number the model wrote is checked only for existing. Whether that page supports the claim is a human rating.")
    if baseline:
        out.append(
            "- **This is the baseline.** The prompt tells the model to answer only from evidence, and it was "
            "given none. A refusal here shows how those instructions behave without retrieval; it does not "
            "show what the model would say if simply asked (PLAN_V5 §2)."
        )
        out.append("- A baseline answer cites nothing traceable, so citation and retrieval metrics do not apply to it.")
    out.append("")
    return "\n".join(out)


def _page_claims_cell(record: dict) -> str:
    claims = record.get("page_claims") or []
    return ", ".join(c["label"] if c["exists"] else f"{c['label']} (not printed)" for c in claims) or "—"


# The rows of the group summary: (label, population, key into metrics.summarise, needs retrieval).
_GROUP_ROWS = (
    ("Answered (`sufficient` or `partial`)", "all questions run", ("outcomes", "answered"), False),
    ("Refused (`insufficient`)", "all questions run", ("outcomes", "refused"), False),
    ("Malformed output", "all questions run", ("outcomes", "malformed_output"), False),
    ("Provider error", "all questions run", ("outcomes", "provider_error"), False),
    ("Answers passing every validation check", "all questions run", ("validated_answers",), False),
    ("Refusal correctness", "UNANSWERABLE + ADVERSARIAL", ("refusal_correctness",), False),
    ("False refusal (case B)", "ANSWERABLE", ("false_refusal",), False),
    ("Retrieval recall@{k}", "ANSWERABLE", ("recall_at_k",), True),
    ("Gold retrieved below rank {trigger}", "ANSWERABLE", ("gold_below_rank",), True),
    ("Citation hit", "ANSWERABLE", ("citation_hit",), True),
    ("Partial discipline", "PARTIAL", ("partial_discipline",), False),
    ("Any contract violation", "all questions run", ("contract_violations",), False),
    ("Wrote a page number", "all questions run", ("page_claims",), False),
    ("Wrote a page number that the thesis does not print (fabricated citation)", "all questions run",
     ("fabricated_page_citations",), False),
)


def render_group_summary(results: list[RunResult], group_meta: dict) -> str:
    """One table for a group of repeated runs: each metric per run, with the
    smallest and largest count. Counts only; there is deliberately no average."""
    baseline = group_meta["condition"] != RAG
    summaries = [metrics.summarise(result.records) for result in results]
    out: list[str] = []

    out.append(f"# Evaluation run group `{group_meta['run_group']}`" + (" — BASELINE (no retrieval)" if baseline else ""))
    out.append("")
    out.append("| Recorded | Value |")
    out.append("|---|---|")
    out.append(f"| Condition | `{group_meta['condition']}` — {CONDITION_NOTES[group_meta['condition']]} |")
    out.append("| Runs | " + ", ".join(f"`{result.records[0]['run_id']}`" for result in results) + " |")
    out.append(f"| Generation model | `{group_meta['model']}` ({group_meta['provider']}) |")
    out.append(f"| Prompt hash (sha256, first 12) | `{group_meta['prompt_sha256_12']}` |")
    out.append(f"| top-k | {group_meta['top_k']} |")
    out.append(f"| Question file | `{group_meta['questions_file']}` (sha256 `{group_meta['questions_sha256'][:12]}`) |")
    out.append("")
    out.append(
        f"Each metric for each of the {len(results)} runs, as n/N, with the smallest and largest count "
        "across them. No average is given: with this few runs, a single figure without its spread would "
        "mislead, and the spread is the finding."
    )
    out.append("")
    out.append("| Metric | Population | " + " | ".join(f"Run {n}" for n in range(1, len(results) + 1)) + " | Min | Max |")
    out.append("|---|---|" + "---|" * (len(results) + 2))
    for label, population, key, needs_retrieval in _GROUP_ROWS:
        label = label.format(k=group_meta["top_k"], trigger=metrics.RERANKER_TRIGGER_RANK)
        if baseline and needs_retrieval:
            cells = ["n/a"] * (len(results) + 2)
        else:
            ratios = []
            for summary in summaries:
                value = summary
                for part in key:
                    value = value[part]
                ratios.append(value)
            low, high = metrics.spread(ratios)
            cells = [f"{r.n}/{r.N}" for r in (*ratios, low, high)]
        out.append(f"| {label} | {population} | " + " | ".join(cells) + " |")
    out.append("")
    out.append("## Limits")
    out.append("")
    out.append("- The runs share one question set, one model and one prompt. Their spread is run-to-run variation, not a population.")
    out.append("- One document, about 30 questions, one rater who is also the author.")
    if baseline:
        out.append(f"- Retrieval and citation metrics are n/a: {NOT_APPLICABLE}.")
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def _sheet_for(base: Path, run_id: str, plain: bool) -> Path:
    """Only a single RAG run uses the plain rating-sheet name. Every other run
    is rated on a sheet named after it, so no sheet is ever shared or reused."""
    return base if plain else base.with_name(f"{base.stem}_{run_id}{base.suffix}")


def _execute_run(*, run_meta, questions, vectors, chunks, top_k, page_map, report, out_dir, sheet_path, stream) -> RunResult:
    run_id = run_meta["run_id"]
    jsonl_path, summary_path = out_dir / f"{run_id}.jsonl", out_dir / f"{run_id}.md"
    records: list[dict] = []
    total = len(questions)
    with jsonl_path.open("x", encoding="utf-8") as handle:
        for position, question in enumerate(questions, start=1):
            record = evaluate_question(question, vectors, chunks, top_k, run_meta, page_map)
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
    sheet_rows = write_rating_sheet(sheet_path, records)

    incomplete = sum(1 for r in records if r["outcome"] != metrics.COMPLETED)
    print(f"\nRecords : {jsonl_path}", file=stream)
    print(f"Summary : {summary_path}", file=stream)
    print(f"Ratings : {sheet_path} ({sheet_rows} answered question(s) to rate)", file=stream)
    if incomplete:
        print(
            f"\n{incomplete} of {total} question(s) ended in a provider error or malformed output. "
            "They are recorded and counted; nothing was retried.",
            file=stream,
        )
    result = RunResult(EXIT_INCOMPLETE if incomplete else EXIT_OK, records, jsonl_path, summary_path, sheet_path)
    result.runs = [result]
    return result


def run(
    *,
    questions_path: Path = check_gold.DEFAULT_QUESTIONS,
    pages_path: Path = check_gold.DEFAULT_PAGES,
    out_dir: Path = DEFAULT_OUT_DIR,
    rating_sheet_path: Path = DEFAULT_RATING_SHEET,
    top_k: int | None = None,
    stream=None,
    baseline: str | None = None,
    repeat: int = 1,
) -> RunResult:
    stream = stream or sys.stdout
    top_k = top_k or settings.top_k

    # --- gates: all of them before the index is loaded or a call is made ----
    if baseline is not None and baseline not in BASELINES:
        return _refuse(f"unknown baseline {baseline!r}. The only baseline is: {', '.join(BASELINES)}.", stream)
    if repeat < 1:
        return _refuse(f"--repeat must be 1 or more (got {repeat}).", stream)
    condition = BASELINES[baseline] if baseline else RAG

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

    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    suffix = "" if condition == RAG else f"_baseline-{baseline}"
    run_group = f"eval_group_{stamp}{suffix}" if repeat > 1 else None
    plans = []
    for number in range(1, repeat + 1):
        run_id = f"eval_{stamp}{suffix}" + (f"_r{number}of{repeat}" if repeat > 1 else "")
        sheet = _sheet_for(rating_sheet_path, run_id, plain=condition == RAG and repeat == 1)
        plans.append((number, run_id, sheet))

    for _, run_id, sheet in plans:
        rated = _rated_rows(sheet)
        if rated:
            return _refuse(
                f"{sheet} already holds {rated} rated row(s) and would be overwritten. "
                "Move or rename it, or pass --rating-sheet with a new path.",
                stream,
            )
        if (out_dir / f"{run_id}.jsonl").exists() or (out_dir / f"{run_id}.md").exists():
            return _refuse(f"{out_dir / (run_id + '.jsonl')} already exists; a run record is never overwritten.", stream)

    vectors, chunks, manifest = ask.load_index()  # once, however many runs follow

    questions_bytes = Path(questions_path).read_bytes()
    try:
        questions_file = str(Path(questions_path).resolve().relative_to(ROOT))
    except ValueError:
        questions_file = Path(questions_path).name
    shared_meta = {
        "schema_version": SCHEMA_VERSION,
        "condition": condition,
        "run_group": run_group,
        "runs_in_group": repeat,
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
    results: list[RunResult] = []
    for number, run_id, sheet in plans:
        if repeat > 1:
            print(f"\n=== Run {number} of {repeat} ({run_id}) ===", file=stream)
        run_meta = {
            **shared_meta,
            "run_id": run_id,
            "run_number": number,
            "run_started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        results.append(
            _execute_run(
                run_meta=run_meta, questions=report.questions, vectors=vectors, chunks=chunks, top_k=top_k,
                page_map=report.page_map, report=report, out_dir=out_dir, sheet_path=sheet, stream=stream,
            )
        )

    if repeat == 1:
        return results[0]

    group_summary_path = out_dir / f"{run_group}.md"
    group_summary_path.write_text(render_group_summary(results, shared_meta), encoding="utf-8")
    print(f"\nGroup summary : {group_summary_path}", file=stream)
    return RunResult(
        exit_code=max(result.exit_code for result in results),
        records=[record for result in results for record in result.records],
        runs=results,
        group_summary_path=group_summary_path,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the gold question set and record every outcome.")
    parser.add_argument("--questions", type=Path, default=check_gold.DEFAULT_QUESTIONS)
    parser.add_argument("--pages", type=Path, default=check_gold.DEFAULT_PAGES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--rating-sheet", type=Path, default=DEFAULT_RATING_SHEET)
    parser.add_argument("-k", "--top-k", type=int, default=settings.top_k)
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="run the question set N times under one run group; reports min and max")
    parser.add_argument("--baseline", choices=sorted(BASELINES), default=None,
                        help="run the same questions with retrieval switched off (PLAN_V5)")
    args = parser.parse_args(argv)

    return run(
        questions_path=args.questions,
        pages_path=args.pages,
        out_dir=args.out_dir,
        rating_sheet_path=args.rating_sheet,
        top_k=args.top_k,
        baseline=args.baseline,
        repeat=args.repeat,
    ).exit_code


if __name__ == "__main__":
    raise SystemExit(main())
