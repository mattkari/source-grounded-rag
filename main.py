"""Interactive CLI for the source-grounded research assistant.

    python main.py                     # interactive loop
    python main.py --verbose-provenance
    python main.py -k 8

This is a shell, not a pipeline. Every question goes through ask.run_query —
the same retrieval, generation, validation, and citation resolution that
`python ask.py "<question>"` uses. Nothing about grounding, refusal,
interpretation labelling, or footnotes is reimplemented here.
"""

from __future__ import annotations

import argparse
import sys

import ask
from config import settings

EXIT_WORDS = {"exit", "quit", "q", ":q", "\\q"}
HELP_WORDS = {"help", "?", "\\h"}

BANNER = """\
╭──────────────────────────────────────────────────────────────────────────╮
│  Source-Grounded Research Assistant — interactive mode                   │
╰──────────────────────────────────────────────────────────────────────────╯
Collection : {title}
Index      : {chunks} passages · {model} · {dim}d
Answers are grounded in this collection only. When the collection lacks
evidence, the assistant refuses rather than filling the gap.

Type a question, or "exit" to quit ("help" for commands).
"""

HELP = """\
Commands
  exit | quit | q     leave the session
  help | ?            this message
  verbose             toggle chunk ids + verbatim passages under footnotes
Anything else is treated as a question against the collection.
"""


def read_question(prompt: str = "> ") -> str | None:
    """Return the next question, or None when the user is done.

    Ctrl+D (EOF) and Ctrl+C both end the session cleanly — no stack trace.
    """
    try:
        return input(prompt)
    except EOFError:
        print()
        return None
    except KeyboardInterrupt:
        print("\n(interrupted)")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interactive query loop over the authorised research collection."
    )
    parser.add_argument("-k", "--top-k", type=int, default=settings.top_k)
    parser.add_argument(
        "--verbose-provenance",
        action="store_true",
        help="start with chunk ids and verbatim passages shown under each footnote",
    )
    args = parser.parse_args()

    # Loaded once for the whole session, not per question.
    try:
        vectors, chunks, manifest = ask.load_index()
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    verbose = args.verbose_provenance
    print(
        BANNER.format(
            title=settings.document_short_title,
            chunks=manifest["chunk_count"],
            model=manifest["embedding_model"],
            dim=manifest["embedding_dim"],
        )
    )

    asked = 0
    while True:
        question = read_question()
        if question is None:
            break

        question = question.strip()
        if not question:
            continue
        if question.lower() in EXIT_WORDS:
            break
        if question.lower() in HELP_WORDS:
            print(HELP)
            continue
        if question.lower() == "verbose":
            verbose = not verbose
            print(f"verbose provenance: {'on' if verbose else 'off'}\n")
            continue

        try:
            outcome = ask.run_query(question, vectors, chunks, args.top_k)
        except KeyboardInterrupt:
            # Abandon this question, keep the session alive.
            print("\n(cancelled)\n")
            continue
        except Exception as exc:  # provider error, malformed output, network
            # Never swallow a failure: report it and keep the loop usable.
            print(f"\n!! query failed: {type(exc).__name__}: {exc}\n", file=sys.stderr)
            continue

        asked += 1
        print()
        print(outcome.rendered(verbose))

        if not outcome.grounded:
            print("\n" + "!" * 74)
            print("VALIDATION FAILED — this answer is not certified grounded:")
            for failure in outcome.failures:
                print(f"  ✗ {failure}")
            print("!" * 74)
        print()

    print(f"\nSession ended — {asked} question(s) asked. Goodbye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
