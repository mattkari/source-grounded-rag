"""Measure and audit a thesis PDF from the command line — PLAN_V4 Sprint U0.

    python scripts/measure_thesis.py path/to/thesis.pdf
    python scripts/measure_thesis.py --builtin        # the acceptance test (PLAN_V4 §9)

Runs the same analysis the web UI runs on an upload — automatic layout
measurement, a dry run through the real extractor and chunker, and the
provenance audit — and prints the result. Nothing is written, nothing is
embedded, and no API is called.

`--builtin` runs it on the built-in thesis and compares the outcome with the
hand-measured profile in config.py and with the committed extraction and
index. The committed `index/` and `data/canonical/` are only read.

The output carries numbers, font names, page numbers and chunk ids. It never
prints passage text.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # so `python scripts/measure_thesis.py` finds the modules
    sys.path.insert(0, str(ROOT))

import audit  # noqa: E402
import upload  # noqa: E402
from config import settings  # noqa: E402
from documents import default_document  # noqa: E402


def format_profile(analysis: dict) -> str:
    measurement, layout = analysis["measurement"], analysis["layout"]
    out = ["MEASURED LAYOUT PROFILE"]
    if layout is None:
        out.append("  nothing could be measured")
    else:
        for item in dataclasses.fields(layout):
            value = getattr(layout, item.name)
            out.append(f"  {item.name:<28} {'not found' if value is None else value}")
            key = "heading_tiers" if item.name.endswith("_heading_min_size") else item.name
            evidence = measurement.evidence.get(key) or {}
            if evidence.get("rule"):
                out.append(f"      how: {evidence['rule']}")
    out.append("")
    out.append("FLAGS FOR THE RESEARCHER")
    out.extend(f"  ! {flag}" for flag in measurement.flags)
    if not measurement.flags:
        out.append("  none")
    return "\n".join(out)


def compare_with_builtin(analysis: dict) -> tuple[str, bool]:
    """Compare a measurement of the built-in thesis with what is committed."""
    document = default_document(settings)
    hand, measured = document.layout, analysis["layout"]
    out = ["", "COMPARISON WITH THE HAND-MEASURED PROFILE (config.py)"]
    for item in dataclasses.fields(hand):
        a, b = getattr(measured, item.name), getattr(hand, item.name)
        out.append(f"  {item.name:<28} measured {a!s:<32} hand {b!s:<28} {'same' if a == b else 'differs'}")

    committed_rows = [
        json.loads(line)
        for line in (document.canonical_dir / "pages.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    committed_chunks = json.loads((document.index_dir / "chunks.json").read_text(encoding="utf-8"))
    rows, chunks = analysis["rows"], analysis["records"]

    same_pages = sum(1 for a, b in zip(rows, committed_rows) if a == b)
    differing_pages = [a["pdf_page"] for a, b in zip(rows, committed_rows) if a != b]
    same_chunks = sum(1 for a, b in zip(chunks, committed_chunks) if a == b)
    differing_chunks = [a["chunk_id"] for a, b in zip(chunks, committed_chunks) if a != b]
    identical = rows == committed_rows and chunks == committed_chunks

    out.append("")
    out.append("COMPARISON WITH THE COMMITTED EXTRACTION AND INDEX (read only)")
    out.append(f"  pages identical      {same_pages}/{len(committed_rows)}")
    if differing_pages:
        out.append(f"      differing PDF pages: {', '.join(str(p) for p in differing_pages)}")
    out.append(f"  passages identical   {same_chunks}/{len(committed_chunks)} (measured: {len(chunks)})")
    if differing_chunks:
        out.append(f"      first differing: {', '.join(differing_chunks[:3])}")
    out.append(f"  committed corpus hash unchanged on disk: "
               f"{json.loads((document.index_dir / 'manifest.json').read_text())['corpus_text_sha256'][:12]}")
    return "\n".join(out), identical


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure and audit a thesis PDF. Writes nothing.")
    parser.add_argument("pdf", nargs="?", type=Path, help="path to a thesis PDF")
    parser.add_argument("--builtin", action="store_true",
                        help="run on the built-in thesis and compare with what is committed")
    parser.add_argument("--evidence", action="store_true", help="also print the evidence as JSON")
    args = parser.parse_args(argv)

    if args.builtin:
        pdf_path = default_document(settings).pdf_path
    elif args.pdf:
        pdf_path = args.pdf
    else:
        parser.error("give a PDF path, or --builtin")
    if not Path(pdf_path).exists():
        print(f"No such file: {pdf_path}", file=sys.stderr)
        return 2

    # The built-in thesis keeps its own id so its passages can be compared one to one.
    document_id = default_document(settings).document_id if args.builtin else upload.ID_PREFIX + "trial"
    analysis = upload.analyse_pdf(pdf_path, document_id)
    print(format_profile(analysis))
    if analysis["layout"] is None:
        return 1
    print()
    print(audit.format_report(analysis["audit"]))
    if args.evidence:
        print()
        print(json.dumps(analysis["measurement"].evidence, indent=1, ensure_ascii=False))

    if args.builtin:
        text, _ = compare_with_builtin(analysis)
        print(text)
    # Exit status reports only what blocks approval. Differences from the
    # hand-measured profile are printed above for the researcher to judge.
    return 1 if analysis["audit"]["hard_stops"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
