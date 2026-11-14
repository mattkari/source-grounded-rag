"""Validate the E1 gold question file before any run is trusted (Jira LAB-45).

    python scripts/check_gold.py
    python scripts/check_gold.py --questions evaluation/questions_v1.yaml

Prints a pass/fail table and exits 0 when nothing failed, 1 otherwise.

What this script will never print: the question text, the answer summary, the
notes, or any text from the thesis. The table carries ids, categories, page
labels and fixed reason strings only, and a value that does not look like an
id or a page label is described, not echoed — so a passage pasted into the
wrong field cannot leak into a terminal log or a CI transcript.

A slot whose `question` is blank is "not written yet". That is the normal state
of the template and is reported, never counted as an error.

Every FAIL says what to do about it, not only what is wrong.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # so `python scripts/check_gold.py` finds config.py
    sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402

DEFAULT_QUESTIONS = ROOT / "evaluation" / "questions_v1.yaml"
DEFAULT_PAGES = settings.canonical_dir / "pages.jsonl"

FIELDS = (
    "id",
    "batch",
    "question",
    "expected_type",
    "gold_pages",
    "expected_answer_summary",
    "notes",
)
EXPECTED_TYPES = ("ANSWERABLE", "PARTIAL", "UNANSWERABLE", "ADVERSARIAL")
NEEDS_GOLD = frozenset({"ANSWERABLE", "PARTIAL"})
TARGETS = {"ANSWERABLE": 15, "PARTIAL": 5, "UNANSWERABLE": 7, "ADVERSARIAL": 3}

PASS, FAIL, NOT_WRITTEN = "PASS", "FAIL", "not written yet"

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,16}")
_LABEL_RE = re.compile(r"[0-9ivxlcdm]{1,8}", re.IGNORECASE)
_TYPE_RE = re.compile(r"[A-Za-z_]{1,20}")


# ---------------------------------------------------------------------------
# Printed-page map, read from the canonical extraction (labels only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PageMap:
    label_to_pdf: dict[str, tuple[int, ...]]   # printed label -> PDF pages carrying it
    pdf_to_label: dict[int, str | None]        # PDF page -> printed label, if any
    pdf_to_region: dict[int, str]              # PDF page -> "front matter" | "body" | "appendix" | "back matter"
    problems: tuple[str, ...]                  # the extraction disagrees with the layout profile

    def ambiguous(self) -> list[str]:
        return [label for label, pdf in self.label_to_pdf.items() if len(pdf) > 1]

    def unnumbered_run(self, pdf_page: int) -> list[int]:
        """The consecutive PDF pages around `pdf_page` that carry no printed
        number. Empty when `pdf_page` has one, or is not in the document."""
        if pdf_page not in self.pdf_to_label or self.pdf_to_label[pdf_page] is not None:
            return []
        first = last = pdf_page
        while first - 1 in self.pdf_to_label and self.pdf_to_label[first - 1] is None:
            first -= 1
        while last + 1 in self.pdf_to_label and self.pdf_to_label[last + 1] is None:
            last += 1
        return list(range(first, last + 1))


def load_page_map(path: Path) -> PageMap:
    """Read `pdf_page`, `printed_page` and the running header from each row.

    The page text is never kept, and the header is used only to tell an
    appendix from other back matter — it is not stored or printed.
    """
    label_to_pdf: dict[str, list[int]] = {}
    pdf_to_label: dict[int, str | None] = {}
    pdf_to_region: dict[int, str] = {}
    problems: list[str] = []
    body_first_pdf = settings.body_first_printed_page + settings.body_pdf_page_offset
    body_last_pdf = settings.body_last_printed_page + settings.body_pdf_page_offset

    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            pdf_page, label = row["pdf_page"], row["printed_page"]
            pdf_to_label[pdf_page] = label
            if pdf_page < body_first_pdf:
                pdf_to_region[pdf_page] = "front matter"
            elif pdf_page <= body_last_pdf:
                pdf_to_region[pdf_page] = "body"
            elif str(row.get("running_header") or "").strip().lower().startswith("appendix"):
                pdf_to_region[pdf_page] = "appendix"
            else:
                pdf_to_region[pdf_page] = "back matter"
            if label is None:
                continue
            if not isinstance(label, str):
                problems.append(f"pdf page {pdf_page}: printed label is not a string")
                continue
            label_to_pdf.setdefault(label, []).append(pdf_page)

    first, last = settings.body_first_printed_page, settings.body_last_printed_page
    offset = settings.body_pdf_page_offset
    for label, pdf_pages in label_to_pdf.items():
        if not label.isdecimal():
            continue
        number = int(label)
        if not first <= number <= last:
            problems.append(f"printed label {label} is outside the body range {first}-{last}")
        for pdf_page in pdf_pages:
            if pdf_page != number + offset:
                problems.append(
                    f"printed label {label} is on pdf page {pdf_page}, expected {number + offset}"
                )

    return PageMap(
        label_to_pdf={label: tuple(pdf) for label, pdf in label_to_pdf.items()},
        pdf_to_label=pdf_to_label,
        pdf_to_region=pdf_to_region,
        problems=tuple(problems),
    )


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------


@dataclass
class Row:
    slot: int                  # 1-based position in the file
    id: str                    # safe to print
    expected_type: str         # safe to print
    status: str                # PASS | FAIL | "not written yet"
    gold: list[str] = field(default_factory=list)      # valid labels only, safe to print
    problems: list[str] = field(default_factory=list)  # fixed reason strings


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    file_problems: list[str] = field(default_factory=list)
    # Written questions that passed every check, in file order. This is the only
    # thing the runner may execute.
    questions: list[dict] = field(default_factory=list)
    page_map: PageMap | None = None

    @property
    def failed(self) -> list[Row]:
        return [row for row in self.rows if row.status == FAIL]

    @property
    def not_written(self) -> list[Row]:
        return [row for row in self.rows if row.status == NOT_WRITTEN]

    @property
    def ok(self) -> bool:
        return not self.file_problems and not self.failed

    def category_counts(self) -> dict[str, dict[str, int]]:
        counts = {
            name: {"pass": 0, "fail": 0, "not_written": 0, "target": TARGETS[name]}
            for name in EXPECTED_TYPES
        }
        for row in self.rows:
            if row.expected_type not in counts:
                continue
            key = {PASS: "pass", FAIL: "fail", NOT_WRITTEN: "not_written"}[row.status]
            counts[row.expected_type][key] += 1
        return counts


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _pages_phrase(pdf_pages: list[int]) -> str:
    """"PDF page 28 carries" / "PDF pages 66 and 67 carry" — ready for "... no printed number"."""
    if len(pdf_pages) == 1:
        return f"PDF page {pdf_pages[0]} carries"
    listed = ", ".join(str(p) for p in pdf_pages[:-1]) + f" and {pdf_pages[-1]}"
    return f"PDF pages {listed} carry"


def _missing_label_problem(label: str, pages: PageMap) -> str:
    first, last = settings.body_first_printed_page, settings.body_last_printed_page
    offset = settings.body_pdf_page_offset
    if label.isdecimal() and first <= int(label) <= last:
        run = pages.unnumbered_run(int(label) + offset)
        if run:
            return (
                f"gold page {label} cannot be used: {_pages_phrase(run)} no printed number, "
                f"so the system cannot cite {'it' if len(run) == 1 else 'them'}: "
                "choose a neighbouring page or another question"
            )
    return (
        f"gold page {label} is not printed on any page: check the number printed on the page "
        f"itself (body pages are {first}-{last}; PDF viewer page = printed + {offset})"
    )


def _ambiguous_label_problem(label: str, pages: PageMap) -> str:
    places = [
        f"the {pages.pdf_to_region.get(pdf_page, 'document')} (PDF page {pdf_page})"
        for pdf_page in pages.label_to_pdf[label]
    ]
    first, last = settings.body_first_printed_page, settings.body_last_printed_page
    return (
        f"gold page {label} is ambiguous: that label appears in both "
        + " and ".join(places)
        + f", so a citation of it cannot say which: choose a body page ({first}-{last}) or another question"
    )


def _gold_problems(gold: object, expected_type: str, pages: PageMap) -> tuple[list[str], list[str]]:
    """Return (valid labels, problems) for one written question."""
    if not isinstance(gold, list):
        return [], ['gold_pages must be a list: write it as ["143", "148"], or [] for none']

    problems: list[str] = []
    valid: list[str] = []

    for position, label in enumerate(gold, start=1):
        where = f"gold page #{position}"
        if label is None:
            problems.append(f'{where} is null: look up the printed page and quote its label, e.g. "143"')
        elif isinstance(label, bool) or not isinstance(label, str):
            problems.append(f'{where} is not a string: quote the printed label, e.g. "143"')
        elif not _LABEL_RE.fullmatch(label):
            problems.append(
                f"{where} is not a page label ({len(label)} characters, not echoed): "
                "replace it with the printed page label only"
            )
        elif label in valid:
            problems.append(f"gold page {label} is listed twice: remove the repeat")
        elif label not in pages.label_to_pdf:
            problems.append(_missing_label_problem(label, pages))
        elif len(pages.label_to_pdf[label]) > 1:
            problems.append(_ambiguous_label_problem(label, pages))
        else:
            valid.append(label)

    if expected_type in NEEDS_GOLD and not gold:
        problems.append(
            f"{expected_type} needs at least one gold page: add the printed label of a page that "
            "answers it, or change expected_type"
        )
    if expected_type in EXPECTED_TYPES and expected_type not in NEEDS_GOLD and gold:
        problems.append(
            f"{expected_type} must have no gold pages: remove them, or change expected_type "
            "if the thesis does answer the question"
        )
    return valid, problems


def _check_entry(entry: object, slot: int, seen_ids: set[str], pages: PageMap) -> tuple[Row, dict | None]:
    if not isinstance(entry, dict):
        return Row(slot, f"slot #{slot}", "?", FAIL,
                   problems=["entry is not a mapping: copy the shape of an empty template slot"]), None

    problems: list[str] = []

    missing = [name for name in FIELDS if name not in entry]
    if missing:
        problems.append(
            "missing field(s): " + ", ".join(missing) + ': add them back (use "" or [] when empty)'
        )
    unknown = sorted(str(key) for key in entry if key not in FIELDS)
    if unknown:
        problems.append(
            f"{len(unknown)} field(s) not in the schema: remove them (allowed: {', '.join(FIELDS)})"
        )

    raw_id = entry.get("id")
    if isinstance(raw_id, str) and _ID_RE.fullmatch(raw_id):
        shown_id = raw_id
        if raw_id in seen_ids:
            problems.append("duplicate id: give this question an id no other slot uses")
        seen_ids.add(raw_id)
    else:
        shown_id = f"slot #{slot}"
        problems.append("id must be a short string of letters, digits, - or _: use the template form, e.g. Q031")

    raw_type = entry.get("expected_type")
    if raw_type in EXPECTED_TYPES:
        shown_type = raw_type
    else:
        shown_type = "?"
        echoed = raw_type if isinstance(raw_type, str) and _TYPE_RE.fullmatch(raw_type) else "value not echoed"
        problems.append(
            f"expected_type must be one of {', '.join(EXPECTED_TYPES)} (found: {echoed}): pick one of the four"
        )

    for name in ("batch", "question", "expected_answer_summary", "notes"):
        if name in entry and entry[name] is not None and not isinstance(entry[name], str):
            problems.append(f'{name} must be a string: put it in quotes, or use "" when empty')

    written = isinstance(entry.get("question"), str) and not _is_blank(entry.get("question"))

    gold: list[str] = []
    if written:
        gold, gold_problems = _gold_problems(entry.get("gold_pages"), shown_type, pages)
        problems.extend(gold_problems)

    if problems:
        return Row(slot, shown_id, shown_type, FAIL, gold, problems), None
    if not written:
        return Row(slot, shown_id, shown_type, NOT_WRITTEN), None

    question = {
        "id": raw_id,
        "batch": entry.get("batch") or "",
        "question": entry["question"].strip(),
        "expected_type": raw_type,
        "gold_pages": list(gold),
    }
    return Row(slot, shown_id, shown_type, PASS, gold), question


def check(questions_path: Path = DEFAULT_QUESTIONS, pages_path: Path = DEFAULT_PAGES) -> Report:
    report = Report()

    try:
        pages = load_page_map(pages_path)
    except (OSError, ValueError, KeyError) as exc:
        report.file_problems.append(
            f"cannot read the page map ({type(exc).__name__}): check that {pages_path} exists and is "
            "the canonical extraction"
        )
        return report
    report.page_map = pages
    report.file_problems.extend(
        f"page map: {problem}: the extraction no longer matches the layout profile in config.py — "
        "re-check the ingest before trusting any gold label"
        for problem in pages.problems
    )

    try:
        loaded = yaml.safe_load(Path(questions_path).read_text(encoding="utf-8"))
    except OSError as exc:
        report.file_problems.append(
            f"cannot read the question file ({type(exc).__name__}): check the path {questions_path}"
        )
        return report
    except yaml.YAMLError as exc:
        # The parser's own message quotes the offending lines. Report position only.
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        report.file_problems.append(
            f"question file is not valid YAML{where}: fix the quoting or indentation there"
        )
        return report

    entries = loaded.get("questions") if isinstance(loaded, dict) else None
    if not isinstance(entries, list):
        report.file_problems.append(
            "question file needs a top-level `questions` list: restore it from the template"
        )
        return report

    seen_ids: set[str] = set()
    for slot, entry in enumerate(entries, start=1):
        row, question = _check_entry(entry, slot, seen_ids, pages)
        report.rows.append(row)
        if question is not None:
            report.questions.append(question)
    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def format_table(report: Report) -> str:
    lines: list[str] = []

    for problem in report.file_problems:
        lines.append(f"FILE PROBLEM: {problem}")
    if report.file_problems:
        lines.append("")

    if report.rows:
        lines.append(f"{'ID':<10} {'TYPE':<13} {'STATUS':<16} GOLD")
        for row in report.rows:
            gold = ",".join(row.gold) if row.gold else "-"
            lines.append(f"{row.id:<10} {row.expected_type:<13} {row.status:<16} {gold}".rstrip())
            # One line per problem: what is wrong, then what to do about it.
            lines.extend(f"    -> {problem}" for problem in row.problems)
        lines.append("")

        lines.append(f"{'CATEGORY':<13} {'PASS':>5} {'FAIL':>5} {'NOT WRITTEN':>12} {'TARGET':>7}  AGAINST TARGET")
        for name, c in report.category_counts().items():
            written = c["pass"] + c["fail"]
            short = c["target"] - written
            if short > 0:
                note = f"{written}/{c['target']} written, {short} to go"
            elif short < 0:
                note = f"{written}/{c['target']} written, {-short} over target"
            else:
                note = f"{written}/{c['target']} written, target met"
            lines.append(
                f"{name:<13} {c['pass']:>5} {c['fail']:>5} {c['not_written']:>12} {c['target']:>7}  {note}"
            )
        lines.append("")

    verdict = "PASS" if report.ok else "FAIL"
    lines.append(
        f"RESULT: {verdict} — {len(report.questions)} passed, {len(report.failed)} failed, "
        f"{len(report.not_written)} not written yet"
        + (f", {len(report.file_problems)} file problem(s)" if report.file_problems else "")
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the gold question file.")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--pages", type=Path, default=DEFAULT_PAGES)
    args = parser.parse_args(argv)

    report = check(args.questions, args.pages)
    print(format_table(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
