"""Paper results tables — `scripts/results_tables.py` (Hermes's Task 3).

Hand-built records with known answers go in; the exact Markdown and LaTeX come
out. Every figure is a count over a stated population. No thesis text, no model
call, and no vendor model string: the fixture model is called "fixture-model".
"""

from __future__ import annotations

import json

import pytest

from scripts import results_tables
from scripts.results_tables import TableError


def record(qid, expected_type, *, outcome="completed", sufficiency=None, gold=(), retrieved="ranked",
           cited=(), failures=(), limitations=(), run_id="eval_20260101T000000Z", **meta):
    """One evaluation record carrying only what the tables read."""
    completed = outcome == "completed"
    if retrieved == "ranked":
        retrieved = [{"rank": 1, "pages": list(gold) or ["3"]}]
    return {
        "run_id": run_id,
        "model": "fixture-model",
        "provider": "fixture-provider",
        "prompt_sha256_12": "abcdef012345",
        "top_k": 5,
        "questions_sha256": "q" * 64,
        "question_id": qid,
        "expected_type": expected_type,
        "outcome": outcome,
        "evidence_sufficiency": sufficiency,
        "gold_pages": list(gold),
        "retrieved": retrieved,
        "cited_pages": list(cited) if completed else None,
        "validation_failures": list(failures) if completed else None,
        "result": {"limitations": list(limitations)} if completed else None,
        **meta,
    }


def run_a(**meta) -> list[dict]:
    """Six questions with every outcome present. The expected counts are worked out by hand."""
    return [
        record("F001", "ANSWERABLE", sufficiency="sufficient", gold=["12"], cited=["12"], **meta),
        record("F002", "ANSWERABLE", sufficiency="insufficient", gold=["40"],
               retrieved=[{"rank": 1, "pages": ["3"]}], **meta),
        record("F003", "ANSWERABLE", outcome="provider_error", gold=["7"], retrieved=None, **meta),
        record("F004", "PARTIAL", sufficiency="partial", gold=["9"], cited=["9"],
               limitations=["FIXTURE limit"], **meta),
        record("F005", "UNANSWERABLE", sufficiency="insufficient", **meta),
        record("F006", "ADVERSARIAL", sufficiency="sufficient", cited=["3"],
               failures=["ungrounded_answer: FIXTURE detail"], **meta),
    ]


def write_run(path, records) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


EXPECTED_MARKDOWN = """\
*Run `eval_20260101T000000Z`: model `fixture-model` (fixture-provider), prompt sha256 `abcdef012345`, top-k 5, 6 questions. Counts are n/N over the stated population.*

| Metric | Population | eval_20260101T000000Z |
|---|---|---|
| Answered (`sufficient` or `partial`) | all questions | 3/6 |
| Refused (`insufficient`) | all questions | 2/6 |
| Malformed output | all questions | 0/6 |
| Provider error | all questions | 1/6 |
| Answers passing every validation check | all questions | 2/6 |
| Refusal correctness | UNANSWERABLE + ADVERSARIAL | 1/2 |
| False refusal (case B) | ANSWERABLE | 1/3 |
| Retrieval recall@k | ANSWERABLE | 1/3 |
| Retrieval not measured | ANSWERABLE | 1/3 |
| Gold retrieved below rank 5 | ANSWERABLE | 0/3 |
| Citation hit | ANSWERABLE | 1/3 |
| Partial discipline | PARTIAL | 1/1 |
| Any contract violation | all questions | 1/6 |
| Wrote a page number | all questions | n/a |
| Wrote a page number the thesis does not print (fabricated citation) | all questions | n/a |
"""

EXPECTED_LATEX = r"""% Run eval_20260101T000000Z: model fixture-model (fixture-provider), prompt sha256 abcdef012345, top-k 5, 6 questions. Counts are n/N over the stated population.
\begin{tabular}{llr}
\toprule
Metric & Population & eval\_20260101T000000Z \\
\midrule
Answered (\texttt{sufficient} or \texttt{partial}) & all questions & 3/6 \\
Refused (\texttt{insufficient}) & all questions & 2/6 \\
Malformed output & all questions & 0/6 \\
Provider error & all questions & 1/6 \\
Answers passing every validation check & all questions & 2/6 \\
Refusal correctness & UNANSWERABLE + ADVERSARIAL & 1/2 \\
False refusal (case B) & ANSWERABLE & 1/3 \\
Retrieval recall@k & ANSWERABLE & 1/3 \\
Retrieval not measured & ANSWERABLE & 1/3 \\
Gold retrieved below rank 5 & ANSWERABLE & 0/3 \\
Citation hit & ANSWERABLE & 1/3 \\
Partial discipline & PARTIAL & 1/1 \\
Any contract violation & all questions & 1/6 \\
Wrote a page number & all questions & n/a \\
Wrote a page number the thesis does not print (fabricated citation) & all questions & n/a \\
\bottomrule
\end{tabular}
"""


# --- one run ---------------------------------------------------------------------


def test_one_run_gives_the_expected_markdown_table(tmp_path):
    path = tmp_path / "eval_20260101T000000Z.jsonl"
    write_run(path, run_a())

    assert results_tables.markdown_table([results_tables.load_run(path)]) == EXPECTED_MARKDOWN


def test_one_run_gives_the_expected_booktabs_fragment(tmp_path):
    path = tmp_path / "eval_20260101T000000Z.jsonl"
    write_run(path, run_a())

    assert results_tables.latex_table([results_tables.load_run(path)]) == EXPECTED_LATEX


def test_every_figure_is_a_count_and_nothing_is_called_accuracy_or_scored(tmp_path):
    path = tmp_path / "eval_a.jsonl"
    write_run(path, run_a())
    runs = [results_tables.load_run(path)]
    both = results_tables.markdown_table(runs) + results_tables.latex_table(runs)

    for word in ("accuracy", "score", "similarity", "%"):
        assert word not in both.lower().replace("% run", "")
    cells = [line.split("|")[3].strip() for line in EXPECTED_MARKDOWN.splitlines()[4:]]
    assert all(cell == "n/a" or (cell.replace("/", "").isdigit() and "/" in cell) for cell in cells)


def test_an_empty_population_is_shown_as_zero_of_zero_not_left_out(tmp_path):
    path = tmp_path / "eval_a.jsonl"
    write_run(path, [record("F001", "ANSWERABLE", sufficiency="sufficient", gold=["12"], cited=["12"])])
    table = results_tables.markdown_table([results_tables.load_run(path)])

    assert "| Partial discipline | PARTIAL | 0/0 |" in table
    assert "| Refusal correctness | UNANSWERABLE + ADVERSARIAL | 0/0 |" in table


# --- several runs ------------------------------------------------------------------


def test_several_runs_get_one_column_each_and_a_caption_naming_every_run(tmp_path):
    first, second = tmp_path / "eval_a.jsonl", tmp_path / "eval_b.jsonl"
    write_run(first, run_a())
    later = run_a(run_id="eval_20260102T000000Z", top_k=10)
    later[1]["evidence_sufficiency"] = "sufficient"      # F002 answered this time
    later[1]["cited_pages"] = ["3"]
    write_run(second, later)

    runs = [results_tables.load_run(first), results_tables.load_run(second)]
    table = results_tables.markdown_table(runs)
    lines = table.splitlines()

    assert lines[0] == (
        "*Run `eval_20260101T000000Z`: model `fixture-model` (fixture-provider), prompt sha256 "
        "`abcdef012345`, top-k 5, 6 questions. Run `eval_20260102T000000Z`: model `fixture-model` "
        "(fixture-provider), prompt sha256 `abcdef012345`, top-k 10, 6 questions. "
        "Counts are n/N over the stated population.*"
    )
    assert lines[2] == "| Metric | Population | eval_20260101T000000Z | eval_20260102T000000Z |"
    assert "| False refusal (case B) | ANSWERABLE | 1/3 | 0/3 |" in table
    assert "| Answered (`sufficient` or `partial`) | all questions | 3/6 | 4/6 |" in table
    assert r"\begin{tabular}{llrr}" in results_tables.latex_table(runs)


def test_runs_over_different_question_files_are_not_put_side_by_side(tmp_path):
    first, second = tmp_path / "eval_a.jsonl", tmp_path / "eval_b.jsonl"
    write_run(first, run_a())
    write_run(second, run_a(run_id="eval_20260102T000000Z", questions_sha256="z" * 64))

    with pytest.raises(TableError) as refused:
        results_tables.check_comparable(
            [results_tables.load_run(first), results_tables.load_run(second)]
        )

    assert str(refused.value) == (
        "These runs used different question files (eval_20260101T000000Z, eval_20260102T000000Z), "
        "so their counts are not comparable. Tabulate them separately."
    )


# --- files that cannot be trusted -----------------------------------------------------


def test_a_file_mixing_two_runs_is_refused(tmp_path):
    path = tmp_path / "eval_mixed.jsonl"
    write_run(path, run_a()[:3] + run_a(run_id="eval_20260102T000000Z")[3:])

    with pytest.raises(TableError) as refused:
        results_tables.load_run(path)

    assert str(refused.value) == "eval_mixed.jsonl holds records from 2 different values of run_id."


@pytest.mark.parametrize("field", ["model", "top_k", "prompt_sha256_12"])
def test_a_file_whose_records_disagree_on_how_they_were_produced_is_refused(tmp_path, field):
    path = tmp_path / "eval_a.jsonl"
    records = run_a()
    records[2][field] = "FIXTURE-different"
    write_run(path, records)

    with pytest.raises(TableError) as refused:
        results_tables.load_run(path)

    assert str(refused.value) == f"eval_a.jsonl holds records from 2 different values of {field}."


def test_a_broken_line_is_an_error_with_its_line_number_not_a_skipped_record(tmp_path):
    path = tmp_path / "eval_a.jsonl"
    good = "".join(json.dumps(r) + "\n" for r in run_a()[:2])
    path.write_text(good + '{"run_id": "eval_x", "question_id"\n', encoding="utf-8")

    with pytest.raises(TableError) as refused:
        results_tables.load_run(path)

    assert str(refused.value) == "eval_a.jsonl line 3 is not valid JSON. No record is skipped silently."


def test_an_empty_file_is_refused(tmp_path):
    path = tmp_path / "eval_a.jsonl"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(TableError) as refused:
        results_tables.load_run(path)

    assert str(refused.value) == "eval_a.jsonl holds no records."


# --- LaTeX escaping --------------------------------------------------------------------


def test_latex_special_characters_in_run_names_are_escaped(tmp_path):
    path = tmp_path / "eval_a.jsonl"
    write_run(path, run_a(run_id="eval_50%_r&d#1"))
    fragment = results_tables.latex_table([results_tables.load_run(path)])

    assert r"eval\_50\%\_r\&d\#1" in fragment
    assert fragment.count(r"\\") == 16          # header row + 15 metric rows, none broken


# --- command line ------------------------------------------------------------------------


def test_main_writes_both_files_beside_the_run_and_prints_where(tmp_path, capsys):
    path = tmp_path / "eval_20260101T000000Z.jsonl"
    write_run(path, run_a())

    assert results_tables.main([str(path)]) == 0

    markdown = tmp_path / "results_eval_20260101T000000Z.md"
    latex = tmp_path / "results_eval_20260101T000000Z.tex"
    assert markdown.read_text(encoding="utf-8") == EXPECTED_MARKDOWN
    assert latex.read_text(encoding="utf-8") == EXPECTED_LATEX
    out = capsys.readouterr().out
    assert str(markdown) in out and str(latex) in out


def test_main_names_a_comparison_after_how_many_runs_it_holds(tmp_path):
    first, second = tmp_path / "eval_a.jsonl", tmp_path / "eval_b.jsonl"
    write_run(first, run_a())
    write_run(second, run_a(run_id="eval_20260102T000000Z"))

    assert results_tables.main([str(first), str(second), "--out-dir", str(tmp_path / "tables")]) == 0
    assert (tmp_path / "tables" / "results_eval_20260101T000000Z_and_1_more.md").exists()
    assert (tmp_path / "tables" / "results_eval_20260101T000000Z_and_1_more.tex").exists()


def test_main_refuses_with_a_message_and_writes_nothing(tmp_path, capsys):
    first, second = tmp_path / "eval_a.jsonl", tmp_path / "eval_b.jsonl"
    write_run(first, run_a())
    write_run(second, run_a(run_id="eval_20260102T000000Z", questions_sha256="z" * 64))

    assert results_tables.main([str(first), str(second)]) == 2
    assert "different question files" in capsys.readouterr().err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["eval_a.jsonl", "eval_b.jsonl"]


def test_main_never_writes_into_the_repository_docs_or_readme(tmp_path):
    """Numbers go beside the run file, under runs/, and nowhere else."""
    path = tmp_path / "eval_a.jsonl"
    write_run(path, run_a())
    results_tables.main([str(path)])

    written = sorted(p.name for p in tmp_path.iterdir())
    assert written == ["eval_a.jsonl", "results_eval_20260101T000000Z.md", "results_eval_20260101T000000Z.tex"]


# --- conditions: an ordinary run beside its no-retrieval baseline (PLAN_V5) --------------


def baseline_of(records):
    """The same questions as a baseline run would record them: nothing retrieved, nothing cited."""
    out = []
    for r in records:
        b = dict(r, condition="baseline_no_rag", run_id="eval_20260101T000000Z_baseline-no-rag",
                 retrieved=None, cited_pages=None)
        if b["outcome"] == "completed":
            b["evidence_sufficiency"] = "insufficient"
            b["validation_failures"] = []
            b["page_claims"] = []
        else:
            b["page_claims"] = None
        out.append(b)
    out[0]["evidence_sufficiency"] = "sufficient"
    out[0]["page_claims"] = [{"label": "12", "exists": True}, {"label": "300", "exists": False}]
    return out


def with_claims(records):
    return [dict(r, condition="rag", page_claims=[] if r["outcome"] == "completed" else None) for r in records]


def test_a_baseline_run_is_labelled_and_its_retrieval_rows_are_not_applicable(tmp_path):
    rag, baseline = tmp_path / "eval_a.jsonl", tmp_path / "eval_b.jsonl"
    write_run(rag, with_claims(run_a()))
    write_run(baseline, baseline_of(run_a()))
    runs = [results_tables.load_run(rag), results_tables.load_run(baseline)]
    table = results_tables.markdown_table(runs)

    assert "| Metric | Population | eval_20260101T000000Z | eval_20260101T000000Z_baseline-no-rag (baseline, no retrieval) |" in table
    assert "Run `eval_20260101T000000Z_baseline-no-rag` (baseline, no retrieval): model" in table
    assert "| Retrieval recall@k | ANSWERABLE | 1/3 | n/a |" in table
    assert "| Retrieval not measured | ANSWERABLE | 1/3 | n/a |" in table
    assert "| Gold retrieved below rank 5 | ANSWERABLE | 0/3 | n/a |" in table
    assert "| Citation hit | ANSWERABLE | 1/3 | n/a |" in table
    assert "| Refused (`insufficient`) | all questions | 2/6 | 4/6 |" in table
    assert "| Wrote a page number | all questions | 0/6 | 1/6 |" in table
    assert "| Wrote a page number the thesis does not print (fabricated citation) | all questions | 0/6 | 1/6 |" in table
    latex = results_tables.latex_table(runs)
    assert r"eval\_20260101T000000Z\_baseline-no-rag (baseline, no retrieval)" in latex
    assert "Citation hit & ANSWERABLE & 1/3 & n/a" in latex


def test_an_ordinary_run_is_never_labelled_a_baseline(tmp_path):
    path = tmp_path / "eval_a.jsonl"
    write_run(path, with_claims(run_a()))
    table = results_tables.markdown_table([results_tables.load_run(path)])

    assert "baseline" not in table
    assert "| Wrote a page number | all questions | 0/6 |" in table


def test_a_file_mixing_the_two_conditions_is_refused(tmp_path):
    path = tmp_path / "eval_mixed.jsonl"
    write_run(path, with_claims(run_a())[:3] + [dict(r, run_id="eval_20260101T000000Z") for r in baseline_of(run_a())[3:]])

    with pytest.raises(TableError) as refused:
        results_tables.load_run(path)

    assert str(refused.value) == "eval_mixed.jsonl holds records from 2 different values of condition."
