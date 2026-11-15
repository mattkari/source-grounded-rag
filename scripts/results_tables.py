"""Turn evaluation run records into tables for the paper.

    python scripts/results_tables.py runs/eval_20261201T101500Z.jsonl
    python scripts/results_tables.py runs/eval_A.jsonl runs/eval_B.jsonl --out-dir runs/tables

For each run file given, one column. Writes two files beside the first run (or
in --out-dir): a Markdown table and a LaTeX `tabular` fragment for booktabs.

What these tables are, and are not:

  * Every figure is a count, `n/N`, over a stated population, computed by the
    same functions the run summary uses (`evaluation/metrics.py`). There are no
    percentages, no averages, and nothing called accuracy.
  * No retrieval similarity score appears (hard rule 4).
  * The caption line names the model, the prompt hash and the top-k each run
    was made with, read from the records. Nothing is typed in by hand.
  * A run file that cannot be trusted is refused, not repaired: records from
    two runs in one file, records that disagree about the model, a line that is
    not JSON. No record is skipped silently (hard rule 9).
  * Runs made over different question files are not put side by side.

The script writes only the two table files. It never edits the README or
anything under docs/: a number reaches the paper by being copied from a table
that was generated from a recorded run.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # so `python scripts/results_tables.py` finds evaluation/
    sys.path.insert(0, str(ROOT))

from evaluation import metrics  # noqa: E402

# Fields every record of one run must agree on, in the order they are checked.
RUN_FIELDS = ("run_id", "condition", "model", "top_k", "prompt_sha256_12")

# The no-retrieval baseline of PLAN_V5. Records written before E2 carry no
# condition and are ordinary runs.
BASELINE = "baseline_no_rag"
BASELINE_LABEL = " (baseline, no retrieval)"
NOT_APPLICABLE = "n/a"

CAPTION_NOTE = "Counts are n/N over the stated population."


class TableError(Exception):
    """The run files cannot be tabulated. The message says why."""


@dataclass
class Run:
    path: Path
    run_id: str
    model: str
    provider: str
    prompt_sha256_12: str
    top_k: int
    questions_sha256: str | None
    records: list[dict]
    condition: str | None = None

    @property
    def baseline(self) -> bool:
        return self.condition == BASELINE

    @property
    def heading(self) -> str:
        return self.run_id + (BASELINE_LABEL if self.baseline else "")

    def caption(self, code: str = "") -> str:
        """`code` wraps identifiers: a backtick for Markdown, nothing for LaTeX."""
        return (
            f"Run {code}{self.run_id}{code}{BASELINE_LABEL if self.baseline else ''}: model {code}{self.model}{code} ({self.provider}), "
            f"prompt sha256 {code}{self.prompt_sha256_12}{code}, top-k {self.top_k}, "
            f"{len(self.records)} questions."
        )


def load_run(path: Path) -> Run:
    path = Path(path)
    records: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise TableError(
                f"{path.name} line {number} is not valid JSON. No record is skipped silently."
            ) from exc
    if not records:
        raise TableError(f"{path.name} holds no records.")

    for name in RUN_FIELDS:
        values = {json.dumps(record.get(name)) for record in records}
        if len(values) > 1:
            raise TableError(f"{path.name} holds records from {len(values)} different values of {name}.")

    first = records[0]
    return Run(
        path=path,
        run_id=str(first.get("run_id")),
        model=str(first.get("model")),
        provider=str(first.get("provider")),
        prompt_sha256_12=str(first.get("prompt_sha256_12")),
        top_k=first.get("top_k"),
        questions_sha256=first.get("questions_sha256"),
        records=records,
        condition=first.get("condition"),
    )


def check_comparable(runs: list[Run]) -> None:
    if len({run.questions_sha256 for run in runs}) > 1:
        names = ", ".join(run.run_id for run in runs)
        raise TableError(
            f"These runs used different question files ({names}), so their counts are not "
            "comparable. Tabulate them separately."
        )


# ---------------------------------------------------------------------------
# The rows. One list, so Markdown and LaTeX can never disagree.
# ---------------------------------------------------------------------------


def _count(ratio: metrics.Ratio) -> str:
    return f"{ratio.n}/{ratio.N}"


def rows(run: Run) -> list[tuple[str, str, str]]:
    """(metric, population, n/N) for one run. `code` spans are marked with backticks."""
    s = metrics.summarise(run.records)
    outcomes = s["outcomes"]
    recall = s["recall_at_k"]
    everyone, answerable = "all questions", "ANSWERABLE"

    def retrieval(value: str) -> str:
        # A baseline retrieves nothing: these rows do not apply to it, and a
        # zero would read as "looked and found nothing".
        return NOT_APPLICABLE if run.baseline else value

    # Runs recorded before E2 did not check the page numbers the model wrote.
    checked = any("page_claims" in record for record in run.records)

    def claims(key: str) -> str:
        return _count(s[key]) if checked else NOT_APPLICABLE

    return [
        ("Answered (`sufficient` or `partial`)", everyone, _count(outcomes["answered"])),
        ("Refused (`insufficient`)", everyone, _count(outcomes["refused"])),
        ("Malformed output", everyone, _count(outcomes["malformed_output"])),
        ("Provider error", everyone, _count(outcomes["provider_error"])),
        ("Answers passing every validation check", everyone, _count(s["validated_answers"])),
        ("Refusal correctness", "UNANSWERABLE + ADVERSARIAL", _count(s["refusal_correctness"])),
        ("False refusal (case B)", answerable, _count(s["false_refusal"])),
        ("Retrieval recall@k", answerable, retrieval(_count(recall))),
        ("Retrieval not measured", answerable, retrieval(f"{recall.not_measured}/{recall.N}")),
        (f"Gold retrieved below rank {metrics.RERANKER_TRIGGER_RANK}", answerable, retrieval(_count(s["gold_below_rank"]))),
        ("Citation hit", answerable, retrieval(_count(s["citation_hit"]))),
        ("Partial discipline", "PARTIAL", _count(s["partial_discipline"])),
        ("Any contract violation", everyone, _count(s["contract_violations"])),
        ("Wrote a page number", everyone, claims("page_claims")),
        ("Wrote a page number the thesis does not print (fabricated citation)", everyone,
         claims("fabricated_page_citations")),
    ]


def _table(runs: list[Run]) -> list[tuple[str, str, list[str]]]:
    per_run = [rows(run) for run in runs]
    return [
        (metric, population, [column[index][2] for column in per_run])
        for index, (metric, population, _) in enumerate(per_run[0])
    ]


def markdown_table(runs: list[Run]) -> str:
    caption = " ".join(run.caption("`") for run in runs) + " " + CAPTION_NOTE
    out = [f"*{caption}*", ""]
    out.append("| Metric | Population | " + " | ".join(run.heading for run in runs) + " |")
    out.append("|---|---|" + "---|" * len(runs))
    for metric, population, counts in _table(runs):
        out.append(f"| {metric} | {population} | " + " | ".join(counts) + " |")
    return "\n".join(out) + "\n"


_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    return "".join(_LATEX_ESCAPES.get(char, char) for char in text)


def _latex_cell(text: str) -> str:
    """Escape a cell; a `backticked` span becomes \\texttt{...}."""
    parts = text.split("`")
    return "".join(
        latex_escape(part) if index % 2 == 0 else r"\texttt{" + latex_escape(part) + "}"
        for index, part in enumerate(parts)
    )


def latex_table(runs: list[Run]) -> str:
    caption = " ".join(run.caption() for run in runs) + " " + CAPTION_NOTE
    out = [f"% {caption}"]
    out.append(r"\begin{tabular}{ll" + "r" * len(runs) + "}")
    out.append(r"\toprule")
    out.append("Metric & Population & " + " & ".join(latex_escape(run.heading) for run in runs) + r" \\")
    out.append(r"\midrule")
    for metric, population, counts in _table(runs):
        out.append(f"{_latex_cell(metric)} & {_latex_cell(population)} & " + " & ".join(counts) + r" \\")
    out.append(r"\bottomrule")
    out.append(r"\end{tabular}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write Markdown and LaTeX tables from evaluation runs.")
    parser.add_argument("runs", nargs="+", type=Path, help="one or more runs/eval_*.jsonl files")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="where to write the tables (default: beside the first run file)")
    args = parser.parse_args(argv)

    try:
        runs = [load_run(path) for path in args.runs]
        check_comparable(runs)
    except (TableError, OSError) as exc:
        print(f"Cannot build the tables: {exc}", file=sys.stderr)
        return 2

    out_dir = args.out_dir or runs[0].path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"results_{runs[0].run_id}" + (f"_and_{len(runs) - 1}_more" if len(runs) > 1 else "")
    markdown_path, latex_path = out_dir / f"{stem}.md", out_dir / f"{stem}.tex"
    markdown_path.write_text(markdown_table(runs), encoding="utf-8")
    latex_path.write_text(latex_table(runs), encoding="utf-8")
    print(f"Markdown : {markdown_path}")
    print(f"LaTeX    : {latex_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
