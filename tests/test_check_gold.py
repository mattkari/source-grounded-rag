"""The gold checker — `scripts/check_gold.py` (Jira LAB-45).

Rule tests run against a synthetic page map shaped like the real one. Two tests
at the end read the committed question file and the canonical page labels, so
CI re-checks the researcher's gold labels on every push.
"""

from __future__ import annotations

import json

import pytest
import yaml

from scripts import check_gold
from scripts.check_gold import FAIL, NOT_WRITTEN, PASS


def entry(qid="F001", expected_type="ANSWERABLE", gold=("3",), question="FIXTURE: a synthetic question?", **extra):
    base = {
        "id": qid,
        "batch": "FIXTURE",
        "question": question,
        "expected_type": expected_type,
        "gold_pages": list(gold),
        "expected_answer_summary": "FIXTURE summary",
        "notes": "",
    }
    base.update(extra)
    return base


@pytest.fixture
def check(tmp_path, pages_path):
    """Write the given entries as a question file and check them."""

    def run(*entries):
        path = tmp_path / "questions.yaml"
        path.write_text(yaml.safe_dump({"questions": list(entries)}, sort_keys=False), encoding="utf-8")
        return check_gold.check(path, pages_path)

    return run


def only_problem(report) -> str:
    assert [row.status for row in report.rows] == [FAIL]
    assert len(report.rows[0].problems) == 1
    return report.rows[0].problems[0]


# --- passing and unwritten -------------------------------------------------------


def test_a_written_answerable_question_with_a_printed_label_passes(check):
    report = check(entry(gold=["3", "12"]))

    assert report.ok
    assert [row.status for row in report.rows] == [PASS]
    assert report.questions == [
        {
            "id": "F001",
            "batch": "FIXTURE",
            "question": "FIXTURE: a synthetic question?",
            "expected_type": "ANSWERABLE",
            "gold_pages": ["3", "12"],
        }
    ]


@pytest.mark.parametrize("blank", ["", "   \n"])
def test_an_empty_slot_is_not_written_yet_and_not_an_error(check, blank):
    report = check(entry(question=blank, gold=[]))

    assert report.ok
    assert [row.status for row in report.rows] == [NOT_WRITTEN]
    assert report.failed == []
    assert report.questions == []


def test_unwritten_slots_are_never_handed_to_the_runner(check):
    report = check(entry("F001"), entry("F002", question="", gold=[]), entry("F003", "UNANSWERABLE", gold=[]))
    assert [q["id"] for q in report.questions] == ["F001", "F003"]


# --- gold pages per category ------------------------------------------------------


@pytest.mark.parametrize("expected_type", ["ANSWERABLE", "PARTIAL"])
def test_answerable_and_partial_need_a_gold_page(check, expected_type):
    assert only_problem(check(entry(expected_type=expected_type, gold=[]))) == (
        f"{expected_type} needs at least one gold page: add the printed label of a page that "
        "answers it, or change expected_type"
    )


@pytest.mark.parametrize("expected_type", ["UNANSWERABLE", "ADVERSARIAL"])
def test_unanswerable_and_adversarial_must_have_no_gold_page(check, expected_type):
    assert only_problem(check(entry(expected_type=expected_type, gold=["3"]))) == (
        f"{expected_type} must have no gold pages: remove them, or change expected_type "
        "if the thesis does answer the question"
    )


@pytest.mark.parametrize("expected_type", ["UNANSWERABLE", "ADVERSARIAL"])
def test_unanswerable_and_adversarial_pass_without_gold(check, expected_type):
    assert check(entry(expected_type=expected_type, gold=[])).ok


# --- each gold page must be a printed label -----------------------------------------


def test_an_unquoted_page_number_is_rejected(check):
    assert only_problem(check(entry(gold=[3]))) == (
        'gold page #1 is not a string: quote the printed label, e.g. "143"'
    )


def test_a_null_gold_page_is_rejected(check):
    assert only_problem(check(entry(gold=[None]))) == (
'gold page #1 is null: look up the printed page and quote its label, e.g. "143"'
    )


def test_a_label_no_page_carries_is_rejected_with_where_to_look(check):
    assert only_problem(check(entry(gold=["999"]))) == (
        "gold page 999 is not printed on any page: check the number printed on the page itself "
        "(body pages are 1-258; PDF viewer page = printed + 23)"
    )


def test_a_body_page_whose_number_did_not_print_says_what_to_do_instead(check):
    # Fixture page 5 sits on pdf page 28, which carries no printed number.
    assert only_problem(check(entry(gold=["5"]))) == (
        "gold page 5 cannot be used: PDF page 28 carries no printed number, so the system "
        "cannot cite it: choose a neighbouring page or another question"
    )


@pytest.mark.parametrize("label, front, appendix", [("i", 2, 282), ("ii", 3, 283)])
def test_a_repeated_roman_label_is_rejected_and_says_where_it_repeats(check, label, front, appendix):
    assert only_problem(check(entry(gold=[label]))) == (
        f"gold page {label} is ambiguous: that label appears in both the front matter "
        f"(PDF page {front}) and the appendix (PDF page {appendix}), so a citation of it cannot "
        "say which: choose a body page (1-258) or another question"
    )


@pytest.mark.parametrize("label", ["43", "44"])
def test_the_real_unnumbered_pages_get_the_instruction_the_researcher_needs(tmp_path, label):
    """Against the committed page labels: printed 43 and 44 do not exist."""
    path = tmp_path / "questions.yaml"
    path.write_text(yaml.safe_dump({"questions": [entry(gold=[label])]}), encoding="utf-8")

    assert only_problem(check_gold.check(path, check_gold.DEFAULT_PAGES)) == (
        f"gold page {label} cannot be used: PDF pages 66 and 67 carry no printed number, so the "
        "system cannot cite them: choose a neighbouring page or another question"
    )


def test_a_real_repeated_roman_label_names_front_matter_and_appendix(tmp_path):
    path = tmp_path / "questions.yaml"
    path.write_text(yaml.safe_dump({"questions": [entry(gold=["iv"])]}), encoding="utf-8")

    assert only_problem(check_gold.check(path, check_gold.DEFAULT_PAGES)) == (
        "gold page iv is ambiguous: that label appears in both the front matter (PDF page 5) "
        "and the appendix (PDF page 285), so a citation of it cannot say which: "
        "choose a body page (1-258) or another question"
    )


def test_a_roman_label_printed_once_is_accepted(check):
    assert check(entry(gold=["viii"])).ok


def test_a_gold_page_listed_twice_is_rejected(check):
    assert only_problem(check(entry(gold=["3", "3"]))) == "gold page 3 is listed twice: remove the repeat"


def test_one_bad_label_fails_the_question_but_good_labels_are_still_shown(check):
    report = check(entry(gold=["3", "999"]))
    assert report.rows[0].status == FAIL
    assert report.rows[0].gold == ["3"]
    assert report.questions == []


# --- schema -------------------------------------------------------------------------


def test_duplicate_ids_are_rejected(check):
    report = check(entry("F001"), entry("F001"))

    assert not report.ok
    assert [row.status for row in report.rows] == [PASS, FAIL]
    assert report.rows[1].problems == ["duplicate id: give this question an id no other slot uses"]


def test_a_duplicate_id_is_an_error_even_on_an_empty_slot(check):
    report = check(entry("F001"), entry("F001", question="", gold=[]))
    assert [row.status for row in report.rows] == [PASS, FAIL]


def test_an_unknown_expected_type_is_rejected(check):
    problem = only_problem(check(entry(expected_type="MAYBE", gold=[])))
    assert problem == (
        "expected_type must be one of ANSWERABLE, PARTIAL, UNANSWERABLE, ADVERSARIAL (found: MAYBE): "
        "pick one of the four"
    )


def test_a_missing_field_is_rejected(check):
    incomplete = entry()
    del incomplete["notes"]
    assert only_problem(check(incomplete)) == (
        'missing field(s): notes: add them back (use "" or [] when empty)'
    )


def test_a_field_outside_the_schema_is_rejected(check):
    assert only_problem(check(entry(gold_passage="FIXTURE pasted text"))) == (
        "1 field(s) not in the schema: remove them (allowed: id, batch, question, expected_type, "
        "gold_pages, expected_answer_summary, notes)"
    )


def test_gold_pages_must_be_a_list(check):
    assert only_problem(check(entry(gold_pages="3"))) == (
        'gold_pages must be a list: write it as ["143", "148"], or [] for none'
    )


def test_a_file_without_a_questions_list_is_a_file_problem(tmp_path, pages_path):
    path = tmp_path / "questions.yaml"
    path.write_text("metadata: {template_version: 1}\n", encoding="utf-8")
    report = check_gold.check(path, pages_path)

    assert not report.ok
    assert report.file_problems == [
        "question file needs a top-level `questions` list: restore it from the template"
    ]


def test_every_failure_tells_the_researcher_what_to_do(check):
    """Each problem is `what is wrong: what to do` and each gets its own line."""
    report = check(
        entry("F001", gold=[]),
        entry("F002", "UNANSWERABLE", gold=["3"]),
        entry("F003", gold=[None, 7, "999", "5", "i", "3", "3", "not a label at all"]),
        entry("F003", expected_type="MAYBE", gold_pages="3", extra_field=1),
        entry("bad id!"),
    )
    problems = [problem for row in report.rows for problem in row.problems]

    assert len(problems) == 14
    for problem in problems:
        what, _, action = problem.partition(": ")
        assert what and len(action.split()) >= 3, problem

    table = check_gold.format_table(report)
    for problem in problems:
        assert f"\n    -> {problem}\n" in table


# --- counts against the target --------------------------------------------------------


def test_counts_per_category_are_reported_against_the_target(check):
    report = check(
        entry("F001"),
        entry("F002"),
        entry("F003", question="", gold=[]),
        entry("F004", "PARTIAL", gold=[]),            # written but fails
        entry("F005", "UNANSWERABLE", gold=[]),
        entry("F006", "ADVERSARIAL", question="", gold=[]),
    )
    assert report.category_counts() == {
        "ANSWERABLE": {"pass": 2, "fail": 0, "not_written": 1, "target": 15},
        "PARTIAL": {"pass": 0, "fail": 1, "not_written": 0, "target": 5},
        "UNANSWERABLE": {"pass": 1, "fail": 0, "not_written": 0, "target": 7},
        "ADVERSARIAL": {"pass": 0, "fail": 0, "not_written": 1, "target": 3},
    }

    table = check_gold.format_table(report)
    assert "2/15 written, 13 to go" in table
    assert "1/5 written, 4 to go" in table
    assert "RESULT: FAIL — 3 passed, 1 failed, 2 not written yet" in table


# --- the table never carries text ------------------------------------------------------


def test_the_table_never_prints_question_summary_notes_or_pasted_text(check):
    report = check(
        entry("F001", question="FIXTURE: SECRET-QUESTION?", expected_answer_summary="SECRET-SUMMARY",
              notes="SECRET-NOTES"),
        entry("F002", gold=["SECRET passage pasted into the wrong field"]),
        entry("SECRET id with spaces"),
        entry("F004", expected_type="SECRET pasted type", gold=[]),
        entry("F005", **{"SECRET-FIELD": "SECRET-VALUE"}),
    )
    table = check_gold.format_table(report)

    assert "SECRET" not in table
    assert "FIXTURE summary" not in table
    assert "gold page #1 is not a page label (42 characters, not echoed): replace it" in table
    assert "slot #3" in table


def test_a_yaml_error_reports_the_position_and_never_quotes_the_file(tmp_path, pages_path):
    path = tmp_path / "questions.yaml"
    path.write_text('questions:\n  - id: F001\n    question: "SECRET unterminated\n', encoding="utf-8")
    report = check_gold.check(path, pages_path)
    table = check_gold.format_table(report)

    assert not report.ok
    assert "question file is not valid YAML at line" in table
    assert "SECRET" not in table


def test_page_text_is_never_loaded_into_the_page_map(pages_path):
    page_map = check_gold.load_page_map(pages_path)
    assert "FIXTURE page text" not in repr(page_map)


# --- the page map itself is checked against the layout profile ---------------------------


def test_a_page_map_that_breaks_the_printed_plus_23_rule_is_a_file_problem(tmp_path, check, pages_path):
    rows = [json.loads(line) for line in pages_path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        if row["printed_page"] == "3":
            row["printed_page"] = "4"   # label 4 now also on pdf page 26, where 3 belongs
    pages_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    report = check(entry(gold=["12"]))

    assert not report.ok
    assert report.file_problems == [
        "page map: printed label 4 is on pdf page 26, expected 27: the extraction no longer matches "
        "the layout profile in config.py — re-check the ingest before trusting any gold label"
    ]


# --- command line -------------------------------------------------------------------------


def test_main_exits_zero_and_prints_the_table_when_nothing_failed(tmp_path, pages_path, capsys):
    path = tmp_path / "questions.yaml"
    path.write_text(yaml.safe_dump({"questions": [entry(), entry("F002", question="", gold=[])]}), encoding="utf-8")

    assert check_gold.main(["--questions", str(path), "--pages", str(pages_path)]) == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS — 1 passed, 0 failed, 1 not written yet" in out
    assert "FIXTURE: a synthetic question?" not in out


def test_main_exits_one_when_a_written_question_fails(tmp_path, pages_path, capsys):
    path = tmp_path / "questions.yaml"
    path.write_text(yaml.safe_dump({"questions": [entry(gold=[])]}), encoding="utf-8")

    assert check_gold.main(["--questions", str(path), "--pages", str(pages_path)]) == 1
    assert "RESULT: FAIL — 0 passed, 1 failed, 0 not written yet" in capsys.readouterr().out


# --- the committed files ---------------------------------------------------------------------


def test_the_canonical_page_map_matches_the_layout_profile():
    page_map = check_gold.load_page_map(check_gold.DEFAULT_PAGES)

    assert page_map.problems == ()
    # Front-matter labels reused by the appendix can never identify one page.
    assert sorted(page_map.ambiguous()) == ["i", "ii", "iii", "iv", "v", "vi", "vii"]
    # PDF pages 66 and 67 carry no printed number.
    assert "43" not in page_map.label_to_pdf and "44" not in page_map.label_to_pdf
    assert page_map.label_to_pdf["1"] == (24,) and page_map.label_to_pdf["258"] == (281,)


def test_the_committed_question_file_passes_the_gold_check():
    report = check_gold.check()
    assert report.ok, check_gold.format_table(report)
    assert len(report.rows) >= 30
